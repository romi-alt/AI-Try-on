import { config } from "./config";
import type { Garment, PresignResponse, Session, TryOnJob } from "./types";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${config.apiUrl}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  listGarments: (category?: Garment["category"]) =>
    request<Garment[]>(`/garments${category ? `?category=${category}` : ""}`),

  createSession: (kioskId: string) =>
    request<Session>("/sessions", { method: "POST", body: JSON.stringify({ kiosk_id: kioskId }) }),

  endSession: (sessionId: string) => request<Session>(`/sessions/${sessionId}/end`, { method: "POST" }),

  presignUpload: (contentType: string, kind: "capture" | "garment" = "capture") =>
    request<PresignResponse>("/uploads/presign", {
      method: "POST",
      body: JSON.stringify({ content_type: contentType, kind }),
    }),

  /** PUT raw bytes straight to object storage (MinIO locally, R2 in prod). */
  uploadToPresigned: async (uploadUrl: string, blob: Blob) => {
    const res = await fetch(uploadUrl, {
      method: "PUT",
      body: blob,
      headers: { "Content-Type": blob.type },
    });
    if (!res.ok) throw new ApiError(res.status, "Upload failed");
  },

  createTryOnJob: (sessionId: string, garmentId: string, captureKey: string) =>
    request<TryOnJob>("/tryon", {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId, garment_id: garmentId, capture_key: captureKey }),
    }),

  getTryOnJob: (jobId: string) => request<TryOnJob>(`/tryon/${jobId}`),
};

export { ApiError };
