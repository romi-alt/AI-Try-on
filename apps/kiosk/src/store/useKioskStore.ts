import { create } from "zustand";
import { api, ApiError } from "@/lib/api";
import { config } from "@/lib/config";
import { createSessionEvents, type SessionEvents } from "@/lib/sessionEvents";
import type { Cart, Category, JobUpdate, Product, Session } from "@/lib/types";

export type Phase =
  | "consent" // waiting for the shopper to agree; no session yet, camera off
  | "starting" // creating the session
  | "browsing" // mirror live, choosing items
  | "countdown" // 3, 2, 1 ...
  | "uploading" // photo taken, sending it
  | "working" // job queued / processing
  | "result"
  | "error";

export type Filters = { category: Category | "all"; onSale: boolean; search: string };
export type CatalogState = "idle" | "loading" | "loadingMore" | "error";
export type CaptureFn = () => Promise<Blob>;
export type AddToCartResult = { ok: true } | { ok: false; message: string };
export type CartChangeResult = AddToCartResult;

const GENERIC_ERROR = "Something went wrong. Please try again.";
const TOO_SLOW = "This is taking longer than expected. Please try again.";

type State = {
  phase: Phase;
  /** Shown on the consent screen (session failed to start) or the error screen. */
  error: string | null;
  session: Session | null;

  filters: Filters;
  products: Product[];
  page: number;
  pages: number;
  total: number;
  catalogState: CatalogState;
  catalogError: string | null;

  /** The outfit, in the order chosen. Kept across filter changes and between looks. */
  selected: Product[];

  cameraReady: boolean;
  cameraError: string | null;
  countdown: number;

  job: JobUpdate | null;
  resultUrl: string | null;

  cart: Cart | null;
  cartOpen: boolean;

  agree: () => Promise<void>;
  setFilters: (patch: Partial<Filters>) => void;
  loadCatalog: (reset: boolean) => Promise<void>;
  toggleProduct: (product: Product) => void;
  removeProduct: (id: string) => void;
  setCamera: (ready: boolean, error?: string | null) => void;
  registerCapture: (fn: CaptureFn | null) => void;
  startTryOn: () => Promise<void>;
  cancelCountdown: () => void;
  backToBrowsing: () => void;
  addToCart: (product: Product, size: string | null, color: string | null) => Promise<AddToCartResult>;
  removeFromCart: (itemId: string) => Promise<CartChangeResult>;
  setCartQuantity: (itemId: string, quantity: number) => Promise<CartChangeResult>;
  openCart: () => void;
  closeCart: () => void;
  reset: () => void;
};

// Not reactive, so they live outside the store state.
let epoch = 0; // bumped on reset/cancel: any async step started under an older epoch stops quietly
let catalogToken = 0; // only the latest catalog request may write results
let events: SessionEvents | null = null;
let untrack: (() => void) | null = null;
let jobTimer: ReturnType<typeof setTimeout> | undefined;
let captureFn: CaptureFn | null = null;
// Cart changes are applied one at a time, in the order they were made. Each response is a whole cart, so
// two in flight together could otherwise finish out of order and leave the older cart on screen.
let cartQueue: Promise<unknown> = Promise.resolve();
function inCartOrder<T>(task: () => Promise<T>): Promise<T> {
  const run = cartQueue.then(task, task);
  cartQueue = run.catch(() => undefined);
  return run;
}

const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

export const describeError = (e: unknown): string =>
  e instanceof ApiError || e instanceof Error ? e.message || GENERIC_ERROR : GENERIC_ERROR;

function stopFollowingJob() {
  clearTimeout(jobTimer);
  jobTimer = undefined;
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
  error: null,
  session: null,
  filters: { category: "all", onSale: false, search: "" } as Filters,
  products: [] as Product[],
  page: 0,
  pages: 0,
  total: 0,
  catalogState: "idle" as CatalogState,
  catalogError: null,
  selected: [] as Product[],
  cameraReady: false,
  cameraError: null,
  countdown: 0,
  job: null,
  resultUrl: null,
  cart: null,
  cartOpen: false,
};

export const useKioskStore = create<State>((set, get) => {
  function fail(message: string) {
    stopFollowingJob();
    set({ phase: "error", error: message });
  }

  function followJob(jobId: string) {
    const sessionEvents = events;
    if (!sessionEvents) return fail(GENERIC_ERROR);
    stopFollowingJob();
    jobTimer = setTimeout(() => fail(TOO_SLOW), config.jobTimeoutMs);
    untrack = sessionEvents.track(jobId, (update) => {
      set({ job: update });
      if (update.status === "done") {
        if (!update.url) return fail(GENERIC_ERROR);
        stopFollowingJob();
        set({ phase: "result", resultUrl: update.url, error: null });
      } else if (update.status === "failed") {
        fail(update.error || GENERIC_ERROR);
      }
    });
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
        set({ session, phase: "browsing" });
        void get().loadCatalog(true);
      } catch (e) {
        if (mine !== epoch) return;
        set({ phase: "consent", error: describeError(e) });
      }
    },

    setFilters: (patch) => {
      set((s) => ({ filters: { ...s.filters, ...patch } }));
      void get().loadCatalog(true);
    },

    loadCatalog: async (reset) => {
      const { filters, page, pages } = get();
      if (!reset && page >= pages) return;
      const token = ++catalogToken;
      set({ catalogState: reset ? "loading" : "loadingMore", catalogError: null });
      try {
        const res = await api.listCatalog({ ...filters, page: reset ? 1 : page + 1 });
        if (token !== catalogToken) return; // a newer filter change superseded this request
        set((s) => {
          const known = new Set(reset ? [] : s.products.map((p) => p.id));
          const fresh = res.items.filter((p) => !known.has(p.id)); // pages can overlap if the catalog changed
          return {
            products: reset ? res.items : [...s.products, ...fresh],
            page: res.page,
            pages: res.pages,
            total: res.total,
            catalogState: "idle",
          };
        });
      } catch (e) {
        if (token !== catalogToken) return;
        set({ catalogState: "error", catalogError: describeError(e) });
      }
    },

    toggleProduct: (product) =>
      set((s) => {
        if (s.phase !== "browsing") return {}; // the outfit is locked while a look is being made
        if (s.selected.some((p) => p.id === product.id)) {
          return { selected: s.selected.filter((p) => p.id !== product.id) };
        }
        if (product.stock <= 0 || s.selected.length >= config.maxOutfitItems) return {};
        return { selected: [...s.selected, product] };
      }),

    removeProduct: (id) =>
      set((s) => (s.phase === "browsing" ? { selected: s.selected.filter((p) => p.id !== id) } : {})),

    setCamera: (ready, error = null) => set({ cameraReady: ready, cameraError: error }),

    registerCapture: (fn) => {
      captureFn = fn;
    },

    startTryOn: async () => {
      const { phase, session, selected, cameraReady } = get();
      if (phase !== "browsing" || !session || selected.length === 0 || !cameraReady || !captureFn) return;
      const mine = ++epoch; // cancelling or leaving bumps it again, which stops everything below
      const productIds = selected.map((p) => p.id);
      try {
        set({ phase: "countdown", error: null, job: null, resultUrl: null });
        for (let n = config.countdownSeconds; n > 0; n--) {
          set({ countdown: n });
          await sleep(1000);
          if (mine !== epoch) return;
        }
        const photo = await captureFn();
        if (mine !== epoch) return;

        set({ phase: "uploading" });
        const capture = await api.uploadCapture(session.id, photo);
        if (mine !== epoch) return;

        set({ phase: "working", job: { job: "", status: "queued", pct: 0 } });
        const accepted = await api.createTryOn(session.id, capture.key, productIds);
        if (mine !== epoch) return;
        followJob(accepted.job_id);
      } catch (e) {
        if (mine === epoch) fail(describeError(e));
      }
    },

    cancelCountdown: () => {
      if (get().phase !== "countdown") return;
      epoch++;
      set({ phase: "browsing" });
    },

    backToBrowsing: () => {
      stopFollowingJob();
      set({ phase: "browsing", error: null, job: null, resultUrl: null });
    },

    addToCart: (product, size, color) =>
      inCartOrder(async (): Promise<AddToCartResult> => {
        const sessionId = get().session?.id;
        if (!sessionId) return { ok: false, message: GENERIC_ERROR };
        try {
          const cart = await api.addToCart({ sessionId, productId: product.id, size, color });
          // The shopper may have left (idle reset) while this was in flight: never show their cart to the next one.
          if (get().session?.id === sessionId) set({ cart });
          return { ok: true };
        } catch (e) {
          return { ok: false, message: describeError(e) };
        }
      }),

    removeFromCart: (itemId) => changeCart((sessionId) => api.removeFromCart(sessionId, itemId)),

    setCartQuantity: (itemId, quantity) =>
      changeCart((sessionId) => api.setCartQuantity(sessionId, itemId, quantity)),

    openCart: () => {
      set({ cartOpen: true });
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

    closeCart: () => set({ cartOpen: false }),

    reset: () => {
      epoch++;
      catalogToken++;
      stopFollowingJob();
      events?.close();
      events = null;
      set({ ...initial });
    },
  };
});
