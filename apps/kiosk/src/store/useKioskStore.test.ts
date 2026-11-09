import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { JobUpdate, Product } from "@/lib/types";

const mocks = vi.hoisted(() => ({
  api: {
    createSession: vi.fn(),
    uploadCapture: vi.fn(),
    createTryOn: vi.fn(),
    getJob: vi.fn(),
    addToCart: vi.fn(),
    getCart: vi.fn(),
    removeFromCart: vi.fn(),
    setCartQuantity: vi.fn(),
    checkout: vi.fn(),
    createShare: vi.fn(),
    requestOutfit: vi.fn(),
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

let trackHandler: ((u: JobUpdate) => void) | undefined;
const emit = (u: Partial<JobUpdate> & Pick<JobUpdate, "status" | "pct">) => trackHandler?.({ job: "job-1", ...u });
const flush = () => vi.advanceTimersByTimeAsync(0);
const photo = new Blob(["jpeg"], { type: "image/jpeg" });

async function openSession() {
  await store().agree();
  await flush();
}

/** A session with one item chosen, ready for the capture screen. */
async function readyToCapture(items = [product("a")]) {
  await openSession();
  items.forEach((p) => store().select(p, { size: "M" }));
  store().startCapture();
}

/** Through the countdown to a result. */
async function toResult() {
  await readyToCapture();
  store().beginCountdown();
  await store().submitCapture(photo);
  await flush();
  emit({ status: "done", pct: 100, url: "http://img/look1.webp" });
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: vi.fn(() => "blob:photo"), revokeObjectURL: vi.fn() }));
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
  mocks.api.uploadCapture.mockResolvedValue({ key: "captures/sess-1/x.webp" });
  mocks.api.createTryOn.mockResolvedValue({ job_id: "job-1", status: "queued", channel: "c" });
  store().reset();
});

afterEach(() => {
  store().reset();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("starting a session", () => {
  it("starts at the consent screen with nothing created and the camera off", () => {
    expect(store().phase).toBe("consent");
    expect(store().view).toBe("shop");
    expect(mocks.api.createSession).not.toHaveBeenCalled();
  });

  it("creates the session on agreement and opens the live connection", async () => {
    await openSession();

    expect(mocks.api.createSession).toHaveBeenCalledTimes(1);
    expect(store().phase).toBe("browsing");
    expect(store().session?.id).toBe("sess-1");
    expect(mocks.createSessionEvents).toHaveBeenCalledWith(expect.objectContaining({ sessionId: "sess-1" }));
  });

  it("goes back to the consent screen with the reason if the session cannot start", async () => {
    mocks.api.createSession.mockRejectedValue(new ApiError(0, "Can't reach the mirror's server."));
    await openSession();
    expect(store().phase).toBe("consent");
    expect(store().error).toBe("Can't reach the mirror's server.");
    expect(store().session).toBeNull();
  });

  it("ignores a second tap while starting", async () => {
    const first = store().agree();
    void store().agree();
    await first;
    expect(mocks.api.createSession).toHaveBeenCalledTimes(1);
  });

  it("forgets everything when the shopper leaves, and closes the connection", async () => {
    await readyToCapture();
    store().reset();
    expect(store().phase).toBe("consent");
    expect(store().session).toBeNull();
    expect(store().selected).toEqual([]);
    expect(store().looks).toEqual([]);
    expect(mocks.events.close).toHaveBeenCalled();
  });

  it("does not come back to life if the shopper leaves while the session is starting", async () => {
    let finish!: (s: unknown) => void;
    mocks.api.createSession.mockReturnValue(new Promise((r) => (finish = r)));
    const starting = store().agree();
    store().reset();
    finish({ id: "late", started_at: "", consent_given: true });
    await starting;
    expect(store().phase).toBe("consent");
    expect(store().session).toBeNull();
  });
});

describe("the shop", () => {
  beforeEach(openSession);

  it("remembers the tab, the product detail and which view the sidebar shows", () => {
    store().setTab("shoes");
    store().openDetail(product("a"));
    expect(store().tab).toBe("shoes");
    expect(store().detail?.id).toBe("a");
    store().setView("help");
    expect(store().view).toBe("help");
    expect(store().detail).toBeNull(); // changing view closes the detail panel
    store().setView("shop");
  });

  it("only switches views while browsing", async () => {
    store().select(product("a"), { size: "M" });
    store().startCapture();
    store().setView("settings");
    expect(store().view).toBe("shop");
  });
});

describe("choosing items", () => {
  beforeEach(openSession);

  it("adds items with their size and colour, in the order chosen", () => {
    const [a, b] = [product("a"), product("b")];
    expect(store().select(a, { size: "M", color: "Ivory" })).toEqual({ ok: true });
    store().select(b);
    expect(store().selected.map((i) => [i.product.id, i.size, i.color])).toEqual([
      ["a", "M", "Ivory"],
      ["b", null, null],
    ]);
    store().deselect("a");
    expect(store().selected.map((i) => i.product.id)).toEqual(["b"]);
  });

  it("choosing an item again updates its options instead of adding it twice", () => {
    const a = product("a", { sizes: ["S", "M"] });
    store().select(a, { size: "S" });
    store().select(a, { size: "M", color: "Ivory" });
    expect(store().selected).toHaveLength(1);
    expect(store().selected[0]).toMatchObject({ size: "M", color: "Ivory" });
    store().setSelectionOptions("a", { size: "S" });
    expect(store().selected[0]).toMatchObject({ size: "S", color: "Ivory" }); // only the size changed
  });

  it("allows at most 5 items and says why", () => {
    for (const id of "abcde") expect(store().select(product(id))).toEqual({ ok: true });
    const sixth = store().select(product("f"));
    expect(sixth).toEqual({ ok: false, message: "You can try on up to 5 items at once." });
    expect(store().selected).toHaveLength(5);
    expect(store().select(product("a"), { size: "L" })).toEqual({ ok: true }); // changing one already chosen is fine
  });

  it("refuses sold-out products", () => {
    expect(store().select(product("a", { stock: 0 }))).toEqual({ ok: false, message: "That item is sold out." });
    expect(store().selected).toEqual([]);
  });

  it("remembers which items came from a recommendation", () => {
    store().select(product("a"));
    store().select(product("b"), { fromRecommendation: true });
    expect(store().selected.map((i) => i.fromRecommendation)).toEqual([false, true]);
  });

  it("locks the outfit while a look is being made", async () => {
    store().select(product("a"), { size: "M" });
    store().startCapture();
    expect(store().select(product("b"))).toMatchObject({ ok: false });
    store().deselect("a");
    expect(store().selected).toHaveLength(1);
  });

  it("the outfit survives changing tab", () => {
    store().select(product("a"));
    store().setTab("bags");
    store().setTab("clothing");
    expect(store().selected).toHaveLength(1);
  });
});

describe("the capture flow", () => {
  it("needs a session and at least one item before the camera opens", async () => {
    await openSession();
    store().startCapture();
    expect(store().phase).toBe("browsing"); // nothing chosen
    store().select(product("a"));
    store().startCapture();
    expect(store().phase).toBe("capturing");
  });

  it("goes from guidance to a countdown and can be cancelled back to guidance", async () => {
    await readyToCapture();
    store().beginCountdown();
    expect(store().phase).toBe("countdown");
    expect(store().countdown).toBe(config.countdownSeconds);
    store().setCountdown(2);
    expect(store().countdown).toBe(2);
    store().cancelCountdown();
    expect(store().phase).toBe("capturing");
    expect(store().countdown).toBe(0);
  });

  it("leaving the camera screen goes back to the shop with the outfit kept", async () => {
    await readyToCapture();
    store().cancelCapture();
    expect(store().phase).toBe("browsing");
    expect(store().selected).toHaveLength(1);
  });

  it("remembers a camera problem for the screen to explain", async () => {
    await readyToCapture();
    store().setCameraError("Camera permission was denied.");
    expect(store().cameraError).toBe("Camera permission was denied.");
  });
});

describe("trying on", () => {
  it("uploads the photo, starts the job with the chosen products and follows it to the result", async () => {
    await readyToCapture([product("a"), product("b")]);
    store().beginCountdown();

    await store().submitCapture(photo);
    await flush();

    expect(mocks.api.uploadCapture).toHaveBeenCalledWith("sess-1", photo);
    expect(mocks.api.createTryOn).toHaveBeenCalledWith("sess-1", "captures/sess-1/x.webp", ["a", "b"], []);
    expect(store().phase).toBe("working");
    expect(store().photoUrl).toBe("blob:photo"); // for the blurred backdrop
    expect(store().captureKey).toBe("captures/sess-1/x.webp");

    emit({ status: "processing", pct: 40 });
    expect(store().job?.pct).toBe(40);
    emit({ status: "done", pct: 100, url: "http://img/look1.webp" });

    expect(store().phase).toBe("result");
    expect(store().looks).toHaveLength(1);
    expect(store().looks[0]).toMatchObject({ jobId: "job-1", url: "http://img/look1.webp" });
    expect(store().looks[0].items.map((i) => i.product.id)).toEqual(["a", "b"]);
    expect(store().lookIndex).toBe(0);
  });

  it("tells the API which products came from recommendations", async () => {
    await openSession();
    store().select(product("a"));
    store().select(product("b"), { fromRecommendation: true });
    store().startCapture();
    await store().submitCapture(photo);
    expect(mocks.api.createTryOn).toHaveBeenCalledWith("sess-1", expect.any(String), ["a", "b"], ["b"]);
  });

  it("shows the job's own readable message when it fails", async () => {
    await readyToCapture();
    await store().submitCapture(photo);
    await flush();
    emit({ status: "failed", pct: 40, error: "We couldn't see you clearly in the photo." });
    expect(store().phase).toBe("error");
    expect(store().error).toBe("We couldn't see you clearly in the photo.");
  });

  it("treats a 'done' with no image as a failure rather than a blank result", async () => {
    await readyToCapture();
    await store().submitCapture(photo);
    await flush();
    emit({ status: "done", pct: 100, url: null });
    expect(store().phase).toBe("error");
  });

  it("reports why the photo was refused, if the API refuses it", async () => {
    mocks.api.uploadCapture.mockRejectedValue(new ApiError(422, "The photo must be at least 768px tall."));
    await readyToCapture();
    await store().submitCapture(photo);
    expect(store().phase).toBe("error");
    expect(store().error).toBe("The photo must be at least 768px tall.");
    expect(mocks.api.createTryOn).not.toHaveBeenCalled();
  });

  it("offers Try again after 60 seconds but keeps following the job, and a late result still shows", async () => {
    await readyToCapture();
    await store().submitCapture(photo);
    await flush();

    expect(store().timedOut).toBe(false);
    await vi.advanceTimersByTimeAsync(config.tryOnSlowMs - 1);
    expect(store().timedOut).toBe(false);
    await vi.advanceTimersByTimeAsync(2);
    expect(store().timedOut).toBe(true);
    expect(store().phase).toBe("working"); // not failed: it may still finish

    emit({ status: "done", pct: 100, url: "http://img/late.webp" });
    expect(store().phase).toBe("result");
    expect(store().timedOut).toBe(false);
  });

  it("gives up with a message if no answer ever arrives", async () => {
    await readyToCapture();
    await store().submitCapture(photo);
    await flush();
    await vi.advanceTimersByTimeAsync(config.jobTimeoutMs + 1);
    expect(store().phase).toBe("error");
    expect(store().error).toMatch(/taking longer/i);
  });

  it("Try again makes a new job from the same photo and the same outfit", async () => {
    await readyToCapture([product("a"), product("b")]);
    await store().submitCapture(photo);
    await flush();
    await vi.advanceTimersByTimeAsync(config.tryOnSlowMs + 1);
    mocks.api.createTryOn.mockResolvedValue({ job_id: "job-2", status: "queued", channel: "c" });

    await store().retryTryOn();
    await flush();

    expect(mocks.api.uploadCapture).toHaveBeenCalledTimes(1); // no second upload
    expect(mocks.api.createTryOn).toHaveBeenLastCalledWith("sess-1", "captures/sess-1/x.webp", ["a", "b"], []);
    expect(store().timedOut).toBe(false);
    expect(store().phase).toBe("working");
  });

  it("Try again after the photo has expired goes back to the camera", async () => {
    await readyToCapture();
    await store().submitCapture(photo);
    await flush();
    mocks.api.createTryOn.mockRejectedValue(new ApiError(404, "Capture not found. Photos expire after an hour."));
    await store().retryTryOn();
    expect(store().phase).toBe("capturing");
    expect(store().captureKey).toBeNull();
  });

  it("Try again after an error with no photo goes back to the camera", async () => {
    await readyToCapture();
    mocks.api.uploadCapture.mockRejectedValue(new ApiError(0, "offline"));
    await store().submitCapture(photo);
    expect(store().phase).toBe("error");
    await store().retryTryOn();
    expect(store().phase).toBe("capturing");
  });
});

describe("looks", () => {
  it("a second try-on from the result adds Look 2 using the photo already taken", async () => {
    await toResult();
    mocks.api.createTryOn.mockResolvedValue({ job_id: "job-2", status: "queued", channel: "c" });

    const result = await store().tryOnWith(product("b"), { fromRecommendation: true });
    await flush();
    expect(result).toEqual({ ok: true });
    expect(mocks.api.uploadCapture).toHaveBeenCalledTimes(1);
    expect(mocks.api.createTryOn).toHaveBeenLastCalledWith("sess-1", "captures/sess-1/x.webp", ["a", "b"], ["b"]);
    expect(store().phase).toBe("working");

    trackHandler?.({ job: "job-2", status: "done", pct: 100, url: "http://img/look2.webp" });
    expect(store().looks.map((l) => l.url)).toEqual(["http://img/look1.webp", "http://img/look2.webp"]);
    expect(store().lookIndex).toBe(1);
    expect(store().looks[1].items.map((i) => i.product.id)).toEqual(["a", "b"]);
    expect(store().looks[0].items.map((i) => i.product.id)).toEqual(["a"]); // Look 1 keeps its own outfit
  });

  it("switches between looks and ignores an index that does not exist", async () => {
    await toResult();
    mocks.api.createTryOn.mockResolvedValue({ job_id: "job-2", status: "queued", channel: "c" });
    await store().tryOnWith(product("b"));
    await flush();
    trackHandler?.({ job: "job-2", status: "done", pct: 100, url: "http://img/look2.webp" });

    store().showLook(0);
    expect(store().lookIndex).toBe(0);
    store().showLook(5);
    store().showLook(-1);
    expect(store().lookIndex).toBe(0);
  });

  it("keeps only the latest four looks", async () => {
    await toResult();
    for (let n = 2; n <= 6; n++) {
      mocks.api.createTryOn.mockResolvedValue({ job_id: `job-${n}`, status: "queued", channel: "c" });
      store().deselect(`x${n - 1}`);
      await store().tryOnWith(product(`x${n}`));
      await flush();
      trackHandler?.({ job: `job-${n}`, status: "done", pct: 100, url: `http://img/look${n}.webp` });
      store().deselect(`x${n}`);
    }
    expect(store().looks).toHaveLength(4);
    expect(store().looks.at(-1)?.url).toBe("http://img/look6.webp");
  });

  it("only works from the result screen and when the item can be added", async () => {
    await openSession();
    expect(await store().tryOnWith(product("b"))).toMatchObject({ ok: false });
    await toResult();
    expect(await store().tryOnWith(product("z", { stock: 0 }))).toEqual({ ok: false, message: "That item is sold out." });
    expect(mocks.api.createTryOn).toHaveBeenCalledTimes(1);
  });

  it("explains an expired photo and stays on the result", async () => {
    await toResult();
    mocks.api.createTryOn.mockRejectedValue(new ApiError(404, "Capture not found."));
    const result = await store().tryOnWith(product("b"));
    expect(result).toMatchObject({ ok: false, message: expect.stringMatching(/photo has expired/i) });
    expect(store().phase).toBe("result");
    expect(store().captureKey).toBeNull();
  });

  it("does not even ask for a new look when the photo is already known to have expired", async () => {
    await toResult();
    useKioskStore.setState({ captureKey: null });
    const calls = mocks.api.createTryOn.mock.calls.length;

    const result = await store().tryOnWith(product("b"));

    expect(result).toMatchObject({ ok: false, message: expect.stringMatching(/photo has expired/i) });
    expect(mocks.api.createTryOn.mock.calls.length).toBe(calls);
    expect(store().selected.map((i) => i.product.id)).toEqual(["a"]); // and the item was not added
  });

  it("Back to Shop keeps the outfit and the looks", async () => {
    await toResult();
    store().backToShop();
    expect(store().phase).toBe("browsing");
    expect(store().view).toBe("shop");
    expect(store().selected).toHaveLength(1);
    expect(store().looks).toHaveLength(1);
  });
});

describe("saving to the cart and asking for staff", () => {
  it("adds every chosen item, then makes the mobile-page code", async () => {
    await toResult();
    mocks.api.addToCart.mockResolvedValue({ session_id: "sess-1", cart_id: "c", items: [], item_count: 2, subtotal_pkr: 2000 });
    mocks.api.createShare.mockResolvedValue({ short_code: "K7TQ4M2X", path: "/m/K7TQ4M2X", expires_at: "2026-01-02T00:00:00Z" });
    const items = [
      { product: product("a"), size: "M", color: null, fromRecommendation: false },
      { product: product("b"), size: "L", color: "Ivory", fromRecommendation: false },
    ];

    const result = await store().addSelectionToCart(items, "job-1");

    expect(result).toEqual({ ok: true });
    expect(mocks.api.addToCart.mock.calls.map(([a]) => [a.productId, a.size, a.color])).toEqual([
      ["a", "M", null],
      ["b", "L", "Ivory"],
    ]);
    expect(mocks.api.createShare).toHaveBeenCalledWith("sess-1", "job-1");
    expect(store().share?.short_code).toBe("K7TQ4M2X");
    store().dismissShare();
    expect(store().share).toBeNull();
  });

  it("stops at the first item the cart refuses and makes no code", async () => {
    await toResult();
    mocks.api.addToCart
      .mockResolvedValueOnce({ session_id: "sess-1", cart_id: "c", items: [], item_count: 1, subtotal_pkr: 1000 })
      .mockRejectedValueOnce(new ApiError(409, "Only 1 in stock"));
    const items = ["a", "b", "c"].map((id) => ({ product: product(id), size: "M", color: null, fromRecommendation: false }));

    const result = await store().addSelectionToCart(items, "job-1");

    expect(result).toEqual({ ok: false, message: "Only 1 in stock" });
    expect(mocks.api.addToCart).toHaveBeenCalledTimes(2);
    expect(mocks.api.createShare).not.toHaveBeenCalled();
    expect(store().share).toBeNull();
  });

  it("does not show a code to the next shopper if the session ended meanwhile", async () => {
    await toResult();
    mocks.api.addToCart.mockResolvedValue({ session_id: "sess-1", cart_id: "c", items: [], item_count: 1, subtotal_pkr: 1000 });
    let finish!: (s: unknown) => void;
    mocks.api.createShare.mockReturnValue(new Promise((r) => (finish = r)));
    const pending = store().addSelectionToCart([{ product: product("a"), size: "M", color: null, fromRecommendation: false }], "job-1");
    await flush();
    store().reset();
    finish({ short_code: "OLD", path: "/m/OLD", expires_at: "x" });
    await pending;
    expect(store().share).toBeNull();
  });

  it("asks staff for each chosen item and reports how many were sent", async () => {
    await toResult();
    mocks.api.requestOutfit.mockResolvedValue({ id: "r" });
    const items = [
      { product: product("a"), size: "M", color: "Ivory", fromRecommendation: false },
      { product: product("b"), size: "L", color: null, fromRecommendation: false },
    ];

    const result = await store().requestOutfit(items);

    expect(result).toEqual({ ok: true, sent: 2, message: null });
    expect(mocks.api.requestOutfit.mock.calls.map(([a]) => [a.productId, a.size, a.color])).toEqual([
      ["a", "M", "Ivory"],
      ["b", "L", null],
    ]);
  });

  it("reports how far it got when staff cannot be asked", async () => {
    await toResult();
    mocks.api.requestOutfit.mockResolvedValueOnce({ id: "r" }).mockRejectedValueOnce(new ApiError(422, "Choose a size: S, M"));
    const items = ["a", "b"].map((id) => ({ product: product(id), size: id === "a" ? "M" : null, color: null, fromRecommendation: false }));
    expect(await store().requestOutfit(items)).toEqual({ ok: false, sent: 1, message: "Choose a size: S, M" });
  });
});

describe("stopping part-way", () => {
  it("cancelling the countdown takes no photo and calls nothing", async () => {
    await readyToCapture();
    store().beginCountdown();
    store().cancelCountdown();
    expect(store().phase).toBe("capturing");
    expect(mocks.api.uploadCapture).not.toHaveBeenCalled();
  });

  it("leaving during the upload does not start a job or revive the screen", async () => {
    let finish!: (c: unknown) => void;
    mocks.api.uploadCapture.mockReturnValue(new Promise((r) => (finish = r)));
    await readyToCapture();
    const pending = store().submitCapture(photo);
    await flush();
    store().reset();
    finish({ key: "captures/sess-1/late.webp" });
    await pending;
    expect(mocks.api.createTryOn).not.toHaveBeenCalled();
    expect(store().phase).toBe("consent");
  });

  it("an error from a call the shopper already walked away from is not shown", async () => {
    let fail!: (e: unknown) => void;
    mocks.api.uploadCapture.mockReturnValue(new Promise((_r, rej) => (fail = rej)));
    await readyToCapture();
    const pending = store().submitCapture(photo);
    await flush();
    store().reset();
    fail(new ApiError(500, "boom"));
    await pending;
    expect(store().phase).toBe("consent");
    expect(store().error).toBeNull();
  });

  it("stops following the job and its timers when leaving, and frees the photo", async () => {
    await readyToCapture();
    await store().submitCapture(photo);
    await flush();
    store().reset();
    await vi.advanceTimersByTimeAsync(config.jobTimeoutMs + 1);
    expect(store().phase).toBe("consent");
    expect(store().timedOut).toBe(false);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:photo");
  });

  it("a new photo frees the previous one", async () => {
    await readyToCapture();
    await store().submitCapture(photo);
    await flush();
    store().retryTryOn;
    useKioskStore.setState({ phase: "countdown" });
    await store().submitCapture(photo);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:photo");
  });
});

describe("the cart", () => {
  beforeEach(openSession);

  it("the cart view opens only while browsing and closes back to the shop", async () => {
    mocks.api.getCart.mockResolvedValue({ session_id: "sess-1", cart_id: null, items: [], item_count: 0, subtotal_pkr: 0 });
    store().openCart();
    expect(store().view).toBe("cart");
    store().closeCart();
    expect(store().view).toBe("shop");
    useKioskStore.setState({ phase: "result" });
    store().openCart();
    expect(store().view).toBe("shop"); // not while a look is on screen
  });

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
    expect(store().view).toBe("cart");
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

describe("changing a cart quantity", () => {
  const line = (quantity: number) => ({ id: "line-1", product: { stock: 3 }, size: "M", color: null, quantity, unit_price_pkr: 500, line_total_pkr: 500 * quantity });
  const cartOf = (quantity: number) => ({ session_id: "sess-1", cart_id: "c1", items: [line(quantity)], item_count: quantity, subtotal_pkr: 500 * quantity });
  beforeEach(openSession);

  it("sends the new quantity and keeps the cart the API returns", async () => {
    useKioskStore.setState({ cart: cartOf(1) as never });
    mocks.api.setCartQuantity.mockResolvedValue(cartOf(2));

    const result = await store().setCartQuantity("line-1", 2);

    expect(result).toEqual({ ok: true });
    expect(mocks.api.setCartQuantity).toHaveBeenCalledWith("sess-1", "line-1", 2);
    expect(store().cart).toEqual(cartOf(2));
  });

  it("explains a stock refusal and refreshes the cart so the screen shows the real stock", async () => {
    useKioskStore.setState({ cart: cartOf(2) as never });
    mocks.api.setCartQuantity.mockRejectedValue(new ApiError(409, "Only 2 in stock"));
    mocks.api.getCart.mockResolvedValue(cartOf(2));

    const result = await store().setCartQuantity("line-1", 3);

    expect(result).toEqual({ ok: false, message: "Only 2 in stock" });
    expect(mocks.api.getCart).toHaveBeenCalledWith("sess-1");
  });

  it("still reports a stock refusal when the refresh fails too", async () => {
    mocks.api.setCartQuantity.mockRejectedValue(new ApiError(409, "Only 2 in stock"));
    mocks.api.getCart.mockRejectedValue(new ApiError(0, "offline"));
    expect(await store().setCartQuantity("line-1", 3)).toEqual({ ok: false, message: "Only 2 in stock" });
  });

  it("shows the real cart when the line was removed in the meantime", async () => {
    const empty = { session_id: "sess-1", cart_id: "c1", items: [], item_count: 0, subtotal_pkr: 0 };
    mocks.api.setCartQuantity.mockRejectedValue(new ApiError(404, "That item is not in the cart"));
    mocks.api.getCart.mockResolvedValue(empty);

    expect(await store().setCartQuantity("line-1", 2)).toEqual({ ok: true });
    expect(store().cart).toEqual(empty);
  });

  it("keeps the cart on screen when the request cannot be made", async () => {
    useKioskStore.setState({ cart: cartOf(1) as never });
    mocks.api.setCartQuantity.mockRejectedValue(new ApiError(0, "Can't reach the mirror's server."));
    expect(await store().setCartQuantity("line-1", 2)).toEqual({ ok: false, message: "Can't reach the mirror's server." });
    expect(store().cart).toEqual(cartOf(1));
    expect(mocks.api.getCart).not.toHaveBeenCalled(); // only 404 and 409 mean the screen is out of date
  });

  it("never shows the previous shopper's cart to the next one", async () => {
    let finish!: (c: unknown) => void;
    mocks.api.setCartQuantity.mockReturnValue(new Promise((r) => (finish = r)));
    const pending = store().setCartQuantity("line-1", 2);
    await flush();

    store().reset();
    finish(cartOf(2));
    await pending;

    expect(store().cart).toBeNull();
  });

  it("goes in line with other cart changes, so answers cannot arrive out of order", async () => {
    const answers: Array<(c: unknown) => void> = [];
    mocks.api.removeFromCart.mockImplementation(() => new Promise((r) => answers.push(r)));
    mocks.api.setCartQuantity.mockResolvedValue(cartOf(3));

    const removal = store().removeFromCart("line-9");
    const change = store().setCartQuantity("line-1", 3);
    await flush();
    expect(mocks.api.setCartQuantity).not.toHaveBeenCalled(); // waits for the removal to be answered

    answers[0](cartOf(1));
    await Promise.all([removal, change]);

    expect(mocks.api.setCartQuantity).toHaveBeenCalledTimes(1);
    expect(store().cart).toEqual(cartOf(3)); // the later change is the last word
  });
});

describe("checking out", () => {
  const order = { id: "o1", session_id: "sess-1", pickup_code: "K7TQ4M", item_count: 2, subtotal_pkr: 1000, created_at: "2026-01-01T00:00:00Z", items: [] };
  const fullCart = { session_id: "sess-1", cart_id: "c1", items: [{ id: "l1", product: { stock: 5 }, size: null, color: null, quantity: 2, unit_price_pkr: 500, line_total_pkr: 1000 }], item_count: 2, subtotal_pkr: 1000 };
  const emptyCart = { session_id: "sess-1", cart_id: "c1", items: [], item_count: 0, subtotal_pkr: 0 };
  const keyOf = (call: number) => mocks.api.checkout.mock.calls[call][1] as string;
  beforeEach(async () => {
    await openSession();
    useKioskStore.setState({ cart: fullCart as never });
  });

  it("places the order, shows it and empties the cart on screen", async () => {
    mocks.api.checkout.mockResolvedValue(order);

    const result = await store().placeOrder();

    expect(result).toEqual({ ok: true });
    expect(mocks.api.checkout).toHaveBeenCalledWith("sess-1", expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/));
    expect(store().order).toEqual(order);
    expect(store().cart).toEqual(emptyCart);
  });

  it("resends the same key after a failure that leaves the outcome unknown, so a lost answer cannot double-order", async () => {
    mocks.api.checkout.mockRejectedValueOnce(new ApiError(0, "Can't reach the mirror's server."));
    mocks.api.checkout.mockRejectedValueOnce(new ApiError(503, "Service Unavailable"));
    mocks.api.checkout.mockResolvedValueOnce(order);

    expect((await store().placeOrder()).ok).toBe(false);
    expect((await store().placeOrder()).ok).toBe(false);
    expect((await store().placeOrder()).ok).toBe(true);

    expect(keyOf(1)).toBe(keyOf(0));
    expect(keyOf(2)).toBe(keyOf(0));
    expect(store().cart).toEqual(emptyCart);
  });

  it("uses a new key for the next checkout once one has succeeded", async () => {
    mocks.api.checkout.mockResolvedValue(order);
    await store().placeOrder();
    useKioskStore.setState({ cart: fullCart as never, order: null });
    await store().placeOrder();
    expect(keyOf(1)).not.toBe(keyOf(0));
  });

  it("drops the key when the API refuses, and shows the real cart if stock is short", async () => {
    mocks.api.checkout.mockRejectedValue(new ApiError(409, "Not enough stock. Linen Shirt: only 1 left"));
    mocks.api.getCart.mockResolvedValue({ ...fullCart, items: [{ ...fullCart.items[0], product: { stock: 1 } }] });

    const result = await store().placeOrder();
    await store().placeOrder();

    expect(result).toEqual({ ok: false, message: "Not enough stock. Linen Shirt: only 1 left" });
    expect(mocks.api.getCart).toHaveBeenCalledWith("sess-1");
    expect(store().order).toBeNull();
    expect(keyOf(1)).not.toBe(keyOf(0)); // a refusal is an answer: the next attempt is a new checkout
  });

  it("still reports a refusal when refreshing the cart fails too", async () => {
    mocks.api.checkout.mockRejectedValue(new ApiError(409, "Your cart is empty"));
    mocks.api.getCart.mockRejectedValue(new ApiError(0, "offline"));
    expect(await store().placeOrder()).toEqual({ ok: false, message: "Your cart is empty" });
  });

  it("does not reuse a key once the cart has changed", async () => {
    mocks.api.checkout.mockRejectedValueOnce(new ApiError(0, "offline")); // outcome unknown
    mocks.api.setCartQuantity.mockResolvedValue({ ...fullCart, item_count: 3 });
    mocks.api.checkout.mockResolvedValueOnce(order);

    await store().placeOrder();
    await store().setCartQuantity("l1", 3); // the shopper edits the cart before retrying
    await store().placeOrder();

    expect(keyOf(1)).not.toBe(keyOf(0));
  });

  it("does not reuse a key after an item is added either", async () => {
    mocks.api.checkout.mockRejectedValueOnce(new ApiError(0, "offline"));
    mocks.api.addToCart.mockResolvedValue(fullCart);
    mocks.api.checkout.mockResolvedValueOnce(order);

    await store().placeOrder();
    await store().addToCart(product("a"), "M", null);
    await store().placeOrder();

    expect(keyOf(1)).not.toBe(keyOf(0));
  });

  it("does not show an order to the next shopper if the session ended while it was being placed", async () => {
    let finish!: (o: unknown) => void;
    mocks.api.checkout.mockReturnValue(new Promise((r) => (finish = r)));
    const pending = store().placeOrder();
    await flush();

    store().reset(); // idle timeout
    finish(order);
    await pending;

    expect(store().order).toBeNull();
    expect(store().cart).toBeNull();
  });

  it("does nothing without a session", async () => {
    store().reset();
    expect((await store().placeOrder()).ok).toBe(false);
    expect(mocks.api.checkout).not.toHaveBeenCalled();
  });

  it("goes in line behind a cart change that is still in flight", async () => {
    let finish!: (c: unknown) => void;
    mocks.api.setCartQuantity.mockReturnValue(new Promise((r) => (finish = r)));
    mocks.api.checkout.mockResolvedValue(order);

    const change = store().setCartQuantity("l1", 3);
    const placed = store().placeOrder();
    await flush();
    expect(mocks.api.checkout).not.toHaveBeenCalled(); // must not order the cart as it was before the change

    finish({ ...fullCart, item_count: 3 });
    await Promise.all([change, placed]);
    expect(mocks.api.checkout).toHaveBeenCalledTimes(1);
  });

  it("clears the order when dismissed and when the session ends", async () => {
    mocks.api.checkout.mockResolvedValue(order);
    await store().placeOrder();
    store().dismissOrder();
    expect(store().order).toBeNull();

    await openSession();
    useKioskStore.setState({ order: order as never });
    store().reset();
    expect(store().order).toBeNull();
  });
});
