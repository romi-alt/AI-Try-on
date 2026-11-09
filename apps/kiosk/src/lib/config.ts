const apiUrl = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export const config = {
  apiUrl,
  // WebSocket base. Defaults to the API's own host (http -> ws, https -> wss).
  wsUrl: (process.env.NEXT_PUBLIC_WS_URL ?? apiUrl.replace(/^http/, "ws")).replace(/\/$/, ""),

  // Capture: the API requires a portrait JPEG/WebP at least 768px tall and at most 5 MB.
  // A webcam frame is landscape, so it is cropped to 3:4 and scaled to this size.
  captureWidth: Number(process.env.NEXT_PUBLIC_CAPTURE_WIDTH ?? 864),
  captureHeight: Number(process.env.NEXT_PUBLIC_CAPTURE_HEIGHT ?? 1152),
  captureQuality: 0.9,
  countdownSeconds: Number(process.env.NEXT_PUBLIC_COUNTDOWN_SECONDS ?? 3),

  catalogPageSize: 12,
  searchDebounceMs: 300,
  maxOutfitItems: 5, // POST /tryon accepts 1-5 products

  // Following a job
  pollIntervalMs: 2000, // used while the WebSocket is down
  reconnectMinMs: 500,
  reconnectMaxMs: 10_000,
  staleSocketMs: 60_000, // the server pings every 25s; silence for this long means a dead connection
  jobTimeoutMs: 330_000, // just past the worker's own 300s limit, so the server's answer wins
} as const;
