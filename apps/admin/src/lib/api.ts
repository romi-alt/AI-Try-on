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

export type GarmentInput = Omit<Garment, "id" | "image_url" | "created_at">;

export type Session = {
  id: string;
  kiosk_id: string;
  started_at: string;
  ended_at: string | null;
  job_count: number;
};

export type TryOnJob = {
  id: string;
  session_id: string;
  garment_id: string;
  status: "queued" | "processing" | "done" | "failed";
  capture_key: string;
  result_key: string | null;
  result_url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
};

export type Stats = {
  garments_active: number;
  sessions_today: number;
  jobs_today: number;
  jobs_failed_today: number;
  queue_depth: number;
};

export type PresignResponse = {
  key: string;
  upload_url: string;
  public_url: string;
  expires_in: number;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const ADMIN_KEY = process.env.NEXT_PUBLIC_ADMIN_API_KEY ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Admin-Key": ADMIN_KEY,
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new Error(`${res.status} ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  stats: () => request<Stats>("/admin/stats"),

  listGarments: (includeInactive = true) =>
    request<Garment[]>(`/garments?include_inactive=${includeInactive}`),
  createGarment: (input: GarmentInput) =>
    request<Garment>("/garments", { method: "POST", body: JSON.stringify(input) }),
  updateGarment: (id: string, patch: Partial<GarmentInput>) =>
    request<Garment>(`/garments/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteGarment: (id: string) => request<void>(`/garments/${id}`, { method: "DELETE" }),

  presignUpload: (contentType: string) =>
    request<PresignResponse>("/uploads/presign", {
      method: "POST",
      body: JSON.stringify({ content_type: contentType, kind: "garment" }),
    }),
  uploadToPresigned: async (uploadUrl: string, file: File) => {
    const res = await fetch(uploadUrl, { method: "PUT", body: file, headers: { "Content-Type": file.type } });
    if (!res.ok) throw new Error(`Upload failed (${res.status})`);
  },

  listSessions: (limit = 50) => request<Session[]>(`/sessions?limit=${limit}`),
  listJobs: (limit = 50) => request<TryOnJob[]>(`/tryon?limit=${limit}`),
};
