/**
 * Live job updates for one session.
 *
 * One WebSocket (`/ws?session=...`) stays open for the whole session. A job is followed with `track()`:
 *
 * - Updates for it arrive on the socket. Heartbeats (`{"type":"ping"}`) are ignored.
 * - The socket has no history, so on every (re)connect, and when tracking starts, the current state is read
 *   from `GET /jobs/{id}` to catch up. The server updates that state and publishes in one transaction, so
 *   connect-then-read can never miss an update.
 * - While the socket is down the state is polled instead, so a job still finishes if WebSockets are blocked.
 * - A socket that has been silent for `staleAfterMs` (the server pings every 25s) is treated as dead and replaced.
 * - Updates never move a job backwards: a poll answered late cannot undo a newer message.
 * - Messages that arrive before `track()` is called (the POST /tryon response racing the first events) are kept
 *   briefly and replayed.
 *
 * Framework-free on purpose, so it can be tested with a fake socket and fake timers.
 */
import type { JobState, JobUpdate } from "./types";

export type SocketLike = {
  onopen: ((ev?: unknown) => void) | null;
  onmessage: ((ev: { data: unknown }) => void) | null;
  onclose: ((ev?: unknown) => void) | null;
  onerror: ((ev?: unknown) => void) | null;
  close(): void;
};

export type SessionEventsOptions = {
  sessionId: string;
  /** e.g. `ws://localhost:8000` */
  wsUrl: string;
  fetchJob: (jobId: string) => Promise<JobState>;
  createSocket?: (url: string) => SocketLike;
  pollIntervalMs?: number;
  reconnectMinMs?: number;
  reconnectMaxMs?: number;
  staleAfterMs?: number;
};

export type SessionEvents = {
  /** Follow one job. Returns a function that stops following it. */
  track(jobId: string, onUpdate: (update: JobUpdate) => void): () => void;
  /** Close the socket and stop everything. */
  close(): void;
};

const BUFFER_LIMIT = 50;
/** A read still unanswered after this long no longer blocks the next poll (a request can hang). */
const READ_STALE_MS = 10_000;

type Tracked = { jobId: string; onUpdate: (u: JobUpdate) => void; last: JobUpdate | null };

const isTerminal = (u: JobUpdate) => u.status === "done" || u.status === "failed";
const rank = (u: JobUpdate) => (u.status === "queued" ? 0 : u.status === "processing" ? 1 : 2);

/** True if `next` is news relative to `last` (not a repeat, and not older). */
function isForward(last: JobUpdate | null, next: JobUpdate): boolean {
  if (!last) return true;
  if (isTerminal(last)) return false;
  if (rank(next) !== rank(last)) return rank(next) > rank(last);
  return next.pct > last.pct || isTerminal(next);
}

function parse(data: unknown): JobUpdate | "ping" | null {
  if (typeof data !== "string") return null;
  let msg: unknown;
  try {
    msg = JSON.parse(data);
  } catch {
    return null;
  }
  if (!msg || typeof msg !== "object") return null;
  const m = msg as Record<string, unknown>;
  if (m.type === "ping") return "ping";
  if (typeof m.job === "string" && typeof m.status === "string" && typeof m.pct === "number") {
    return m as unknown as JobUpdate;
  }
  return null;
}

export function createSessionEvents(opts: SessionEventsOptions): SessionEvents {
  const pollMs = opts.pollIntervalMs ?? 2000;
  const minBackoff = opts.reconnectMinMs ?? 500;
  const maxBackoff = opts.reconnectMaxMs ?? 10_000;
  const staleMs = opts.staleAfterMs ?? 60_000;
  const url = `${opts.wsUrl}/ws?session=${encodeURIComponent(opts.sessionId)}`;
  const makeSocket = opts.createSocket ?? ((u: string) => new WebSocket(u) as unknown as SocketLike);

  let socket: SocketLike | null = null;
  let connected = false;
  let closed = false;
  let backoff = minBackoff;
  let tracked: Tracked | null = null;
  let buffer: JobUpdate[] = [];
  let inflight = false;
  let inflightSince = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let staleTimer: ReturnType<typeof setTimeout> | undefined;
  let pollTimer: ReturnType<typeof setInterval> | undefined;

  function detach(ws: SocketLike) {
    ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
    try {
      ws.close();
    } catch {
      /* already closed */
    }
  }

  function apply(update: JobUpdate) {
    const t = tracked;
    if (!t || t.jobId !== update.job || !isForward(t.last, update)) return;
    t.last = update;
    t.onUpdate(update);
    if (isTerminal(update)) {
      tracked = null;
      stopPolling(); // the socket stays open for the session's next job
    }
  }

  function dispatch(update: JobUpdate) {
    if (tracked && tracked.jobId === update.job) {
      apply(update);
      return;
    }
    buffer.push(update);
    if (buffer.length > BUFFER_LIMIT) buffer.shift();
  }

  /**
   * Read the job's current state and apply it. Polling passes `force = false` so reads never pile up behind a
   * slow server; a read after (re)connecting or at track() always goes out, so a hung earlier read cannot
   * stop us catching up.
   */
  function catchUp(force: boolean) {
    const t = tracked;
    if (!t) return;
    if (!force && inflight && Date.now() - inflightSince < READ_STALE_MS) return;
    inflight = true;
    inflightSince = Date.now();
    opts
      .fetchJob(t.jobId)
      .then((s) => {
        if (tracked === t) apply({ job: s.job, status: s.status, pct: s.pct, url: s.url, error: s.error });
      })
      .catch(() => {
        /* transient: the next poll or reconnect tries again */
      })
      .finally(() => {
        inflight = false;
      });
  }

  function startPolling() {
    if (pollTimer || !tracked || connected || closed) return;
    pollTimer = setInterval(() => catchUp(false), pollMs);
  }

  function stopPolling() {
    clearInterval(pollTimer);
    pollTimer = undefined;
  }

  function armStale(ws: SocketLike) {
    clearTimeout(staleTimer);
    staleTimer = setTimeout(() => down(ws), staleMs);
  }

  function down(ws: SocketLike) {
    if (socket !== ws) return;
    detach(ws);
    socket = null;
    connected = false;
    clearTimeout(staleTimer);
    if (closed) return;
    reconnectTimer = setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, maxBackoff);
    startPolling();
  }

  function connect() {
    if (closed) return;
    const ws = makeSocket(url);
    socket = ws;
    ws.onopen = () => {
      if (socket !== ws) return;
      connected = true;
      backoff = minBackoff;
      stopPolling();
      armStale(ws);
      catchUp(true);
    };
    ws.onmessage = (ev) => {
      if (socket !== ws) return;
      armStale(ws);
      const msg = parse(ev.data);
      if (msg && msg !== "ping") dispatch(msg);
    };
    ws.onclose = ws.onerror = () => down(ws);
  }

  connect();

  return {
    track(jobId, onUpdate) {
      const t: Tracked = { jobId, onUpdate, last: null };
      tracked = t;
      const early = buffer.filter((u) => u.job === jobId);
      buffer = [];
      early.forEach(apply);
      if (tracked === t) {
        catchUp(true);
        startPolling();
      }
      return () => {
        if (tracked === t) {
          tracked = null;
          stopPolling();
        }
      };
    },

    close() {
      closed = true;
      clearTimeout(reconnectTimer);
      clearTimeout(staleTimer);
      stopPolling();
      if (socket) detach(socket);
      socket = null;
      tracked = null;
      buffer = [];
    },
  };
}
