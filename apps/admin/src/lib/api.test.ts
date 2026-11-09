import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, messageFromDetail } from "./api";
import { config } from "./config";
import type { ProductInput } from "./types";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.restoreAllMocks());

describe("messageFromDetail", () => {
  it("uses a string detail as is", () => {
    expect(messageFromDetail("Product is in a cart and cannot be deleted", "x")).toBe("Product is in a cart and cannot be deleted");
  });
  it("names the field in a validation error and drops pydantic's prefix", () => {
    expect(
      messageFromDetail(
        [
          { loc: ["body", "colors", 0, "hex"], msg: "String should match pattern '^#[0-9a-fA-F]{6}$'" },
          { loc: ["body"], msg: "Value error, sale_price_pkr cannot exceed price_pkr" },
        ],
        "x",
      ),
    ).toBe("colors.hex: String should match pattern '^#[0-9a-fA-F]{6}$'. sale_price_pkr cannot exceed price_pkr");
  });
  it("falls back when there is nothing useful", () => {
    expect(messageFromDetail(undefined, "Bad Request")).toBe("Bad Request");
    expect(messageFromDetail([], "Bad Request")).toBe("Bad Request");
  });
});

describe("requests", () => {
  it("sends the admin key on every request", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({}));
    await api.stats();
    expect(new Headers(fetch.mock.calls[0][1]?.headers).get("X-Admin-Key")).toBe(config.adminKey);
  });

  it("lists products from the catalog, leaving defaults out", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({ items: [] }));
    await api.listProducts({ category: "all", page: 1, pageSize: 20 });
    await api.listProducts({ category: "shoes", search: " heel ", onSale: true, page: 3, pageSize: 20 });
    const q = (i: number) => Object.fromEntries(new URL(String(fetch.mock.calls[i][0])).searchParams);
    expect(new URL(String(fetch.mock.calls[0][0])).pathname).toBe("/catalog");
    expect(q(0)).toEqual({ page: "1", page_size: "20" });
    expect(q(1)).toEqual({ page: "3", page_size: "20", category: "shoes", on_sale: "true", search: "heel" });
  });

  it("creates a product with a JSON body", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ id: "p1" }, 201));
    const input: ProductInput = { name: "A", category: "top", price_pkr: 1, sale_price_pkr: null, sizes: [], colors: [], stock: 0, garment_image_url: "u", garment_mask_url: null };
    await api.createProduct({ ...input });
    const [url, init] = fetch.mock.calls[0];
    expect(String(url)).toMatch(/\/products$/);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual(input);
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  });

  it("patches only the fields it is given, including an explicit null", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({}));
    await api.updateProduct("p1", { sale_price_pkr: null, stock: 4 });
    const [url, init] = fetch.mock.calls[0];
    expect(String(url)).toMatch(/\/products\/p1$/);
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(String(init?.body))).toEqual({ sale_price_pkr: null, stock: 4 });
  });

  it("handles a 204 from delete", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(null, { status: 204 }));
    await expect(api.deleteProduct("p1")).resolves.toBeUndefined();
  });

  it("collects every page of products", async () => {
    const page = (n: number, pages: number, items: string[]) => json({ items: items.map((id) => ({ id })), page: n, pages, total: 3, page_size: 100 });
    const fetch = vi.spyOn(globalThis, "fetch");
    fetch.mockResolvedValueOnce(page(1, 2, ["a", "b"]));
    fetch.mockResolvedValueOnce(page(2, 2, ["c"]));
    const all = await api.listAllProducts();
    expect(all.map((p) => p.id)).toEqual(["a", "b", "c"]);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it("reads sessions and jobs with a limit", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json([]));
    await api.listSessions(50);
    await api.listJobs();
    expect(String(fetch.mock.calls[0][0])).toMatch(/\/sessions\?limit=50$/);
    expect(String(fetch.mock.calls[1][0])).toMatch(new RegExp(`/tryon\\?limit=${config.listLimit}$`));
  });
});

describe("errors", () => {
  it("explains a rejected admin key and how to fix it", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: "Invalid admin key" }, 401));
    const err = await api.stats().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(err.message).toMatch(/NEXT_PUBLIC_ADMIN_API_KEY/);
  });

  it("passes the API's own reason through", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: "Product is in a cart and cannot be deleted" }, 409));
    await expect(api.deleteProduct("p")).rejects.toMatchObject({ status: 409, message: "Product is in a cart and cannot be deleted" });
  });

  it("copes with a non-JSON error body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html/>", { status: 502, statusText: "Bad Gateway" }));
    await expect(api.stats()).rejects.toMatchObject({ status: 502, message: "Bad Gateway" });
  });

  it("says where it could not connect", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await api.stats().catch((e) => e);
    expect(err.status).toBe(0);
    expect(err.message).toContain(config.apiUrl);
  });

  it("explains a timeout", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new DOMException("timed out", "TimeoutError"));
    await expect(api.stats()).rejects.toThrow(/too long/);
  });

  it("gives every request a timeout", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({}));
    await api.stats();
    expect(fetch.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
  });
});

describe("uploadImage", () => {
  const file = new File(["png-bytes"], "shirt.png", { type: "image/png" });
  const presign = { key: "garment/2026/01/01/x.png", upload_url: "http://storage.test/put?sig=1", public_url: "http://storage.test/bucket/garment/x.png", expires_in: 600 };

  it("asks for a presigned URL, PUTs the file there, and returns the public URL", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    fetch.mockResolvedValueOnce(json(presign));
    fetch.mockResolvedValueOnce(new Response(null, { status: 200 }));

    const url = await api.uploadImage(file);

    expect(url).toBe(presign.public_url);
    const [presignUrl, presignInit] = fetch.mock.calls[0];
    expect(String(presignUrl)).toMatch(/\/uploads\/presign$/);
    expect(JSON.parse(String(presignInit?.body))).toEqual({ content_type: "image/png", kind: "garment" });
    const [putUrl, putInit] = fetch.mock.calls[1];
    expect(String(putUrl)).toBe(presign.upload_url);
    expect(putInit?.method).toBe("PUT");
    expect(putInit?.body).toBe(file);
    expect(new Headers(putInit?.headers).get("Content-Type")).toBe("image/png");
    expect(new Headers(putInit?.headers).has("X-Admin-Key")).toBe(false); // the key must not go to storage
  });

  it("suggests a CORS rule when the browser blocks the upload", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    fetch.mockResolvedValueOnce(json(presign));
    fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(api.uploadImage(file)).rejects.toThrow(/CORS/);
  });

  it("reports a refusal from storage", async () => {
    const fetch = vi.spyOn(globalThis, "fetch");
    fetch.mockResolvedValueOnce(json(presign));
    fetch.mockResolvedValueOnce(new Response("denied", { status: 403 }));
    await expect(api.uploadImage(file)).rejects.toMatchObject({ status: 403, message: expect.stringContaining("403") });
  });

  it("does not try to upload if the API refuses to presign", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: [{ loc: ["body", "content_type"], msg: "Input should be 'image/jpeg'" }] }, 422));
    await expect(api.uploadImage(file)).rejects.toThrow(/content_type/);
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
