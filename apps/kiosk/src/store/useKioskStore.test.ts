import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { JobUpdate, Product } from "@/lib/types";

const mocks = vi.hoisted(() => ({
  api: {
    createSession: vi.fn(),
    listCatalog: vi.fn(),
    uploadCapture: vi.fn(),
    createTryOn: vi.fn(),
    getJob: vi.fn(),
    addToCart: vi.fn(),
    getCart: vi.fn(),
    removeFromCart: vi.fn(),
  },
  events: { track: vi.fn(), close: vi.fn() },
  createSessionEvents: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/api")>()), api: mocks.api }));
vi.mock("@/lib/sessionEvents", () => ({ createSessionEvents: mocks.createSessionEvents }));

import { ApiError } from "@/lib/api";
import { config } from "@/lib/config";
import { useKioskStore } from "./useKioskStore";

const store = () => useKioskStore.getState();

function product(id: string, over: Partial<Product> = {}): Product {
  return {
    id,
    name: `Product ${id}`,
    category: "top",
    price_pkr: 1000,
    sale_price_pkr: null,
    sizes: ["M"],
    colors: [],
    stock: 5,
    garment_image_url: `http://img/${id}.png`,
    garment_mask_url: null,
    created_at: "2026-01-01T00:00:00Z",
    on_sale: false,
    current_price_pkr: 1000,
    ...over,
  };
}

const page = (items: Product[], p = 1, pages = 1, total = items.length) => ({
  items,
  total,
  page: p,
  page_size: 12,
  pages,
});

let trackHandler: ((u: JobUpdate) => void) | undefined;
const emit = (u: Partial<JobUpdate> & Pick<JobUpdate, "status" | "pct">) => trackHandler?.({ job: "job-1", ...u });
const flush = () => vi.advanceTimersByTimeAsync(0);
const photo = new Blob(["jpeg"], { type: "image/jpeg" });

async function openSession() {
  await store().agree();
  await flush();
}

async function readyToTryOn(items = [product("a"), product("b")]) {
  mocks.api.listCatalog.mockResolvedValue(page(items));
  await openSession();
  store().registerCapture(() => Promise.resolve(photo));
  store().setCamera(true);
  items.slice(0, 1).forEach((p) => store().toggleProduct(p));
}

beforeEach(() => {
  vi.useFakeTimers();
  Object.values(mocks.api).forEach((f) => f.mockReset());
  mocks.events.track.mockReset();
  mocks.events.close.mockReset();
  mocks.createSessionEvents.mockReset();
  trackHandler = undefined;
  mocks.events.track.mockImplementation((_id: string, handler: (u: JobUpdate) => void) => {
    trackHandler = handler;
    return vi.fn();
  });
  mocks.createSessionEvents.mockReturnValue(mocks.events);
  mocks.api.createSession.mockResolvedValue({ id: "sess-1", started_at: "", consent_given: true });
  mocks.api.listCatalog.mockResolvedValue(page([]));
  mocks.api.uploadCapture.mockResolvedValue({ key: "captures/sess-1/x.webp" });
  mocks.api.createTryOn.mockResolvedValue({ job_id: "job-1", status: "queued", channel: "c" });
  store().reset();
});

afterEach(() => {
  store().reset();
  vi.useRealTimers();
});

describe("starting a session", () => {
  it("starts at the consent screen with nothing created and the camera off", () => {
    expect(store().phase).toBe("consent");
    expect(mocks.api.createSession).not.toHaveBeenCalled();
  });

  it("creates the session on agreement, opens the live connection and loads the catalog", async () => {
    mocks.api.listCatalog.mockResolvedValue(page([product("a")]));
    await openSession();

    expect(mocks.api.createSession).toHaveBeenCalledTimes(1);
    expect(store().phase).toBe("browsing");
    expect(store().session?.id).toBe("sess-1");
    expect(mocks.createSessionEvents).toHaveBeenCalledWith(
      expect.objectContaining({ sessionId: "sess-1", wsUrl: config.wsUrl, fetchJob: mocks.api.getJob }),
    );
    expect(store().products.map((p) => p.id)).toEqual(["a"]);
  });

  it("goes back to the consent screen with the reason if the session cannot start", async () => {
    mocks.api.createSession.mockRejectedValue(new ApiError(0, "Can't reach the mirror's server."));
    await store().agree();

    expect(store().phase).toBe("consent");
    expect(store().error).toBe("Can't reach the mirror's server.");
    expect(mocks.createSessionEvents).not.toHaveBeenCalled();
  });

  it("ignores a second tap while starting", async () => {
    const first = store().agree();
    await store().agree();
    await first;
    expect(mocks.api.createSession).toHaveBeenCalledTimes(1);
  });

  it("forgets everything when the shopper leaves, and closes the connection", async () => {
    await readyToTryOn();
    store().reset();

    expect(store().phase).toBe("consent");
    expect(store().session).toBeNull();
    expect(store().selected).toEqual([]);
    expect(mocks.events.close).toHaveBeenCalled();
  });

  it("does not come back to life if the shopper leaves while the session is starting", async () => {
    let resolve!: (s: unknown) => void;
    mocks.api.createSession.mockReturnValue(new Promise((r) => (resolve = r)));
    const starting = store().agree();
    store().reset();
    resolve({ id: "late", started_at: "", consent_given: true });
    await starting;

    expect(store().phase).toBe("consent");
    expect(mocks.createSessionEvents).not.toHaveBeenCalled();
  });
});

describe("the catalog", () => {
  beforeEach(openSession);

  it("asks for the first page again whenever a filter changes", async () => {
    mocks.api.listCatalog.mockClear();
    store().setFilters({ category: "dress" });
    await flush();
    store().setFilters({ onSale: true });
    await flush();
    store().setFilters({ search: "silk" });
    await flush();

    expect(mocks.api.listCatalog).toHaveBeenLastCalledWith({
      category: "dress",
      onSale: true,
      search: "silk",
      page: 1,
    });
    expect(mocks.api.listCatalog).toHaveBeenCalledTimes(3);
  });

  it("only the latest request may write results, however the responses are ordered", async () => {
    let slow!: (v: unknown) => void;
    mocks.api.listCatalog.mockReturnValueOnce(new Promise((r) => (slow = r)));
    mocks.api.listCatalog.mockResolvedValueOnce(page([product("new")]));

    store().setFilters({ search: "a" }); // slow
    store().setFilters({ search: "ab" }); // fast, and the one that counts
    await flush();
    slow(page([product("stale")]));
    await flush();

    expect(store().products.map((p) => p.id)).toEqual(["new"]);
    expect(store().catalogState).toBe("idle");
  });

  it("adds the next page to the list, without duplicates", async () => {
    mocks.api.listCatalog.mockResolvedValueOnce(page([product("1"), product("2")], 1, 2, 3));
    await store().loadCatalog(true);
    mocks.api.listCatalog.mockResolvedValueOnce(page([product("2"), product("3")], 2, 2, 3)); // overlap
    await store().loadCatalog(false);

    expect(store().products.map((p) => p.id)).toEqual(["1", "2", "3"]);
    expect(mocks.api.listCatalog).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 }));
  });

  it("stops asking once the last page is loaded", async () => {
    mocks.api.listCatalog.mockResolvedValueOnce(page([product("1")], 1, 1, 1));
    await store().loadCatalog(true);
    mocks.api.listCatalog.mockClear();
    await store().loadCatalog(false);
    expect(mocks.api.listCatalog).not.toHaveBeenCalled();
  });

  it("shows a readable error and can retry", async () => {
    mocks.api.listCatalog.mockRejectedValueOnce(new ApiError(502, "Bad Gateway"));
    await store().loadCatalog(true);
    expect(store().catalogState).toBe("error");
    expect(store().catalogError).toBe("Bad Gateway");

    mocks.api.listCatalog.mockResolvedValueOnce(page([product("1")]));
    await store().loadCatalog(true);
    expect(store().catalogState).toBe("idle");
    expect(store().catalogError).toBeNull();
  });
});

describe("choosing items", () => {
  beforeEach(openSession);

  it("adds and removes items, in the order chosen", () => {
    const [a, b, c] = [product("a"), product("b"), product("c")];
    store().toggleProduct(b);
    store().toggleProduct(a);
    store().toggleProduct(c);
    store().toggleProduct(a);
    expect(store().selected.map((p) => p.id)).toEqual(["b", "c"]);
    store().removeProduct("b");
    expect(store().selected.map((p) => p.id)).toEqual(["c"]);
  });

  it("allows at most 5 items", () => {
    for (let i = 0; i < 8; i++) store().toggleProduct(product(String(i)));
    expect(store().selected).toHaveLength(config.maxOutfitItems);
    expect(store().selected.map((p) => p.id)).toEqual(["0", "1", "2", "3", "4"]);
  });

  it("ignores sold-out products", () => {
    store().toggleProduct(product("gone", { stock: 0 }));
    expect(store().selected).toEqual([]);
  });

  it("keeps the outfit when the catalog is filtered", async () => {
    store().toggleProduct(product("a"));
    mocks.api.listCatalog.mockResolvedValue(page([product("z")]));
    store().setFilters({ category: "shoes" });
    await flush();
    expect(store().selected.map((p) => p.id)).toEqual(["a"]);
  });

  it("locks the outfit while a look is being made", async () => {
    await readyToTryOn();
    void store().startTryOn();
    await flush();
    expect(store().phase).toBe("countdown");

    store().toggleProduct(product("late"));
    store().removeProduct("a");
    expect(store().selected.map((p) => p.id)).toEqual(["a"]);
  });
});

describe("trying on", () => {
  it("needs an item and a working camera", async () => {
    mocks.api.listCatalog.mockResolvedValue(page([product("a")]));
    await openSession();
    store().registerCapture(() => Promise.resolve(photo));

    await store().startTryOn(); // nothing selected
    store().toggleProduct(product("a"));
    await store().startTryOn(); // camera not ready
    expect(store().phase).toBe("browsing");
    expect(mocks.api.uploadCapture).not.toHaveBeenCalled();
  });

  it("counts down, takes the photo, uploads it, starts the job and follows it to the result", async () => {
    await readyToTryOn([product("a"), product("b")]);
    store().toggleProduct(product("b"));
    const capture = vi.fn(() => Promise.resolve(photo));
    store().registerCapture(capture);

    void store().startTryOn();
    await flush();
    expect(store().phase).toBe("countdown");
    const shown: number[] = [];
    for (let i = 0; i < config.countdownSeconds; i++) {
      shown.push(store().countdown);
      await vi.advanceTimersByTimeAsync(1000);
    }
    expect(shown).toEqual([3, 2, 1]);

    expect(capture).toHaveBeenCalledTimes(1);
    expect(mocks.api.uploadCapture).toHaveBeenCalledWith("sess-1", photo);
    expect(mocks.api.createTryOn).toHaveBeenCalledWith("sess-1", "captures/sess-1/x.webp", ["a", "b"]);
    expect(store().phase).toBe("working");
    expect(mocks.events.track).toHaveBeenCalledWith("job-1", expect.any(Function));

    emit({ status: "processing", pct: 40 });
    expect(store().job).toMatchObject({ status: "processing", pct: 40 });
    expect(store().phase).toBe("working");

    emit({ status: "done", pct: 100, url: "https://img/result.webp" });
    expect(store().phase).toBe("result");
    expect(store().resultUrl).toBe("https://img/result.webp");
    expect(store().selected.map((p) => p.id)).toEqual(["a", "b"]); // the outfit shown is the outfit tried
  });

  it("shows the job's own readable message when it fails", async () => {
    await readyToTryOn();
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);

    emit({ status: "failed", pct: 30, error: "We couldn't see your full body clearly." });

    expect(store().phase).toBe("error");
    expect(store().error).toBe("We couldn't see your full body clearly.");
    expect(store().resultUrl).toBeNull();
  });

  it("treats a 'done' with no image as a failure rather than a blank result", async () => {
    await readyToTryOn();
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);
    emit({ status: "done", pct: 100 });
    expect(store().phase).toBe("error");
  });

  it("reports why the photo was refused, if the API refuses it", async () => {
    mocks.api.uploadCapture.mockRejectedValue(new ApiError(422, "Image is too small: 500px tall, at least 768px required."));
    await readyToTryOn();
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);

    expect(store().phase).toBe("error");
    expect(store().error).toMatch(/too small/);
    expect(mocks.api.createTryOn).not.toHaveBeenCalled();
  });

  it("reports a camera that fails at the moment of capture", async () => {
    await readyToTryOn();
    store().registerCapture(() => Promise.reject(new Error("The camera isn't ready yet.")));
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);
    expect(store().error).toBe("The camera isn't ready yet.");
  });

  it("explains an expired photo or a busy service from the API's own words", async () => {
    mocks.api.createTryOn.mockRejectedValue(new ApiError(503, "The try-on service is busy. Please try again in a moment."));
    await readyToTryOn();
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);
    expect(store().error).toBe("The try-on service is busy. Please try again in a moment.");
  });

  it("gives up with a message if no answer ever arrives", async () => {
    await readyToTryOn();
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);
    expect(store().phase).toBe("working");

    await vi.advanceTimersByTimeAsync(config.jobTimeoutMs);

    expect(store().phase).toBe("error");
    expect(store().error).toMatch(/longer than expected/);
  });

  it("lets the shopper try again and keeps the outfit", async () => {
    await readyToTryOn();
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);
    emit({ status: "failed", pct: 10, error: "No." });

    store().backToBrowsing();

    expect(store().phase).toBe("browsing");
    expect(store().error).toBeNull();
    expect(store().selected.map((p) => p.id)).toEqual(["a"]);
  });

  it("can go straight on to another look from the result", async () => {
    await readyToTryOn();
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);
    emit({ status: "done", pct: 100, url: "https://img/r.webp" });

    store().backToBrowsing();

    expect(store().phase).toBe("browsing");
    expect(store().resultUrl).toBeNull();
    expect(store().job).toBeNull();
  });
});

describe("stopping part-way", () => {
  it("cancelling the countdown takes no photo and calls nothing", async () => {
    await readyToTryOn();
    const capture = vi.fn(() => Promise.resolve(photo));
    store().registerCapture(capture);
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(1500);
    expect(store().phase).toBe("countdown");

    store().cancelCountdown();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(store().phase).toBe("browsing");
    expect(capture).not.toHaveBeenCalled();
    expect(mocks.api.uploadCapture).not.toHaveBeenCalled();
  });

  it("leaving during the countdown never takes a photo", async () => {
    await readyToTryOn();
    const capture = vi.fn(() => Promise.resolve(photo));
    store().registerCapture(capture);
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(1000);

    store().reset();
    await vi.advanceTimersByTimeAsync(10_000);

    expect(capture).not.toHaveBeenCalled();
    expect(store().phase).toBe("consent");
  });

  it("leaving during the upload does not start a job or revive the screen", async () => {
    let finish!: (v: unknown) => void;
    mocks.api.uploadCapture.mockReturnValue(new Promise((r) => (finish = r)));
    await readyToTryOn();
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);
    expect(store().phase).toBe("uploading");

    store().reset();
    finish({ key: "k" });
    await flush();

    expect(mocks.api.createTryOn).not.toHaveBeenCalled();
    expect(store().phase).toBe("consent");
  });

  it("an error from a call the shopper already walked away from is not shown", async () => {
    let boom!: (e: unknown) => void;
    mocks.api.createTryOn.mockReturnValue(new Promise((_, rej) => (boom = rej)));
    await readyToTryOn();
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);

    store().reset();
    boom(new ApiError(500, "server exploded"));
    await flush();

    expect(store().phase).toBe("consent");
    expect(store().error).toBeNull();
  });

  it("stops following the job and its timeout when leaving", async () => {
    const untrack = vi.fn();
    mocks.events.track.mockReturnValue(untrack);
    await readyToTryOn();
    void store().startTryOn();
    await vi.advanceTimersByTimeAsync(3000);

    store().reset();

    expect(untrack).toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(config.jobTimeoutMs * 2);
    expect(store().phase).toBe("consent"); // the timeout did not fire into the next shopper's session
  });
});

describe("the cart", () => {
  beforeEach(openSession);

  it("adds an item with the chosen options and keeps the returned cart", async () => {
    const cart = { session_id: "sess-1", cart_id: "c1", items: [], item_count: 1, subtotal_pkr: 1000 };
    mocks.api.addToCart.mockResolvedValue(cart);

    const result = await store().addToCart(product("a"), "M", "Ivory");

    expect(result).toEqual({ ok: true });
    expect(mocks.api.addToCart).toHaveBeenCalledWith({ sessionId: "sess-1", productId: "a", size: "M", color: "Ivory" });
    expect(store().cart).toEqual(cart);
  });

  it("returns the API's reason and leaves the cart alone when it is refused", async () => {
    mocks.api.addToCart.mockRejectedValue(new ApiError(409, "Only 1 in stock (1 already in cart)"));
    const result = await store().addToCart(product("a"), "M", null);
    expect(result).toEqual({ ok: false, message: "Only 1 in stock (1 already in cart)" });
    expect(store().cart).toBeNull();
  });

  it("refreshes the cart when it is opened, and survives that failing", async () => {
    const cart = { session_id: "sess-1", cart_id: null, items: [], item_count: 0, subtotal_pkr: 0 };
    mocks.api.getCart.mockResolvedValueOnce(cart);
    store().openCart();
    await flush();
    expect(store().cartOpen).toBe(true);
    expect(store().cart).toEqual(cart);

    mocks.api.getCart.mockRejectedValueOnce(new ApiError(0, "offline"));
    store().openCart();
    await flush();
    expect(store().cart).toEqual(cart);
  });
});

describe("removing from the cart", () => {
  const line = { id: "line-1", product: {}, size: "M", color: null, quantity: 2, unit_price_pkr: 500, line_total_pkr: 1000 };
  const full = { session_id: "sess-1", cart_id: "c1", items: [line], item_count: 2, subtotal_pkr: 1000 };
  const empty = { session_id: "sess-1", cart_id: "c1", items: [], item_count: 0, subtotal_pkr: 0 };
  beforeEach(openSession);

  it("removes the line and keeps the cart the API returns", async () => {
    useKioskStore.setState({ cart: full as never });
    mocks.api.removeFromCart.mockResolvedValue(empty);

    const result = await store().removeFromCart("line-1");

    expect(result).toEqual({ ok: true });
    expect(mocks.api.removeFromCart).toHaveBeenCalledWith("sess-1", "line-1");
    expect(store().cart).toEqual(empty);
  });

  it("shows the real cart when the line was already gone", async () => {
    useKioskStore.setState({ cart: full as never });
    mocks.api.removeFromCart.mockRejectedValue(new ApiError(404, "That item is not in the cart"));
    mocks.api.getCart.mockResolvedValue(empty);

    const result = await store().removeFromCart("line-1");

    expect(result).toEqual({ ok: true });
    expect(store().cart).toEqual(empty);
  });

  it("reports a failure and keeps the cart on screen", async () => {
    useKioskStore.setState({ cart: full as never });
    mocks.api.removeFromCart.mockRejectedValue(new ApiError(0, "Can't reach the mirror's server."));

    const result = await store().removeFromCart("line-1");

    expect(result).toEqual({ ok: false, message: "Can't reach the mirror's server." });
    expect(store().cart).toEqual(full);
  });

  it("keeps the original message when a 404 cannot be refreshed either", async () => {
    mocks.api.removeFromCart.mockRejectedValue(new ApiError(404, "That item is not in the cart"));
    mocks.api.getCart.mockRejectedValue(new ApiError(0, "offline"));
    expect(await store().removeFromCart("line-1")).toEqual({ ok: false, message: "That item is not in the cart" });
  });

  it("does nothing without a session", async () => {
    store().reset();
    const result = await store().removeFromCart("line-1");
    expect(result.ok).toBe(false);
    expect(mocks.api.removeFromCart).not.toHaveBeenCalled();
  });

  it("never shows the previous shopper's cart to the next one", async () => {
    let finish!: (c: unknown) => void;
    mocks.api.removeFromCart.mockReturnValue(new Promise((r) => (finish = r)));
    const pending = store().removeFromCart("line-1");
    await flush();

    store().reset(); // the idle timeout fired while the request was in flight
    finish(empty);
    await pending;

    expect(store().cart).toBeNull();
  });

  it("applies cart changes in the order they were made, even if answers arrive late", async () => {
    const answers: Array<(c: unknown) => void> = [];
    mocks.api.getCart.mockImplementation(() => new Promise((r) => answers.push(r)));
    mocks.api.removeFromCart.mockResolvedValue(empty);

    store().openCart(); // refresh starts first...
    const removal = store().removeFromCart("line-1"); // ...the removal is made after it
    await flush();
    expect(mocks.api.removeFromCart).not.toHaveBeenCalled(); // waits for the refresh to finish

    answers[0](full);
    await removal;

    expect(mocks.api.removeFromCart).toHaveBeenCalledTimes(1);
    expect(store().cart).toEqual(empty); // the removal is the last word, not the older refresh
  });

  it("does not let an add that finishes after the shopper left write into the next session", async () => {
    let finish!: (c: unknown) => void;
    mocks.api.addToCart.mockReturnValue(new Promise((r) => (finish = r)));
    const pending = store().addToCart(product("a"), "M", null);
    await flush();

    store().reset();
    finish(full);
    await pending;

    expect(store().cart).toBeNull();
  });
});
