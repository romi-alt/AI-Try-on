/**
 * The admin app's server-side door to the API.
 *
 * The browser never holds the admin key: it calls `/api/proxy/<path>` on this app, which checks the NextAuth session
 * and forwards the request to the API with `X-Admin-Key` added from a server-only environment variable.
 */
export const PROXIED_PREFIXES = ["admin", "products", "orders", "sessions", "tryon", "catalog", "uploads", "jobs"] as const;

export type ProxyInput = {
  signedIn: boolean;
  method: string;
  /** Path segments after `/api/proxy/`. */
  path: string[];
  search: string;
  contentType: string | null;
  body: ArrayBuffer | null;
  apiUrl: string;
  adminKey: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
};

const json = (status: number, detail: string) =>
  new Response(JSON.stringify({ detail }), { status, headers: { "Content-Type": "application/json" } });

export async function proxyToApi(input: ProxyInput): Promise<Response> {
  if (!input.signedIn) return json(401, "Sign in to continue");
  const { path } = input;
  if (path.length === 0 || !(PROXIED_PREFIXES as readonly string[]).includes(path[0])) return json(404, "Not found");
  if (path.some((s) => s === "" || s === "." || s === ".." || /[/\\]/.test(s))) return json(400, "Bad path");
  if (!input.adminKey) return json(500, "The admin app has no ADMIN_API_KEY configured");

  const headers: Record<string, string> = { "X-Admin-Key": input.adminKey };
  if (input.contentType) headers["Content-Type"] = input.contentType;
  const hasBody = !["GET", "HEAD"].includes(input.method) && input.body !== null && input.body.byteLength > 0;

  let upstream: Response;
  try {
    upstream = await (input.fetchImpl ?? fetch)(`${input.apiUrl}/${path.map(encodeURIComponent).join("/")}${input.search}`, {
      method: input.method,
      headers,
      body: hasBody ? input.body : undefined,
      cache: "no-store",
      signal: AbortSignal.timeout(input.timeoutMs ?? 60_000),
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "TimeoutError") return json(504, "The API took too long to answer.");
    return json(502, `Can't reach the API at ${input.apiUrl}.`);
  }

  // Only what the page needs goes back: never the upstream's cookies or hop-by-hop headers.
  const out = new Headers();
  const type = upstream.headers.get("content-type");
  if (type) out.set("Content-Type", type);
  // An API 401 means the server's admin key is wrong, which is not the browser's fault or fixable by signing in again.
  if (upstream.status === 401) return json(502, "The API rejected this app's ADMIN_API_KEY. Check it matches the API's.");
  return new Response(upstream.status === 204 ? null : upstream.body, { status: upstream.status, headers: out });
}
