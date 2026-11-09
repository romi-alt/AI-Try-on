/**
 * Idle detection for a shared screen.
 *
 *   active --(no input for warnAfterMs)--> warning --(no answer for graceMs)--> expired
 *
 * Input restarts the clock. While the warning is up only an explicit answer dismisses it, so a nudged mouse or
 * a passing shadow on a touch screen cannot keep an abandoned session alive.
 *
 * It compares against the real clock on a short tick instead of counting down with a timeout, so if the
 * machine sleeps and wakes, a session that is long overdue expires straight away rather than showing the
 * last shopper's screen for another warning period. Framework-free so it can be tested with fake timers.
 */

export type IdleState = "stopped" | "active" | "warning";
/**
 * presence: somebody seems to be there (mouse move, scroll, a press or touch). It restarts the clock while the
 *   session is active but cannot dismiss the warning.
 * confirm: an explicit answer to the warning (a click on it, a key press). It dismisses the warning.
 */
export type ActivityKind = "presence" | "confirm";

export type IdleOptions = {
  warnAfterMs: number; // 0 (or less) disables the timer
  graceMs: number;
  onWarn: () => void;
  onResume?: () => void; // a warning was dismissed
  onTick?: (secondsLeft: number) => void; // during the warning, whenever the displayed seconds change
  onExpire: () => void;
  tickMs?: number;
  now?: () => number;
};

export type IdleTimer = {
  /** Start counting from now. Does nothing if already running or disabled. */
  start(): void;
  /** Stop and forget everything. Safe to call at any time. */
  stop(): void;
  activity(kind: ActivityKind): void;
  readonly state: IdleState;
};

/** Mouse-move events arrive in floods; restarting the clock more than twice a second adds nothing. */
const PRESENCE_THROTTLE_MS = 500;

export function createIdleTimer(opts: IdleOptions): IdleTimer {
  const now = opts.now ?? Date.now;
  const tickMs = opts.tickMs ?? 250;
  const enabled = opts.warnAfterMs > 0;

  let state: IdleState = "stopped";
  let warnAt = 0;
  let expireAt = 0;
  let lastReset = 0;
  let lastSeconds = -1;
  let interval: ReturnType<typeof setInterval> | undefined;

  function restartClock() {
    const t = now();
    lastReset = t;
    warnAt = t + opts.warnAfterMs;
    expireAt = warnAt + Math.max(0, opts.graceMs);
  }

  function emitSeconds() {
    const secs = Math.max(0, Math.ceil((expireAt - now()) / 1000));
    if (secs !== lastSeconds) {
      lastSeconds = secs;
      opts.onTick?.(secs);
    }
  }

  function stop() {
    clearInterval(interval);
    interval = undefined;
    state = "stopped";
    lastSeconds = -1;
  }

  function expire() {
    stop(); // first, so the callback sees a stopped timer and may start a new one
    opts.onExpire();
  }

  function tick() {
    const t = now();
    if (t >= expireAt) return expire(); // also covers waking from sleep long past the deadline
    if (state === "active" && t >= warnAt) {
      state = "warning";
      opts.onWarn();
    }
    if (state === "warning") emitSeconds();
  }

  return {
    start() {
      if (!enabled || state !== "stopped") return;
      restartClock();
      state = "active";
      interval = setInterval(tick, tickMs);
    },
    stop,
    activity(kind) {
      if (state === "stopped") return;
      if (state === "active") {
        if (kind === "presence" && now() - lastReset < PRESENCE_THROTTLE_MS) return;
        restartClock();
        return;
      }
      if (kind === "confirm") {
        state = "active";
        lastSeconds = -1;
        restartClock();
        opts.onResume?.();
      }
    },
    get state() {
      return state;
    },
  };
}

/**
 * Whether the idle timer runs in a given kiosk phase. It is paused while the shopper is waiting on a try-on
 * (countdown, upload, rendering): they are present, just not touching anything. It restarts, in full, when the
 * phase changes, so the result gets its own full period.
 */
export function isIdleTrackedPhase(phase: string): boolean {
  return phase === "consent" || phase === "browsing" || phase === "result" || phase === "error";
}
