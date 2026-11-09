/** A non-negative number of seconds from an environment value, or the fallback if it is missing or not a number. */
export function parseSeconds(raw: string | undefined, fallback: number): number {
  if (raw === undefined || raw.trim() === "") return fallback;
  const n = Number(raw);
  return Number.isFinite(n) && n >= 0 ? n : fallback;
}

const apiUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export const config = {
  apiUrl,
  // WebSocket base. Defaults to the API's own host (http -> ws, https -> wss).
  wsUrl: (process.env.NEXT_PUBLIC_WS_URL ?? apiUrl.replace(/^http/, "ws")).replace(/\/$/, ""),

  // The address phones use to open the mobile page (the QR code points here). Empty: this kiosk's own address.
  publicUrl: (process.env.NEXT_PUBLIC_PUBLIC_URL ?? "").replace(/\/$/, ""),

  // MediaPipe delegate for pose guidance: CPU (default; about 30 ms a frame, no GPU surprises) or GPU.
  poseDelegate: process.env.NEXT_PUBLIC_POSE_DELEGATE === "GPU" ? ("GPU" as const) : ("CPU" as const),

  // Capture: the API requires a portrait JPEG/WebP at least 768px tall and at most 5 MB.
  // A webcam frame is landscape, so it is cropped to 3:4 and scaled to this size.
  captureWidth: Number(process.env.NEXT_PUBLIC_CAPTURE_WIDTH ?? 864),
  captureHeight: Number(process.env.NEXT_PUBLIC_CAPTURE_HEIGHT ?? 1152),
  captureQuality: 0.9,
  countdownSeconds: Number(process.env.NEXT_PUBLIC_COUNTDOWN_SECONDS ?? 3),

  catalogPageSize: 12,
  searchDebounceMs: 300,
  maxOutfitItems: 5, // POST /tryon accepts 1-5 products
  // A try-on that takes longer than this offers "Try again" (the job itself keeps going in the background).
  tryOnSlowMs: parseSeconds(process.env.NEXT_PUBLIC_TRYON_SLOW_SECONDS, 60) * 1000,

  // Idle timeout: after 45s without input a "still there?" screen appears, and if nobody answers within the 15s
  // grace period (60s in all) the session ends and the kiosk returns to the attract screen. 0 turns it off.
  idleWarnSeconds: parseSeconds(process.env.NEXT_PUBLIC_IDLE_WARN_SECONDS, 45),
  idleGraceSeconds: parseSeconds(process.env.NEXT_PUBLIC_IDLE_GRACE_SECONDS, 15),

  // Following a job
  pollIntervalMs: 2000, // used while the WebSocket is down
  reconnectMinMs: 500,
  reconnectMaxMs: 10_000,
  staleSocketMs: 60_000, // the server pings every 25s; silence for this long means a dead connection
  jobTimeoutMs: 330_000, // just past the worker's own 300s limit, so the server's answer wins
} as const;
