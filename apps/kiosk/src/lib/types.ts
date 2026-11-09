// Mirrors services/api/app/schemas. Keep in sync.

export type Garment = {
  id: string;
  sku: string;
  name: string;
  brand: string | null;
  category: "top" | "bottom" | "dress" | "outerwear" | "accessory";
  color: string | null;
  price_cents: number | null;
  image_key: string;
  image_url: string;
  is_active: boolean;
  created_at: string;
};

export type Session = {
  id: string;
  kiosk_id: string;
  started_at: string;
  ended_at: string | null;
};

export type JobStatus = "queued" | "processing" | "done" | "failed";

export type TryOnJob = {
  id: string;
  session_id: string;
  garment_id: string;
  status: JobStatus;
  capture_key: string;
  result_key: string | null;
  result_url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type PresignResponse = {
  key: string;
  upload_url: string;
  public_url: string;
  expires_in: number;
};
