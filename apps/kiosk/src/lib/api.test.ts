import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, messageFromDetail } from "./api";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

afterEach(() => vi.restoreAllMocks());

describe("messageFromDetail", () => {
  it("uses a string detail as is", () => {
    expect(messageFromDetail("Capture not found.", "x")).toBe("Capture not found.");
  });
  it("joins the messages of a validation error", () => {
    expect(messageFromDetail([{ msg: "Field required" }, { msg: "Input should be True" }], "x")).toBe(
      "Field required. Input should be True",
    );
  });
  it("falls back when there is nothing useful", () => {
    expect(messageFromDetail(undefined, "Bad Request")).toBe("Bad Request");
    expect(messageFromDetail([], "Bad Request")).toBe("Bad Request");
    expect(messageFromDetail({}, "Bad Request")).toBe("Bad Request");
  });
});

describe("requests", () => {
  it("starts a session with consent", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ id: "s1", consent_given: true }, 201));
    await api.createSession();
    const [url, init] = fetch.mock.calls[0];
    expect(String(url)).toMatch(/\/sessions$/);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ consent_given: true });
    expect(new Headers(init?.headers).get("Content-Type")).toBe("application/json");
  });

  it("builds catalog queries from the filters, leaving defaults out", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({ items: [] }));
    await api.listCatalog({ page: 1, pageSize: 12 });
    await api.listCatalog({ categories: ["top", "dress"], onSale: true, search: "  silk ", page: 2, pageSize: 12 });
    await api.listCatalog({ onSale: false, search: "   " });
    await api.listCatalog({ minDiscountPct: 50, newWithinDays: 30 });

    const q = (i: number) => new URL(String(fetch.mock.calls[i][0])).searchParams;
    expect(Object.fromEntries(q(0))).toEqual({ page: "1", page_size: "12" });
    expect(q(1).getAll("category")).toEqual(["top", "dress"]); // repeated, as the API expects
    expect(Object.fromEntries(q(1))).toMatchObject({ page: "2", on_sale: "true", search: "silk" });
    expect([...q(2).keys()].sort()).toEqual(["page", "page_size"]);
    expect(Object.fromEntries(q(3))).toMatchObject({ min_discount_pct: "50", new_within_days: "30" });
  });

  it("asks for recommendations with the ids comma-separated", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ more_styles: [], complete_your_look: [] }));
    await api.recommend(["a", "b"]);
    expect(new URL(String(fetch.mock.calls[0][0])).searchParams.get("product_ids")).toBe("a,b");
  });

  it("tells the API which products came from a recommendation", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({ job_id: "j", status: "queued", channel: "c" }, 202));
    await api.createTryOn("s", "captures/s/x.webp", ["a", "b"], ["b"]);
    await api.createTryOn("s", "captures/s/x.webp", ["a"]);
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toMatchObject({ product_ids: ["a", "b"], recommended_product_ids: ["b"] });
    expect(JSON.parse(String(fetch.mock.calls[1][1]?.body)).recommended_product_ids).toEqual([]);
  });

  it("creates a share link, asks for an outfit, and sends the staff key only where it belongs", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockImplementation(async () => json({}));
    await api.createShare("s", "job-1");
    await api.requestOutfit({ sessionId: "s", productId: "p", size: "M", color: null });
    await api.listStaffRequests("staff-key");
    await api.updateStaffRequest("staff-key", "r1", "done");
    await api.getMobileLook("AB 12");
    const calls = fetch.mock.calls;
    expect(JSON.parse(String(calls[0][1]?.body))).toEqual({ session_id: "s", job_id: "job-1" });
    expect(JSON.parse(String(calls[1][1]?.body))).toEqual({ session_id: "s", product_id: "p", size: "M", color: null });
    expect(new Headers(calls[1][1]?.headers).has("X-Staff-Key")).toBe(false);
    expect(new Headers(calls[2][1]?.headers).get("X-Staff-Key")).toBe("staff-key");
    expect(String(calls[3][0])).toMatch(/\/requests\/r1$/);
    expect(String(calls[4][0])).toMatch(/\/m\/AB%2012$/); // the code is encoded, not trusted
  });

  it("uploads the photo as multipart without forcing a Content-Type", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ key: "captures/s/x.webp" }, 201));
    await api.uploadCapture("sess-1", new Blob(["jpeg"], { type: "image/jpeg" }));
    const [, init] = fetch.mock.calls[0];
    const form = init?.body as FormData;
    expect(form).toBeInstanceOf(FormData);
    expect(form.get("session_id")).toBe("sess-1");
    expect((form.get("file") as File).name).toBe("capture.jpg");
    expect(new Headers(init?.headers).has("Content-Type")).toBe(false); // the browser adds the boundary
  });

  it("starts a try-on with the key and the chosen products", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ job_id: "j1" }, 202));
    await api.createTryOn("s1", "captures/s1/a.webp", ["p1", "p2"]);
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({
      session_id: "s1",
      capture_key: "captures/s1/a.webp",
      product_ids: ["p1", "p2"],
      recommended_product_ids: [],
    });
  });

  it("adds to the cart one at a time, sending null for an unchosen option", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ items: [] }));
    await api.addToCart({ sessionId: "s1", productId: "p1", size: "M" });
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({
      session_id: "s1",
      product_id: "p1",
      size: "M",
      color: null,
      quantity: 1,
    });
  });
});

describe("errors", () => {
  it("turns an API error into its readable message", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: "Only 3 in stock (2 already in cart)" }, 409));
    await expect(api.addToCart({ sessionId: "s", productId: "p" })).rejects.toMatchObject({
      name: "ApiError",
      status: 409,
      message: "Only 3 in stock (2 already in cart)",
    });
  });

  it("reads FastAPI validation errors", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ detail: [{ msg: "Value error, consent_given must be true" }] }, 422));
    await expect(api.createSession()).rejects.toThrow("Value error, consent_given must be true");
  });

  it("copes with a non-JSON error body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("<html>bad gateway</html>", { status: 502, statusText: "Bad Gateway" }));
    await expect(api.getJob("j")).rejects.toMatchObject({ status: 502, message: "Bad Gateway" });
  });

  it("gives every request a timeout so a hung connection fails instead of waiting forever", async () => {
    const fetch = vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ items: [] }));
    await api.listCatalog();
    expect(fetch.mock.calls[0][1]?.signal).toBeInstanceOf(AbortSignal);
  });

  it("explains a timeout in plain words", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new DOMException("signal timed out", "TimeoutError"));
    const err = await api.getJob("j").catch((e) => e);
    expect(err).toMatchObject({ status: 0 });
    expect(err.message).toMatch(/took too long/i);
  });

  it("reports an unreachable server in plain words", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await api.getCart("s").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 0 });
    expect(err.message).toMatch(/can't reach/i);
  });
});
