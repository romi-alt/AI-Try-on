import { create } from "zustand";
import { api, ApiError } from "@/lib/api";
import { config } from "@/lib/config";
import { createSessionEvents, type SessionEvents } from "@/lib/sessionEvents";
import { DEFAULT_TAB, type TabId } from "@/lib/categories";
import type { Cart, JobUpdate, Order, Product, Session, ShareLink } from "@/lib/types";

export type Phase =
  | "consent" // waiting for the shopper to agree; no session yet, camera off
  | "starting" // creating the session
  | "browsing" // choosing items in the shop; camera off
  | "capturing" // camera on, guiding the shopper into frame
  | "countdown" // "Strike a pose" 3, 2, 1
  | "uploading" // photo taken, sending it
  | "working" // job queued / processing
  | "result"
  | "error";

/** The main area's content while browsing. The sidebar switches between these. */
export type View = "shop" | "scanner" | "cart" | "help" | "settings";

/** One chosen item with the options the shopper picked for it. */
export type Selection = {
  product: Product;
  size: string | null;
  color: string | null;
  /** Added from "More styles" / "Complete your look" (reported to the API for the recommendation analytics). */
  fromRecommendation: boolean;
};

/** A finished try-on: the image and the items it shows. */
export type Look = { jobId: string; url: string; items: Selection[] };

export type CaptureFn = () => Promise<Blob>;
export type AddToCartResult = { ok: true } | { ok: false; message: string };
export type CartChangeResult = AddToCartResult;
export type SelectResult = { ok: true } | { ok: false; message: string };

const GENERIC_ERROR = "Something went wrong. Please try again.";
const TOO_SLOW = "This is taking longer than expected. Please try again.";
const MAX_LOOKS = 4;

type State = {
  phase: Phase;
  view: View;
  /** Shown on the consent screen (session failed to start) or the error screen. */
  error: string | null;
  session: Session | null;

  /** The shop's active tab and the product whose detail panel is open. */
  tab: TabId;
  detail: Product | null;

  /** The outfit, in the order chosen. Kept across tabs and between looks. */
  selected: Selection[];

  cameraError: string | null;
  countdown: number;
  /** The photo just taken, as an object URL: shown blurred behind the progress ring. */
  photoUrl: string | null;
  captureKey: string | null;

  job: JobUpdate | null;
  /** True once a try-on has taken longer than `tryOnSlowMs`: the screen offers "Try again" (the job keeps going). */
  timedOut: boolean;
  looks: Look[];
  lookIndex: number;

  cart: Cart | null;
  /** The order just placed, shown until the shopper is done. Cleared when the session ends. */
  order: Order | null;
  /** The mobile-page code, set by "Add Selected to Cart" and shown as a QR code until dismissed. */
  share: ShareLink | null;

  agree: () => Promise<void>;
  setTab: (tab: TabId) => void;
  openDetail: (product: Product | null) => void;
  setView: (view: View) => void;

  select: (product: Product, opts?: { size?: string | null; color?: string | null; fromRecommendation?: boolean }) => SelectResult;
  deselect: (productId: string) => void;
  setSelectionOptions: (productId: string, opts: { size?: string | null; color?: string | null }) => void;

  startCapture: () => void;
  cancelCapture: () => void;
  setCameraError: (error: string | null) => void;
  beginCountdown: () => void;
  setCountdown: (n: number) => void;
  cancelCountdown: () => void;
  submitCapture: (photo: Blob) => Promise<void>;
  retryTryOn: () => Promise<void>;
  /** Add an item to the outfit and make a new look with the photo already taken (no new capture). */
  tryOnWith: (product: Product, opts?: { fromRecommendation?: boolean }) => Promise<SelectResult>;
  showLook: (index: number) => void;
  backToShop: () => void;

  addToCart: (product: Product, size: string | null, color: string | null) => Promise<AddToCartResult>;
  addSelectionToCart: (items: Selection[], jobId: string | null) => Promise<AddToCartResult>;
  requestOutfit: (items: Selection[]) => Promise<{ ok: boolean; sent: number; message: string | null }>;
  dismissShare: () => void;
  removeFromCart: (itemId: string) => Promise<CartChangeResult>;
  setCartQuantity: (itemId: string, quantity: number) => Promise<CartChangeResult>;
  placeOrder: () => Promise<CartChangeResult>;
  dismissOrder: () => void;
  openCart: () => void;
  closeCart: () => void;
  reset: () => void;
};

// Not reactive, so they live outside the store state.
let epoch = 0; // bumped on reset/cancel: any async step started under an older epoch stops quietly
let slowTimer: ReturnType<typeof setTimeout> | undefined;
let pendingItems: Selection[] = []; // the outfit of the job being followed
let events: SessionEvents | null = null;
let untrack: (() => void) | null = null;
let jobTimer: ReturnType<typeof setTimeout> | undefined;
// Cart changes are applied one at a time, in the order they were made. Each response is a whole cart, so
// two in flight together could otherwise finish out of order and leave the older cart on screen.
let cartQueue: Promise<unknown> = Promise.resolve();
function inCartOrder<T>(task: () => Promise<T>): Promise<T> {
  const run = cartQueue.then(task, task);
  cartQueue = run.catch(() => undefined);
  return run;
}

// One per checkout attempt. It is kept after a failure that leaves the outcome unknown (no answer, a server error)
// so the retry gets the order back if it was in fact placed, and dropped as soon as the outcome is known or the
// cart changes, so it can never return an old order for a different cart.
let checkoutKey: string | null = null;

function newKey(): string {
  const b = crypto.getRandomValues(new Uint8Array(16)); // randomUUID needs a secure context; this does not
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = [...b].map((x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export const describeError = (e: unknown): string =>
  e instanceof ApiError || e instanceof Error ? e.message || GENERIC_ERROR : GENERIC_ERROR;

function stopFollowingJob() {
  clearTimeout(jobTimer);
  clearTimeout(slowTimer);
  jobTimer = undefined;
  slowTimer = undefined;
  untrack?.();
  untrack = null;
}

/**
 * Applies one change to the cart (remove a line, set its quantity) and keeps the cart the API answers with.
 * When the API says the line is gone (404) or there is not enough stock (409) the cart on screen is out of date,
 * so the real one is fetched; a vanished line then counts as done, while a stock refusal still reports why.
 */
function changeCart(call: (sessionId: string) => Promise<Cart>): Promise<CartChangeResult> {
  return inCartOrder(async (): Promise<CartChangeResult> => {
    const sessionId = useKioskStore.getState().session?.id;
    if (!sessionId) return { ok: false, message: GENERIC_ERROR };
    const apply = (cart: Cart) => {
      if (useKioskStore.getState().session?.id === sessionId) useKioskStore.setState({ cart });
    };
    try {
      apply(await call(sessionId));
      checkoutKey = null; // the cart changed: a retried checkout is a different one
      return { ok: true };
    } catch (e) {
      if (e instanceof ApiError && (e.status === 404 || e.status === 409)) {
        let refreshed = false;
        try {
          apply(await api.getCart(sessionId));
          refreshed = true;
        } catch {
          /* keep the original message */
        }
        if (e.status === 404 && refreshed) return { ok: true };
      }
      return { ok: false, message: describeError(e) };
    }
  });
}

const initial = {
  phase: "consent" as Phase,
  view: "shop" as View,
  error: null,
  session: null,
  tab: DEFAULT_TAB as TabId,
  detail: null,
  selected: [] as Selection[],
  cameraError: null,
  countdown: 0,
  photoUrl: null,
  captureKey: null,
  job: null,
  timedOut: false,
  looks: [] as Look[],
  lookIndex: 0,
  cart: null,
  order: null,
  share: null,
};

export const useKioskStore = create<State>((set, get) => {
  function fail(message: string) {
    stopFollowingJob();
    set({ phase: "error", error: message });
  }

  function followJob(jobId: string, items: Selection[]) {
    const sessionEvents = events;
    if (!sessionEvents) return fail(GENERIC_ERROR);
    stopFollowingJob();
    pendingItems = items;
    set({ timedOut: false });
    jobTimer = setTimeout(() => fail(TOO_SLOW), config.jobTimeoutMs);
    slowTimer = setTimeout(() => set({ timedOut: true }), config.tryOnSlowMs); // offers "Try again"; the job keeps going
    untrack = sessionEvents.track(jobId, (update) => {
      set({ job: update });
      if (update.status === "done") {
        if (!update.url) return fail(GENERIC_ERROR);
        stopFollowingJob();
        set((s) => {
          const looks = [...s.looks, { jobId, url: update.url as string, items: pendingItems }].slice(-MAX_LOOKS);
          return { phase: "result", looks, lookIndex: looks.length - 1, timedOut: false, error: null };
        });
      } else if (update.status === "failed") {
        fail(update.error || GENERIC_ERROR);
      }
    });
  }

  /** Create the try-on for `items` from an already uploaded photo and follow it. */
  async function runTryOn(items: Selection[], captureKey: string, mine: number) {
    const session = get().session;
    if (!session) return fail(GENERIC_ERROR);
    set({ phase: "working", job: { job: "", status: "queued", pct: 0 }, timedOut: false, error: null });
    const accepted = await api.createTryOn(
      session.id,
      captureKey,
      items.map((i) => i.product.id),
      items.filter((i) => i.fromRecommendation).map((i) => i.product.id),
    );
    if (mine !== epoch) return;
    followJob(accepted.job_id, items);
  }

  return {
    ...initial,

    agree: async () => {
      if (get().phase !== "consent") return;
      const mine = epoch;
      set({ phase: "starting", error: null });
      try {
        const session = await api.createSession();
        if (mine !== epoch) return;
        events = createSessionEvents({
          sessionId: session.id,
          wsUrl: config.wsUrl,
          fetchJob: api.getJob,
          pollIntervalMs: config.pollIntervalMs,
          reconnectMinMs: config.reconnectMinMs,
          reconnectMaxMs: config.reconnectMaxMs,
          staleAfterMs: config.staleSocketMs,
        });
        set({ session, phase: "browsing", view: "shop" });
      } catch (e) {
        if (mine !== epoch) return;
        set({ phase: "consent", error: describeError(e) });
      }
    },

    setTab: (tab) => set({ tab }),
    openDetail: (product) => set({ detail: product }),
    setView: (view) => set((s) => (s.phase === "browsing" ? { view, detail: null } : {})),

    select: (product, opts = {}) => {
      const s = get();
      if (s.phase !== "browsing" && s.phase !== "result") {
        return { ok: false, message: "Your outfit can't change while a look is being made." };
      }
      if (product.stock <= 0) return { ok: false, message: "That item is sold out." };
      const existing = s.selected.find((i) => i.product.id === product.id);
      if (!existing && s.selected.length >= config.maxOutfitItems) {
        return { ok: false, message: `You can try on up to ${config.maxOutfitItems} items at once.` };
      }
      const next: Selection = {
        product,
        size: opts.size !== undefined ? opts.size : (existing?.size ?? null),
        color: opts.color !== undefined ? opts.color : (existing?.color ?? null),
        fromRecommendation: opts.fromRecommendation ?? existing?.fromRecommendation ?? false,
      };
      set({
        selected: existing
          ? s.selected.map((i) => (i.product.id === product.id ? next : i))
          : [...s.selected, next],
      });
      return { ok: true };
    },

    deselect: (productId) =>
      set((s) => (s.phase === "browsing" || s.phase === "result" ? { selected: s.selected.filter((i) => i.product.id !== productId) } : {})),

    setSelectionOptions: (productId, opts) =>
      set((s) => ({
        selected: s.selected.map((i) =>
          i.product.id === productId
            ? { ...i, size: opts.size !== undefined ? opts.size : i.size, color: opts.color !== undefined ? opts.color : i.color }
            : i,
        ),
      })),

    startCapture: () => {
      const { phase, session, selected } = get();
      if (phase !== "browsing" || !session || selected.length === 0) return;
      set({ phase: "capturing", cameraError: null, error: null, job: null, detail: null });
    },

    cancelCapture: () => {
      const { phase } = get();
      if (phase !== "capturing" && phase !== "countdown") return;
      epoch++;
      set({ phase: "browsing", countdown: 0, cameraError: null });
    },

    setCameraError: (error) => set({ cameraError: error }),

    beginCountdown: () => {
      if (get().phase === "capturing") set({ phase: "countdown", countdown: config.countdownSeconds });
    },

    setCountdown: (n) => {
      if (get().phase === "countdown") set({ countdown: n });
    },

    cancelCountdown: () => {
      if (get().phase === "countdown") set({ phase: "capturing", countdown: 0 });
    },

    submitCapture: async (photo) => {
      const { phase, session, selected } = get();
      if ((phase !== "countdown" && phase !== "capturing") || !session || selected.length === 0) return;
      const mine = ++epoch; // cancelling or leaving bumps it again, which stops everything below
      const url = URL.createObjectURL(photo);
      set((s) => {
        if (s.photoUrl) URL.revokeObjectURL(s.photoUrl);
        return { phase: "uploading", photoUrl: url, countdown: 0, error: null, job: null };
      });
      try {
        const capture = await api.uploadCapture(session.id, photo);
        if (mine !== epoch) return;
        set({ captureKey: capture.key });
        await runTryOn(selected, capture.key, mine);
      } catch (e) {
        if (mine === epoch) fail(describeError(e));
      }
    },

    retryTryOn: async () => {
      const { phase, captureKey, selected, session } = get();
      if ((phase !== "working" && phase !== "error") || !session || selected.length === 0) return;
      if (!captureKey) return set({ phase: "capturing", error: null, job: null });
      stopFollowingJob();
      const mine = ++epoch;
      try {
        await runTryOn(selected, captureKey, mine);
      } catch (e) {
        if (mine !== epoch) return;
        if (e instanceof ApiError && e.status === 404) {
          // The photo was deleted (they only last an hour): take a new one.
          set({ phase: "capturing", captureKey: null, error: null, job: null });
        } else {
          fail(describeError(e));
        }
      }
    },

    tryOnWith: async (product, opts = {}) => {
      const { phase, captureKey, session } = get();
      if (phase !== "result" || !session) return { ok: false, message: GENERIC_ERROR };
      if (!captureKey) return { ok: false, message: "Your photo has expired. Go back and take a new one." };
      const added = get().select(product, { fromRecommendation: opts.fromRecommendation ?? false });
      if (!added.ok) return added;
      const mine = ++epoch;
      try {
        await runTryOn(get().selected, captureKey, mine);
        return { ok: true };
      } catch (e) {
        if (mine === epoch) {
          if (e instanceof ApiError && e.status === 404) {
            set({ phase: "result", captureKey: null });
            return { ok: false, message: "Your photo has expired. Go back and take a new one." };
          }
          set({ phase: "result" });
        }
        return { ok: false, message: describeError(e) };
      }
    },

    showLook: (index) => set((s) => (index >= 0 && index < s.looks.length ? { lookIndex: index } : {})),

    backToShop: () => {
      stopFollowingJob();
      set({ phase: "browsing", view: "shop", error: null, job: null, timedOut: false, share: null });
    },

    addToCart: (product, size, color) =>
      inCartOrder(async (): Promise<AddToCartResult> => {
        const sessionId = get().session?.id;
        if (!sessionId) return { ok: false, message: GENERIC_ERROR };
        try {
          const cart = await api.addToCart({ sessionId, productId: product.id, size, color });
          // The shopper may have left (idle reset) while this was in flight: never show their cart to the next one.
          if (get().session?.id === sessionId) set({ cart });
          checkoutKey = null;
          return { ok: true };
        } catch (e) {
          return { ok: false, message: describeError(e) };
        }
      }),

    removeFromCart: (itemId) => changeCart((sessionId) => api.removeFromCart(sessionId, itemId)),

    setCartQuantity: (itemId, quantity) =>
      changeCart((sessionId) => api.setCartQuantity(sessionId, itemId, quantity)),

    placeOrder: () =>
      inCartOrder(async (): Promise<CartChangeResult> => {
        const sessionId = get().session?.id;
        if (!sessionId) return { ok: false, message: GENERIC_ERROR };
        const key = (checkoutKey ??= newKey());
        try {
          const order = await api.checkout(sessionId, key);
          checkoutKey = null;
          if (get().session?.id === sessionId) {
            const cart = get().cart;
            set({
              order,
              cart: { session_id: sessionId, cart_id: cart?.cart_id ?? null, items: [], item_count: 0, subtotal_pkr: 0 },
            });
          }
          return { ok: true };
        } catch (e) {
          if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
            checkoutKey = null; // refused: the outcome is known
            if (e.status === 409) {
              // Short of stock, or the cart was already emptied: show the shopper the real cart.
              try {
                const cart = await api.getCart(sessionId);
                if (get().session?.id === sessionId) set({ cart });
              } catch {
                /* keep the message below */
              }
            }
          }
          return { ok: false, message: describeError(e) };
        }
      }),

    dismissOrder: () => set({ order: null }),

    addSelectionToCart: async (items, jobId) => {
      for (const item of items) {
        const result = await get().addToCart(item.product, item.size, item.color);
        if (!result.ok) return result;
      }
      const sessionId = get().session?.id;
      if (!sessionId) return { ok: false, message: GENERIC_ERROR };
      try {
        const share = await api.createShare(sessionId, jobId);
        if (get().session?.id === sessionId) set({ share });
        return { ok: true };
      } catch (e) {
        return { ok: false, message: describeError(e) };
      }
    },

    requestOutfit: async (items) => {
      const sessionId = get().session?.id;
      if (!sessionId) return { ok: false, sent: 0, message: GENERIC_ERROR };
      let sent = 0;
      for (const item of items) {
        try {
          await api.requestOutfit({ sessionId, productId: item.product.id, size: item.size, color: item.color });
          sent++;
        } catch (e) {
          return { ok: false, sent, message: describeError(e) };
        }
      }
      return { ok: true, sent, message: null };
    },

    dismissShare: () => set({ share: null }),

    openCart: () => {
      set((s) => (s.phase === "browsing" ? { view: "cart", detail: null } : {}));
      const sessionId = get().session?.id;
      if (!sessionId) return;
      void inCartOrder(async () => {
        try {
          const cart = await api.getCart(sessionId);
          if (get().session?.id === sessionId) set({ cart });
        } catch {
          /* the cart on screen stays as it was */
        }
      });
    },

    closeCart: () => set((s) => (s.view === "cart" ? { view: "shop" } : {})),

    reset: () => {
      checkoutKey = null;
      epoch++;
      stopFollowingJob();
      pendingItems = [];
      events?.close();
      events = null;
      const photo = get().photoUrl;
      if (photo) URL.revokeObjectURL(photo);
      set({ ...initial });
    },
  };
});
