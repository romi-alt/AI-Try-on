import type { JobStatus } from "./types";

export const shortId = (id: string) => id.slice(0, 8);

/** "8s", "1m 12s", or "-" when it cannot be worked out. */
export function formatDuration(startIso: string, endIso: string): string {
  const ms = new Date(endIso).getTime() - new Date(startIso).getTime();
  if (!Number.isFinite(ms) || ms < 0) return "-";
  const s = Math.round(ms / 1000);
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

/** Names for a job's products, in order. A product that was deleted since shows as removed. */
export function productNames(ids: string[], names: ReadonlyMap<string, string>): string[] {
  return ids.map((id) => names.get(id) ?? "(removed product)");
}

export const STATUS_STYLE: Record<JobStatus, string> = {
  queued: "bg-neutral-200 text-neutral-700",
  processing: "bg-blue-100 text-blue-800",
  done: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

/**
 * When a presigned (SigV4) URL stops working, read from its own `X-Amz-Date` and `X-Amz-Expires`, so this stays
 * right whatever lifetime the worker was configured with. Null for a URL that is not presigned.
 */
export function signedUrlExpiry(url: string): Date | null {
  let params: URLSearchParams;
  try {
    params = new URL(url).searchParams;
  } catch {
    return null;
  }
  const date = params.get("X-Amz-Date");
  const seconds = Number(params.get("X-Amz-Expires"));
  const m = date?.match(/^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/);
  if (!m || !Number.isFinite(seconds) || seconds <= 0) return null;
  const signedAt = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
  return new Date(signedAt + seconds * 1000);
}

export function linkExpired(url: string, now: number = Date.now()): boolean {
  const expiry = signedUrlExpiry(url);
  return expiry !== null && expiry.getTime() <= now;
}
