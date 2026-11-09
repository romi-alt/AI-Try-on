// Mirrors services/api/app/schemas. Keep in sync.

export type Category = "top" | "bottom" | "dress" | "shoes" | "bag" | "accessory";

export const CATEGORIES: { value: Category; label: string }[] = [
  { value: "top", label: "Top" },
  { value: "bottom", label: "Bottom" },
  { value: "dress", label: "Dress" },
  { value: "shoes", label: "Shoes" },
  { value: "bag", label: "Bag" },
  { value: "accessory", label: "Accessory" },
];

export const categoryLabel = (c: Category) => CATEGORIES.find((x) => x.value === c)?.label ?? c;

export type ColorOption = { name: string; hex: string };

export type ProcessingStatus = "idle" | "queued" | "processing" | "done" | "failed";

export type Product = {
  id: string;
  sku: string | null;
  name: string;
  category: Category;
  price_pkr: number;
  sale_price_pkr: number | null;
  sizes: string[];
  colors: ColorOption[];
  stock: number;
  garment_image_url: string;
  garment_mask_url: string | null;
  garment_original_url: string | null;
  has_embedding: boolean;
  embedding_updated_at: string | null;
  processing_status: ProcessingStatus;
  processing_error: string | null;
  created_at: string;
  on_sale: boolean;
  current_price_pkr: number;
};

/** The writable fields of a product (POST /products). */
export type ProductInput = {
  sku: string | null;
  name: string;
  category: Category;
  price_pkr: number;
  sale_price_pkr: number | null;
  sizes: string[];
  colors: ColorOption[];
  stock: number;
  garment_image_url: string;
  garment_mask_url: string | null;
};

export type CatalogPage = { items: Product[]; total: number; page: number; page_size: number; pages: number };

export type AdminSession = { id: string; started_at: string; consent_given: boolean; job_count: number };

export type JobStatus = "queued" | "processing" | "done" | "failed";

export type Job = {
  id: string;
  session_id: string;
  product_ids: string[];
  status: JobStatus;
  progress: number;
  capture_key: string;
  result_url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type Stats = {
  products_in_stock: number;
  sessions_today: number;
  jobs_today: number;
  jobs_failed_today: number;
  /** -1 when Redis could not be reached. */
  queue_depth: number;
};

export type PresignResponse = { key: string; upload_url: string; public_url: string; expires_in: number };
export type UploadCheck = { key: string; size_bytes: number; content_type: string; public_url: string };

/** `GET /orders`: a placed order, with names and prices as they were at checkout. Paid for at the counter. */
export type OrderItem = {
  product_id: string;
  product_name: string;
  size: string | null;
  color: string | null;
  quantity: number;
  unit_price_pkr: number;
  line_total_pkr: number;
};
export type OrderStatus = "placed" | "collected" | "cancelled";
export type Order = {
  id: string;
  session_id: string | null;
  pickup_code: string;
  status: OrderStatus;
  item_count: number;
  subtotal_pkr: number;
  created_at: string;
  status_changed_at: string | null;
  items: OrderItem[];
};

/** `POST /products/{id}/process` and `POST /products/embeddings`. */
export type AssetJobAccepted = { job_id: string; products: number };

/** `POST /products/import` */
export type ImportRow = { line: number; action: "create" | "update" | "error"; sku: string | null; name: string | null; errors: string[] };
export type ImportReport = {
  dry_run: boolean;
  applied: boolean;
  created: number;
  updated: number;
  error_count: number;
  rows: ImportRow[];
  embedding_job_id: string | null;
};

/** `GET /admin/analytics` */
export type ProductTryOnStats = { product_id: string; name: string; category: string | null; tryons: number; added_to_cart: number; cart_rate: number | null };
export type PairingStats = {
  base_product_id: string;
  base_name: string;
  recommended_product_id: string;
  recommended_name: string;
  tryons: number;
  added_to_cart: number;
};
export type Analytics = {
  days: number;
  since: string;
  tryons: number;
  tryons_with_cart: number;
  cart_rate: number | null;
  products: ProductTryOnStats[];
  pairings: PairingStats[];
};
