export const config = {
  apiUrl: process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  mediaBaseUrl: process.env.NEXT_PUBLIC_MEDIA_BASE_URL ?? "http://localhost:9000/tryon-media",
  kioskId: process.env.NEXT_PUBLIC_KIOSK_ID ?? "dev-laptop",
  captureWidth: Number(process.env.NEXT_PUBLIC_CAPTURE_WIDTH ?? 720),
  captureHeight: Number(process.env.NEXT_PUBLIC_CAPTURE_HEIGHT ?? 960),
  pollIntervalMs: 1500,
  jobTimeoutMs: 90_000,
} as const;
