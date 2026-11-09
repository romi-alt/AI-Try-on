import { config } from "./config";
import type {
  AdminSession,
  Analytics,
  AssetJobAccepted,
  ImportReport,
  CatalogPage,
  Category,
  Job,
  Order,
  OrderStatus,
  PresignResponse,
  Product,
  ProductInput,
  Stats,
  UploadCheck,
} from "./types";

/** An API failure carrying a message that is fit to show an admin. */
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
      .map((d) => {
        if (!d || typeof d !== "object" || !("msg" in d)) return "";
        const loc = (d as { loc?: unknown[] }).loc;
        const field = Array.isArray(loc) ? loc.filter((p) => typeof p === "string" && p !== "body").join(".") : "";
        const msg = String((d as { msg: unknown }).msg).replace(/^Value error, /, "");
        return field ? `${field}: ${msg}` : msg;
      })
      .filter(Boolean);
    if (msgs.length) return msgs.join(". ");
  }
  return fallback;
}

const DEFAULT_TIMEOUT_MS = 15_000;
const UPLOAD_TIMEOUT_MS = 60_000;
const SIGNED_OUT = "Your session has ended. Sign in again.";

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");

  let res: Response;
  try {
    res = await fetch(`${config.apiUrl}${path}`, {
      ...init,
      headers,
      cache: "no-store",
      signal: init.signal ?? AbortSignal.timeout(timeoutMs),
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "TimeoutError") {
      throw new ApiError(0, "The API took too long to answer.");
    }
    throw new ApiError(0, "Can't reach the admin server.");
  }

  if (!res.ok) {
    if (res.status === 401) {
      // The proxy answers 401 only when the NextAuth session has expired.
      if (typeof window !== "undefined") window.location.href = "/login";
      throw new ApiError(401, SIGNED_OUT);
    }
    let detail: unknown;
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, messageFromDetail(detail, res.statusText || "Something went wrong."));
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export type ProductQuery = {
  category?: Category | "all";
  search?: string;
  onSale?: boolean;
  page?: number;
  pageSize?: number;
};

export const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;

export const api = {
  stats: () => request<Stats>("/admin/stats"),

  /** The catalog endpoint lists every product, sold out or not, which is what an admin wants. */
  listProducts: ({ category, search, onSale, page = 1, pageSize = config.productsPageSize }: ProductQuery = {}) => {
    const q = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
    if (category && category !== "all") q.set("category", category);
    if (onSale) q.set("on_sale", "true");
    if (search?.trim()) q.set("search", search.trim());
    return request<CatalogPage>(`/catalog?${q}`);
  },

  /** Every product, following the pages. Used to show product names on the jobs page. */
  listAllProducts: async (): Promise<Product[]> => {
    const all: Product[] = [];
    for (let page = 1; page <= 20; page++) {
      const res = await request<CatalogPage>(`/catalog?page=${page}&page_size=100`);
      all.push(...res.items);
      if (page >= res.pages) break;
    }
    return all;
  },

  createProduct: (input: ProductInput) =>
    request<Product>("/products", { method: "POST", body: JSON.stringify(input) }),

  /** Only the fields present are changed. Send `null` explicitly to clear an optional field. */
  updateProduct: (id: string, patch: Partial<ProductInput>) =>
    request<Product>(`/products/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),

  deleteProduct: (id: string) => request<void>(`/products/${id}`, { method: "DELETE" }),

  /**
   * Uploads an image straight to object storage and returns the URL to store on the product:
   * ask the API for a presigned PUT URL, PUT the file to it, then have the API check what arrived.
   * A presigned PUT cannot limit the size, so that last step is what refuses (and deletes) an oversized file.
   */
  uploadImage: async (file: File): Promise<string> => {
    const presign = await request<PresignResponse>("/uploads/presign", {
      method: "POST",
      body: JSON.stringify({ content_type: file.type, kind: "garment" }),
    });
    let res: Response;
    try {
      res = await fetch(presign.upload_url, {
        method: "PUT",
        body: file,
        headers: { "Content-Type": file.type },
        signal: AbortSignal.timeout(UPLOAD_TIMEOUT_MS),
      });
    } catch {
      throw new ApiError(
        0,
        "Couldn't upload the image. If the API is fine, the storage bucket probably needs a CORS rule allowing PUT from this site.",
      );
    }
    if (!res.ok) throw new ApiError(res.status, `The storage service rejected the upload (HTTP ${res.status}).`);
    const checked = await request<UploadCheck>("/uploads/verify", {
      method: "POST",
      body: JSON.stringify({ key: presign.key }),
    });
    return checked.public_url;
  },

  /**
   * Recent orders, newest first. `code` finds one by its pickup code (the API ignores case and spaces) and `status`
   * keeps only orders in that state.
   */
  listOrders: ({ code, status, limit = config.listLimit }: { code?: string; status?: OrderStatus; limit?: number } = {}) => {
    const q = new URLSearchParams({ limit: String(limit) });
    if (code?.trim()) q.set("code", code.trim());
    if (status) q.set("status", status);
    return request<Order[]>(`/orders?${q}`);
  },

  /**
   * Closes a waiting order. Cancelling puts its items back into stock. Asking for the state an order is already in
   * is harmless; switching a closed order to the other state is a 409.
   */
  setOrderStatus: (id: string, status: "collected" | "cancelled") =>
    request<Order>(`/orders/${id}`, { method: "PATCH", body: JSON.stringify({ status }) }),

  /**
   * Queue background removal and a garment mask for a product's image (and a fresh embedding unless `reembed` is
   * false). Progress shows in the product's `processing_status`. A product already being processed is a 409.
   */
  processProduct: (id: string, reembed = true) =>
    request<AssetJobAccepted>(`/products/${id}/process?reembed=${reembed}`, { method: "POST" }),

  /** Queue FashionCLIP embeddings for some products, or (no ids) the whole catalog. */
  regenerateEmbeddings: ({ productIds, onlyMissing = false }: { productIds?: string[]; onlyMissing?: boolean } = {}) =>
    request<AssetJobAccepted>("/products/embeddings", {
      method: "POST",
      body: JSON.stringify({ product_ids: productIds ?? null, only_missing: onlyMissing }),
    }),

  /** Bulk create/update from CSV text. `dryRun` checks the file and saves nothing. All or nothing. */
  importProducts: (csv: Blob | string, { dryRun }: { dryRun: boolean }) =>
    request<ImportReport>(`/products/import?dry_run=${dryRun}`, { method: "POST", body: csv, headers: { "Content-Type": "text/csv" } }, UPLOAD_TIMEOUT_MS),

  analytics: (days: number, limit = 10) => request<Analytics>(`/admin/analytics?days=${days}&limit=${limit}`),

  listSessions: (limit: number = config.listLimit) => request<AdminSession[]>(`/sessions?limit=${limit}`),

  listJobs: (limit: number = config.listLimit) => request<Job[]>(`/tryon?limit=${limit}`),
};
