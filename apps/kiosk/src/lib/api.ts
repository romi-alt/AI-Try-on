import { config } from "./config";
import { connectivityBus } from "./connectivityBus";
import type {
  Cart,
  CaptureResult,
  CatalogPage,
  Category,
  JobState,
  MobileCheckout,
  MobileLook,
  Order,
  Product,
  Recommendations,
  Session,
  ShareLink,
  StaffRequest,
  TryOnAccepted,
} from "./types";

/** An API failure carrying a message that is fit to show a shopper (`detail` from FastAPI). */
export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** FastAPI sends `{detail: "text"}`, or `{detail: [{msg, loc, ...}]}` for validation errors. */
export function messageFromDetail(detail: unknown, fallback: string): string {
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d && typeof d === "object" && "msg" in d ? String((d as { msg: unknown }).msg) : ""))
      .filter(Boolean);
    if (msgs.length) return msgs.join(". ");
  }
  return fallback;
}

const DEFAULT_TIMEOUT_MS = 15_000;
const UPLOAD_TIMEOUT_MS = 60_000;

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const headers = new Headers(init.headers);
  // A FormData body must not get a Content-Type: the browser adds it with the multipart boundary.
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let res: Response;
  try {
    // A request that never answers (a half-open connection) must fail rather than hang forever.
    res = await fetch(`${config.apiUrl}${path}`, {
      ...init,
      headers,
      cache: "no-store",
      signal: init.signal ?? AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "TimeoutError") {
      connectivityBus.reportNetworkFailure();
      throw new ApiError(0, "The mirror's server took too long to answer. Please try again.");
    }
    connectivityBus.reportNetworkFailure();
    throw new ApiError(0, "Can't reach the mirror's server. Please check the connection and try again.");
  }

  if (!res.ok) {
    let detail: unknown;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, messageFromDetail(detail, res.statusText || "Something went wrong."));
  }
  return (await res.json()) as T;
}

export type CatalogQuery = {
  categories?: Category[];
  onSale?: boolean;
  /** Only items marked down by at least this percentage. */
  minDiscountPct?: number;
  /** Only items added in the last N days. */
  newWithinDays?: number;
  search?: string;
  page?: number;
  pageSize?: number;
};

export const api = {
  /** Starts a session. The API refuses to without the shopper's consent. */
  createSession: () =>
    request<Session>("/sessions", { method: "POST", body: JSON.stringify({ consent_given: true }) }),

  listCatalog: ({
    categories,
    onSale,
    minDiscountPct,
    newWithinDays,
    search,
    page = 1,
    pageSize = config.catalogPageSize,
  }: CatalogQuery = {}) => {
    const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    for (const c of categories ?? []) q.append("category", c);
    if (onSale) q.set("on_sale", "true");
    if (minDiscountPct) q.set("min_discount_pct", String(minDiscountPct));
    if (newWithinDays) q.set("new_within_days", String(newWithinDays));
    if (search?.trim()) q.set("search", search.trim());
    return request<CatalogPage>(`/catalog?${q}`);
  },

  /** More styles and "Complete your look" for the chosen items. */
  recommend: (productIds: string[]) =>
    request<Recommendations>(`/recommend?${new URLSearchParams({ product_ids: productIds.join(",") })}`),

  getProduct: (id: string) => request<Product>(`/products/${id}`),

  /** Uploads the webcam photo. The API validates it, strips metadata and returns the storage key. */
  uploadCapture: (sessionId: string, photo: Blob) => {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("file", photo, "capture.jpg");
    return request<CaptureResult>("/capture", { method: "POST", body: form }, UPLOAD_TIMEOUT_MS);
  },

  /** `recommendedIds`: the part of `productIds` the shopper added from the recommendations (for analytics). */
  createTryOn: (sessionId: string, captureKey: string, productIds: string[], recommendedIds: string[] = []) =>
    request<TryOnAccepted>("/tryon", {
      method: "POST",
      body: JSON.stringify({
        session_id: sessionId,
        capture_key: captureKey,
        product_ids: productIds,
        recommended_product_ids: recommendedIds,
      }),
    }),

  getJob: (jobId: string) => request<JobState>(`/jobs/${jobId}`),

  addToCart: (args: { sessionId: string; productId: string; size?: string | null; color?: string | null }) =>
    request<Cart>("/cart/add", {
      method: "POST",
      body: JSON.stringify({
        session_id: args.sessionId,
        product_id: args.productId,
        size: args.size ?? null,
        color: args.color ?? null,
        quantity: 1,
      }),
    }),

  getCart: (sessionId: string) => request<Cart>(`/cart/${sessionId}`),

  /**
   * Places an order for the whole cart. Send the same `idempotencyKey` when retrying after a failure that left the
   * outcome unknown (no answer, a server error): the API then returns the order if it was placed, not a second one.
   */
  checkout: (sessionId: string, idempotencyKey: string) =>
    request<Order>("/checkout", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, idempotency_key: idempotencyKey }),
    }),

  /** Sets one line's quantity (1 or more) and returns the updated cart. 409 when there is not enough stock. */
  setCartQuantity: (sessionId: string, itemId: string, quantity: number) =>
    request<Cart>(`/cart/${sessionId}/items/${itemId}`, { method: "PATCH", body: JSON.stringify({ quantity }) }),

  /** Removes one whole line and returns the updated cart. A line that is already gone is a 404. */
  removeFromCart: (sessionId: string, itemId: string) =>
    request<Cart>(`/cart/${sessionId}/items/${itemId}`, { method: "DELETE" }),

  /** A short code for the mobile page (`/m/{code}`) showing this session's cart and, optionally, one finished look. */
  createShare: (sessionId: string, jobId?: string | null) =>
    request<ShareLink>("/share", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, job_id: jobId ?? null }),
    }),

  /** "Request Outfit": ask staff to bring an item in a size. Asking again for the same open item is harmless. */
  requestOutfit: (args: { sessionId: string; productId: string; size: string | null; color: string | null }) =>
    request<StaffRequest>("/requests", {
      method: "POST",
      body: JSON.stringify({
        session_id: args.sessionId,
        product_id: args.productId,
        size: args.size,
        color: args.color,
      }),
    }),

  // --- the mobile page (/m/{code}): public, the code is the credential ---
  getMobileLook: (code: string) => request<MobileLook>(`/m/${encodeURIComponent(code)}`),
  mobileCheckout: (code: string, idempotencyKey: string) =>
    request<MobileCheckout>(`/m/${encodeURIComponent(code)}/checkout`, {
      method: "POST",
      body: JSON.stringify({ idempotency_key: idempotencyKey }),
    }),

  // --- the staff page: a staff key in X-Staff-Key ---
  listStaffRequests: (staffKey: string) =>
    request<StaffRequest[]>("/requests", { headers: { "X-Staff-Key": staffKey } }),
  updateStaffRequest: (staffKey: string, id: string, status: "bringing" | "done") =>
    request<StaffRequest>(`/requests/${id}`, {
      method: "PATCH",
      headers: { "X-Staff-Key": staffKey },
      body: JSON.stringify({ status }),
    }),
};
