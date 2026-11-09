/**
 * Knows whether the mirror can reach its server, and tells the screen when that changes.
 *
 * A shop's internet drops now and then. The browser's own `navigator.onLine` only knows about the network cable or
 * Wi-Fi, not about the API being unreachable, so the real test is asking the API (`GET /health`). The rules:
 *
 * - Offline is declared after two failed checks in a row (one blip is not an outage), or at once when the browser
 *   itself says it is offline.
 * - Online again after the first success, so the screen comes back the moment the connection does.
 * - While online, check every 15 s; while offline, every 3 s, backing off to 10 s.
 * - `nudge()` checks right now. The API client calls it when a request fails, so a real failure is noticed within
 *   a second or two instead of at the next scheduled check.
 *
 * Framework-free so it can be tested with fake timers and a fake `ping`.
 */
export type Connectivity = "online" | "offline";

export type ConnectivityOptions = {
  /** Resolves true when the server answered. Must give up (reject or resolve false) when `signal` aborts. */
  ping: (signal: AbortSignal) => Promise<boolean>;
  onChange: (state: Connectivity) => void;
  /** Whether the browser thinks it has a network. Default: `navigator.onLine`. */
  isBrowserOnline?: () => boolean;
  /** Subscribe to the browser's `online` / `offline` events; returns the unsubscribe function. */
  listen?: (type: "online" | "offline", handler: () => void) => () => void;
  onlineIntervalMs?: number;
  offlineIntervalMs?: number;
  maxOfflineIntervalMs?: number;
  /** A check that has not answered by then counts as failed. */
  timeoutMs?: number;
  failuresBeforeOffline?: number;
};

export type ConnectivityMonitor = {
  start(): void;
  stop(): void;
  nudge(): void;
  state(): Connectivity;
};

export function createConnectivityMonitor(opts: ConnectivityOptions): ConnectivityMonitor {
  const onlineMs = opts.onlineIntervalMs ?? 15_000;
  const offlineMs = opts.offlineIntervalMs ?? 3_000;
  const maxOfflineMs = opts.maxOfflineIntervalMs ?? 10_000;
  const timeoutMs = opts.timeoutMs ?? 4_000;
  const threshold = opts.failuresBeforeOffline ?? 2;
  const browserOnline = opts.isBrowserOnline ?? (() => (typeof navigator === "undefined" ? true : navigator.onLine));

  let current: Connectivity = "online";
  let failures = 0;
  let backoff = offlineMs;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let inflight = false;
  let running = false;
  let unlisten: (() => void)[] = [];

  function set(next: Connectivity) {
    if (next === current) return;
    current = next;
    opts.onChange(next);
  }

  function schedule(ms: number) {
    clearTimeout(timer);
    if (running) timer = setTimeout(check, ms);
  }

  async function check() {
    if (inflight || !running) return;
    inflight = true;
    clearTimeout(timer);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let ok = false;
    try {
      ok = await Promise.race([
        opts.ping(controller.signal).catch(() => false),
        new Promise<boolean>((resolve) => controller.signal.addEventListener("abort", () => resolve(false))),
      ]);
    } finally {
      clearTimeout(timeout);
      inflight = false;
    }
    if (!running) return;
    if (ok) {
      failures = 0;
      backoff = offlineMs;
      set("online");
      schedule(onlineMs);
      return;
    }
    failures += 1;
    if (failures >= threshold || !browserOnline()) {
      set("offline");
      schedule(backoff);
      backoff = Math.min(Math.round(backoff * 1.5), maxOfflineMs);
    } else {
      schedule(1_500); // one failure: look again soon before calling it an outage
    }
  }

  return {
    start() {
      if (running) return;
      running = true;
      const listen = opts.listen ?? ((type, handler) => (window.addEventListener(type, handler), () => window.removeEventListener(type, handler)));
      unlisten = [
        listen("offline", () => {
          failures = threshold;
          set("offline");
          schedule(offlineMs);
        }),
        listen("online", () => void check()),
      ];
      void check();
    },
    stop() {
      running = false;
      clearTimeout(timer);
      unlisten.forEach((u) => u());
      unlisten = [];
    },
    nudge() {
      void check();
    },
    state: () => current,
  };
}
