export const dynamic = "force-dynamic";

/** Liveness for uptime monitors: the app is up and serving. It touches nothing else. */
export function GET() {
  return Response.json({ status: "ok" }, { headers: { "Cache-Control": "no-store" } });
}
