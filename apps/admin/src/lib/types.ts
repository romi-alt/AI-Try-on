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

export type Product = {
  id: string;
  name: string;
  category: Category;
  price_pkr: number;
  sale_price_pkr: number | null;
  sizes: string[];
  colors: ColorOption[];
  stock: number;
  garment_image_url: string;
  garment_mask_url: string | null;
  created_at: string;
  on_sale: boolean;
  current_price_pkr: number;
};

/** The writable fields of a product (POST /products). */
export type ProductInput = {
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
export type Order = {
  id: string;
  session_id: string | null;
  pickup_code: string;
  item_count: number;
  subtotal_pkr: number;
  created_at: string;
  items: OrderItem[];
};
