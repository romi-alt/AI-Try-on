// Mirrors services/api/app/schemas. Keep in sync.

export type Category = "top" | "bottom" | "dress" | "shoes" | "bag" | "accessory";

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
  /** What the shopper pays: the sale price when on sale, else the regular price. */
  current_price_pkr: number;
};

export type CatalogPage = {
  items: Product[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
};

export type Session = { id: string; started_at: string; consent_given: boolean };

export type CaptureResult = {
  key: string;
  width: number;
  height: number;
  content_type: string;
  size_bytes: number;
  expires_in_seconds: number;
};

export type JobStatus = "queued" | "processing" | "done" | "failed";

/** One update about a job: a WebSocket message, or `GET /jobs/{id}` reduced to the same fields. */
export type JobUpdate = {
  job: string;
  status: JobStatus;
  pct: number;
  url?: string | null;
  error?: string | null;
};

/** `GET /jobs/{id}` */
export type JobState = JobUpdate & { updated_at: string };

export type TryOnAccepted = { job_id: string; status: JobStatus; channel: string };

export type CartItem = {
  id: string;
  product: { id: string; name: string; category: Category; garment_image_url: string };
  size: string | null;
  color: string | null;
  quantity: number;
  unit_price_pkr: number;
  line_total_pkr: number;
};

export type Cart = {
  session_id: string;
  cart_id: string | null;
  items: CartItem[];
  item_count: number;
  subtotal_pkr: number;
};
