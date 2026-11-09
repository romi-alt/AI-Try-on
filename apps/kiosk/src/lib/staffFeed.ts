/**
 * The staff page's live list of "Request Outfit" requests.
 *
 * Same idea as `sessionEvents`, for `WS /ws/staff`: the socket sends `{"type":"auth","key":...}`, the server
 * answers `{"type":"ready"}` once it is subscribed, and only then is `GET /requests` read, so nothing can fall
 * between the list and the stream. Events (`request.created` / `request.updated`) are merged into the list as they
 * arrive. While the socket is down the list is re-read every few seconds, and the socket reconnects with
 * exponential backoff. A wrong key (the server closes with 1008, or the list answers 401) stops everything instead
 * of retrying forever.
 *
 * Framework-free so it can be tested with a fake socket and fake timers.
 */
import type { SocketLike } from "./sessionEvents";
import type { StaffRequest } from "./types";

export type StaffFeedStatus = "connecting" | "live" | "offline" | "unauthorized";
export type StaffFeedState = { status: StaffFeedStatus; requests: StaffRequest[] };

export type StaffSocket = SocketLike & { send(data: string): void };

export type StaffFeedOptions = {
  wsUrl: string;
  key: string;
  fetchList: () => Promise<StaffRequest[]>;
  onChange: (state: StaffFeedState) => void;
  createSocket?: (url: string) => StaffSocket;
  reconnectMinMs?: number;
  reconnectMaxMs?: number;
  /** How often the list is re-read while the socket is down. */
  pollIntervalMs?: number;
  /** A socket silent for this long (the server pings every 25s) is treated as dead. */
  staleAfterMs?: number;
};

export type StaffFeed = { close(): void; refresh(): void };

const byAge = (a: StaffRequest, b: StaffRequest) =>
  a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : a.id < b.id ? -1 : 1;

/**
 * Merge one request into the open list. `done` leaves the list; an older copy never replaces a newer one, so a
 * list read that was answered late cannot undo a newer event.
 */
export function upsertRequest(list: StaffRequest[], incoming: StaffRequest): StaffRequest[] {
  const existing = list.find((r) => r.id === incoming.id);
  if (existing && existing.updated_at > incoming.updated_at) return list;
  const rest = list.filter((r) => r.id !== incoming.id);
  return incoming.status === "done" ? rest : [...rest, incoming].sort(byAge);
}

/** Replace the list with a fresh read, keeping any request that is newer locally (an event that overtook it). */
export function mergeList(current: StaffRequest[], fresh: StaffRequest[]): StaffRequest[] {
  let out = [...fresh].sort(byAge);
  for (const r of current) {
    const f = fresh.find((x) => x.id === r.id);
    if (f && r.updated_at > f.updated_at) out = upsertRequest(out, r);
  }
  return out;
}

function parse(data: unknown): { type: string; request?: StaffRequest } | null {
  if (typeof data !== "string") return null;
  try {
    const msg = JSON.parse(data);
    return msg && typeof msg === "object" && typeof msg.type === "string" ? msg : null;
  } catch {
    return null;
  }
}

const POLICY_VIOLATION = 1008;

export function createStaffFeed(opts: StaffFeedOptions): StaffFeed {
  const minBackoff = opts.reconnectMinMs ?? 500;
  const maxBackoff = opts.reconnectMaxMs ?? 10_000;
  const pollMs = opts.pollIntervalMs ?? 5000;
  const staleMs = opts.staleAfterMs ?? 60_000;
  const url = `${opts.wsUrl}/ws/staff`;
  const makeSocket = opts.createSocket ?? ((u: string) => new WebSocket(u) as unknown as StaffSocket);

  let state: StaffFeedState = { status: "connecting", requests: [] };
  let socket: StaffSocket | null = null;
  let closed = false;
  let backoff = minBackoff;
  let ready = false;
  let reading = false;
  let duringRead: StaffRequest[] = [];
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
  let staleTimer: ReturnType<typeof setTimeout> | undefined;
  let pollTimer: ReturnType<typeof setInterval> | undefined;

  function set(next: Partial<StaffFeedState>) {
    if (closed) return;
    state = { ...state, ...next };
    opts.onChange(state);
  }

  function unauthorized() {
    set({ status: "unauthorized", requests: [] });
    stop();
  }

  function stop() {
    closed = true;
    clearTimeout(reconnectTimer);
    clearTimeout(staleTimer);
    clearInterval(pollTimer);
    pollTimer = undefined;
    if (socket) detach(socket);
    socket = null;
  }

  function detach(ws: StaffSocket) {
    ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null;
    try {
      ws.close();
    } catch {
      /* already closed */
    }
  }

  function read() {
    if (closed || reading) return;
    reading = true;
    duringRead = [];
    opts
      .fetchList()
      .then((fresh) => {
        // Events that arrived while the read was in flight may be newer than what it saw: apply them on top.
        if (!closed) set({ requests: duringRead.reduce(upsertRequest, mergeList(state.requests, fresh)) });
      })
      .catch((e: unknown) => {
        if (typeof e === "object" && e && "status" in e && (e as { status: number }).status === 401) unauthorized();
        /* anything else is transient: the next read tries again */
      })
      .finally(() => {
        reading = false;
        duringRead = [];
      });
  }

  function armStale(ws: StaffSocket) {
    clearTimeout(staleTimer);
    staleTimer = setTimeout(() => down(ws), staleMs);
  }

  function down(ws: StaffSocket) {
    if (socket !== ws) return;
    detach(ws);
    socket = null;
    ready = false;
    clearTimeout(staleTimer);
    if (closed) return;
    set({ status: "offline" });
    reconnectTimer = setTimeout(connect, backoff);
    backoff = Math.min(backoff * 2, maxBackoff);
    if (!pollTimer) pollTimer = setInterval(read, pollMs);
  }

  function connect() {
    if (closed) return;
    const ws = makeSocket(url);
    socket = ws;
    ws.onopen = () => {
      if (socket !== ws) return;
      ws.send(JSON.stringify({ type: "auth", key: opts.key }));
      armStale(ws);
    };
    ws.onmessage = (ev) => {
      if (socket !== ws) return;
      armStale(ws);
      const msg = parse(ev.data);
      if (!msg) return;
      if (msg.type === "ready") {
        ready = true;
        backoff = minBackoff;
        clearInterval(pollTimer);
        pollTimer = undefined;
        set({ status: "live" });
        read();
      } else if ((msg.type === "request.created" || msg.type === "request.updated") && msg.request && ready) {
        if (reading) duringRead.push(msg.request);
        set({ requests: upsertRequest(state.requests, msg.request) });
      }
    };
    ws.onclose = (ev) => {
      if (socket !== ws) return;
      const code = (ev as { code?: number } | undefined)?.code;
      if (code === POLICY_VIOLATION && !ready) return unauthorized();
      down(ws);
    };
    ws.onerror = () => down(ws);
  }

  opts.onChange(state);
  connect();

  return {
    close: stop,
    refresh: read,
  };
}
