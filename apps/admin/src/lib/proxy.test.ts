import { describe, expect, it, vi } from "vitest";
import { type ProxyInput, proxyToApi } from "./proxy";

const base = (over: Partial<ProxyInput> = {}): ProxyInput => ({
  signedIn: true,
  method: "GET",
  path: ["admin", "stats"],
  search: "",
  contentType: null,
  body: null,
  apiUrl: "http://api.test",
  adminKey: "server-secret",
  fetchImpl: vi.fn(async () => new Response(JSON.stringify({ ok: 1 }), { headers: { "Content-Type": "application/json" } })) as unknown as typeof fetch,
  ...over,
});

describe("proxyToApi", () => {
  it("refuses anyone who is not signed in, without calling the API", async () => {
    const input = base({ signedIn: false });
    const res = await proxyToApi(input);
    expect(res.status).toBe(401);
    expect(input.fetchImpl).not.toHaveBeenCalled();
  });

  it("forwards with the admin key from the server and the query string", async () => {
    const input = base({ path: ["catalog"], search: "?page=2&category=top" });
    const res = await proxyToApi(input);
    const [url, init] = (input.fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("http://api.test/catalog?page=2&category=top");
    expect((init as RequestInit).headers).toMatchObject({ "X-Admin-Key": "server-secret" });
    expect(res.status).toBe(200);
    expect(await res.json()).toEqual({ ok: 1 });
  });

  it("passes method, body and content type through (a CSV upload)", async () => {
    const body = new TextEncoder().encode("sku,name\nA,B\n").buffer as ArrayBuffer;
    const input = base({ method: "POST", path: ["products", "import"], search: "?dry_run=true", contentType: "text/csv", body });
    await proxyToApi(input);
    const [, init] = (input.fetchImpl as ReturnType<typeof vi.fn>).mock.calls[0];
    expect((init as RequestInit).method).toBe("POST");
    expect((init as RequestInit).headers).toMatchObject({ "Content-Type": "text/csv" });
    expect((init as RequestInit).body).toBe(body);
  });

  it("only reaches the admin API paths", async () => {
    for (const path of [["health"], ["ws"], ["capture"], ["cart", "add"], ["m", "ABC"], []]) {
      const input = base({ path });
      expect((await proxyToApi(input)).status).toBe(404);
      expect(input.fetchImpl).not.toHaveBeenCalled();
    }
  });

  it("refuses path tricks", async () => {
    for (const path of [["products", ".."], ["products", ""], ["products", "a/b"], ["products", "a\\b"], ["products", "."]]) {
      const input = base({ path });
      expect((await proxyToApi(input)).status).toBe(400);
      expect(input.fetchImpl).not.toHaveBeenCalled();
    }
  });

  it("does not send a request at all without a server key", async () => {
    const input = base({ adminKey: "" });
    expect((await proxyToApi(input)).status).toBe(500);
    expect(input.fetchImpl).not.toHaveBeenCalled();
  });

  it("passes the API's status and reason through", async () => {
    const input = base({ fetchImpl: vi.fn(async () => new Response(JSON.stringify({ detail: "That SKU is already used" }), { status: 409, headers: { "Content-Type": "application/json" } })) as unknown as typeof fetch });
    const res = await proxyToApi(input);
    expect(res.status).toBe(409);
    expect(await res.json()).toEqual({ detail: "That SKU is already used" });
  });

  it("turns an API 401 into a 502 about the server key, so the browser does not think it signed out", async () => {
    const input = base({ fetchImpl: vi.fn(async () => new Response("{}", { status: 401 })) as unknown as typeof fetch });
    const res = await proxyToApi(input);
    expect(res.status).toBe(502);
    expect((await res.json()).detail).toMatch(/ADMIN_API_KEY/);
  });

  it("answers 502 when the API is unreachable and 504 on a timeout, and 204 stays empty", async () => {
    expect((await proxyToApi(base({ fetchImpl: vi.fn(async () => { throw new TypeError("fetch failed"); }) as unknown as typeof fetch }))).status).toBe(502);
    expect((await proxyToApi(base({ fetchImpl: vi.fn(async () => { throw new DOMException("t", "TimeoutError"); }) as unknown as typeof fetch }))).status).toBe(504);
    const none = await proxyToApi(base({ method: "DELETE", path: ["products", "x"], fetchImpl: vi.fn(async () => new Response(null, { status: 204 })) as unknown as typeof fetch }));
    expect(none.status).toBe(204);
  });

  it("does not leak upstream cookies or other headers", async () => {
    const input = base({ fetchImpl: vi.fn(async () => new Response("{}", { headers: { "Set-Cookie": "a=b", "X-Secret": "1", "Content-Type": "application/json" } })) as unknown as typeof fetch });
    const res = await proxyToApi(input);
    expect(res.headers.get("set-cookie")).toBeNull();
    expect(res.headers.get("x-secret")).toBeNull();
    expect(res.headers.get("content-type")).toBe("application/json");
  });
});
