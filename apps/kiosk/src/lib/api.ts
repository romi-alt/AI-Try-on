import { config } from "./config";
import type {
  Cart,
  CaptureResult,
  CatalogPage,
  Category,
  JobState,
  Product,
  Session,
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
      throw new ApiError(0, "The mirror's server took too long to answer. Please try again.");
    }
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
  category?: Category | "all";
  onSale?: boolean;
  search?: string;
  page?: number;
  pageSize?: number;
};

export const api = {
  /** Starts a session. The API refuses to without the shopper's consent. */
  createSession: () =>
    request<Session>("/sessions", { method: "POST", body: JSON.stringify({ consent_given: true }) }),

  listCatalog: ({ category, onSale, search, page = 1, pageSize = config.catalogPageSize }: CatalogQuery = {}) => {
    const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (category && category !== "all") q.set("category", category);
    if (onSale) q.set("on_sale", "true");
    if (search?.trim()) q.set("search", search.trim());
    return request<CatalogPage>(`/catalog?${q}`);
  },

  getProduct: (id: string) => request<Product>(`/products/${id}`),

  /** Uploads the webcam photo. The API validates it, strips metadata and returns the storage key. */
  uploadCapture: (sessionId: string, photo: Blob) => {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("file", photo, "capture.jpg");
    return request<CaptureResult>("/capture", { method: "POST", body: form }, UPLOAD_TIMEOUT_MS);
  },

  createTryOn: (sessionId: string, captureKey: string, productIds: string[]) =>
    request<TryOnAccepted>("/tryon", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, capture_key: captureKey, product_ids: productIds }),
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

  /** Removes one whole line and returns the updated cart. A line that is already gone is a 404. */
  removeFromCart: (sessionId: string, itemId: string) =>
    request<Cart>(`/cart/${sessionId}/items/${itemId}`, { method: "DELETE" }),
};
