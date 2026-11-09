import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSessionEvents, type SocketLike } from "./sessionEvents";
import type { JobState, JobUpdate } from "./types";

class FakeSocket implements SocketLike {
  static all: FakeSocket[] = [];
  onopen: SocketLike["onopen"] = null;
  onmessage: SocketLike["onmessage"] = null;
  onclose: SocketLike["onclose"] = null;
  onerror: SocketLike["onerror"] = null;
  closeCalls = 0;
  constructor(public url: string) {
    FakeSocket.all.push(this);
  }
  close() {
    this.closeCalls++;
  }
  open() {
    this.onopen?.();
  }
  send(msg: object) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  drop() {
    this.onclose?.();
  }
}

const J = "job-1";
const msg = (status: JobUpdate["status"], pct: number, extra: Partial<JobUpdate> = {}): JobUpdate => ({
  job: J,
  status,
  pct,
  ...extra,
});
const state = (u: JobUpdate): JobState => ({ ...u, updated_at: "2026-01-01T00:00:00Z" });

let fetchJob: ReturnType<typeof vi.fn<(id: string) => Promise<JobState>>>;
let updates: JobUpdate[];
const last = () => FakeSocket.all[FakeSocket.all.length - 1];

function start(options: Partial<Parameters<typeof createSessionEvents>[0]> = {}) {
  return createSessionEvents({
    sessionId: "sess-1",
    wsUrl: "ws://api.test",
    fetchJob,
    createSocket: (u) => new FakeSocket(u),
    pollIntervalMs: 2000,
    reconnectMinMs: 500,
    reconnectMaxMs: 4000,
    staleAfterMs: 60_000,
    ...options,
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  FakeSocket.all = [];
  updates = [];
  fetchJob = vi.fn(() => new Promise<JobState>(() => {})); // never answers unless a test says so
});
afterEach(() => vi.useRealTimers());

describe("connecting", () => {
  it("opens one socket for the session straight away", () => {
    start();
    expect(FakeSocket.all).toHaveLength(1);
    expect(last().url).toBe("ws://api.test/ws?session=sess-1");
  });

  it("encodes the session id in the URL", () => {
    start({ sessionId: "a b&c" });
    expect(last().url).toBe("ws://api.test/ws?session=a%20b%26c");
  });
});

describe("following a job over the socket", () => {
  it("delivers updates in order and stops at done", () => {
    const ev = start();
    ev.track(J, (u) => updates.push(u));
    last().open();

    last().send(msg("queued", 0));
    last().send(msg("processing", 0));
    last().send(msg("processing", 40));
    last().send(msg("done", 100, { url: "https://x/r.webp" }));
    last().send(msg("processing", 50)); // anything after done is ignored

    expect(updates.map((u) => [u.status, u.pct])).toEqual([
      ["queued", 0],
      ["processing", 0],
      ["processing", 40],
      ["done", 100],
    ]);
    expect(updates.at(-1)?.url).toBe("https://x/r.webp");
  });

  it("delivers failures with their message", () => {
    const ev = start();
    ev.track(J, (u) => updates.push(u));
    last().open();
    last().send(msg("failed", 30, { error: "We couldn't see your full body." }));
    expect(updates).toEqual([msg("failed", 30, { error: "We couldn't see your full body." })]);
  });

  it("ignores heartbeats, other jobs, junk and non-text frames", () => {
    const ev = start();
    ev.track(J, (u) => updates.push(u));
    last().open();

    last().send({ type: "ping" });
    last().send({ job: "someone-elses", status: "processing", pct: 99 });
    last().onmessage?.({ data: "not json" });
    last().onmessage?.({ data: new ArrayBuffer(4) });
    last().onmessage?.({ data: JSON.stringify([1, 2]) });
    last().send({ job: J, status: "processing" }); // no pct
    last().send(msg("processing", 10));

    expect(updates).toEqual([msg("processing", 10)]);
  });

  it("never moves a job backwards or repeats an update", () => {
    const ev = start();
    ev.track(J, (u) => updates.push(u));
    last().open();

    last().send(msg("processing", 50));
    last().send(msg("processing", 30)); // stale
    last().send(msg("processing", 50)); // repeat
    last().send(msg("queued", 0)); // older status
    last().send(msg("processing", 60));

    expect(updates.map((u) => u.pct)).toEqual([50, 60]);
  });

  it("keeps the socket open after a job finishes so the next one needs no reconnect", () => {
    const ev = start();
    ev.track(J, (u) => updates.push(u));
    last().open();
    last().send(msg("done", 100, { url: "u" }));

    expect(FakeSocket.all).toHaveLength(1);
    expect(last().closeCalls).toBe(0);

    const next: JobUpdate[] = [];
    ev.track("job-2", (u) => next.push(u));
    last().send({ job: "job-2", status: "processing", pct: 5 });
    expect(next).toHaveLength(1);
  });

  it("stops delivering after the returned untrack function is called", () => {
    const ev = start();
    const untrack = ev.track(J, (u) => updates.push(u));
    last().open();
    last().send(msg("processing", 10));
    untrack();
    last().send(msg("processing", 20));
    expect(updates.map((u) => u.pct)).toEqual([10]);
  });
});

describe("early messages", () => {
  it("replays what arrived before track() was called, in order", () => {
    const ev = start();
    last().open();
    last().send(msg("queued", 0)); // the POST /tryon response has not come back yet
    last().send(msg("processing", 0));
    last().send({ job: "other", status: "processing", pct: 70 });

    ev.track(J, (u) => updates.push(u));

    expect(updates.map((u) => [u.status, u.pct])).toEqual([
      ["queued", 0],
      ["processing", 0],
    ]);
  });

  it("replays an early done and then follows nothing further", () => {
    const ev = start();
    last().open();
    last().send(msg("done", 100, { url: "u" }));
    ev.track(J, (u) => updates.push(u));
    expect(updates.map((u) => u.status)).toEqual(["done"]);
    expect(vi.getTimerCount()).toBe(1); // only the stale-socket timer remains: nothing is being polled
  });

  it("bounds what it remembers", () => {
    const ev = start();
    last().open();
    for (let i = 0; i < 200; i++) last().send({ job: "noise", status: "processing", pct: i % 100 });
    expect(() => ev.track(J, () => {})).not.toThrow();
  });
});

describe("catching up from GET /jobs/{id}", () => {
  it("reads the current state when tracking starts and applies it", async () => {
    fetchJob.mockResolvedValue(state(msg("processing", 40)));
    const ev = start();
    last().open();

    ev.track(J, (u) => updates.push(u));
    await vi.advanceTimersByTimeAsync(0);

    expect(fetchJob).toHaveBeenCalledWith(J);
    expect(updates.map((u) => u.pct)).toEqual([40]);
  });

  it("reads it again after a reconnect, then carries on from the socket", async () => {
    const ev = start();
    ev.track(J, (u) => updates.push(u));
    last().open();
    last().send(msg("processing", 30));

    last().drop(); // network blip
    await vi.advanceTimersByTimeAsync(500);
    fetchJob.mockResolvedValue(state(msg("processing", 70))); // the job moved on while we were away
    last().open();
    await vi.advanceTimersByTimeAsync(0);
    last().send(msg("processing", 80));

    expect(updates.map((u) => u.pct)).toEqual([30, 70, 80]);
  });

  it("does not let a slow catch-up undo a newer socket message", async () => {
    let answer!: (s: JobState) => void;
    fetchJob.mockReturnValue(new Promise<JobState>((r) => (answer = r)));
    const ev = start();
    last().open();
    ev.track(J, (u) => updates.push(u));

    last().send(msg("processing", 60)); // arrives first
    answer(state(msg("processing", 20))); // the older read lands afterwards
    await vi.advanceTimersByTimeAsync(0);

    expect(updates.map((u) => u.pct)).toEqual([60]);
  });

  it("finishes from the catch-up alone when the job is already done", async () => {
    fetchJob.mockResolvedValue(state(msg("done", 100, { url: "https://x/r.webp" })));
    const ev = start();
    last().open();
    ev.track(J, (u) => updates.push(u));
    await vi.advanceTimersByTimeAsync(0);
    expect(updates).toEqual([msg("done", 100, { url: "https://x/r.webp" })]);
  });
});

describe("reconnecting", () => {
  it("backs off 500ms, 1s, 2s, 4s and stays at the cap, resetting once connected", async () => {
    start();
    const delays: number[] = [];
    for (let i = 0; i < 6; i++) {
      const before = FakeSocket.all.length;
      last().drop();
      let waited = 0;
      while (FakeSocket.all.length === before) {
        await vi.advanceTimersByTimeAsync(100);
        waited += 100;
      }
      delays.push(waited);
    }
    expect(delays).toEqual([500, 1000, 2000, 4000, 4000, 4000]);

    last().open(); // a successful connection resets the backoff
    last().drop();
    await vi.advanceTimersByTimeAsync(499);
    const n = FakeSocket.all.length;
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.all.length).toBe(n + 1);
  });

  it("treats an error like a close, once", async () => {
    start();
    last().onerror?.();
    last().onclose?.(); // browsers fire both; only one reconnect may follow
    await vi.advanceTimersByTimeAsync(10_000);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it("replaces a socket that has gone silent", async () => {
    start({ staleAfterMs: 60_000 });
    const first = last();
    first.open();
    await vi.advanceTimersByTimeAsync(59_000);
    first.send({ type: "ping" }); // a heartbeat proves it is alive and resets the clock
    await vi.advanceTimersByTimeAsync(59_000);
    expect(FakeSocket.all).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(first.closeCalls).toBe(1);
    await vi.advanceTimersByTimeAsync(500);
    expect(FakeSocket.all).toHaveLength(2);
  });

  it("ignores late events from a socket it has already replaced", async () => {
    const ev = start();
    ev.track(J, (u) => updates.push(u));
    const old = last();
    old.open();
    old.drop();
    await vi.advanceTimersByTimeAsync(500);
    last().open();

    old.send(msg("processing", 99)); // a ghost from the dead connection
    expect(updates).toEqual([]);
  });
});

describe("polling while the socket is down", () => {
  it("polls every interval until the job finishes, if the socket never connects", async () => {
    const answers = [msg("queued", 0), msg("processing", 30), msg("processing", 60), msg("done", 100, { url: "u" })];
    fetchJob.mockImplementation(async () => state(answers.shift() ?? msg("done", 100, { url: "u" })));
    const ev = start();
    last().drop(); // refused: never connects
    ev.track(J, (u) => updates.push(u));

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(2000);

    expect(updates.map((u) => [u.status, u.pct])).toEqual([
      ["queued", 0],
      ["processing", 30],
      ["processing", 60],
      ["done", 100],
    ]);
    const calls = fetchJob.mock.calls.length;
    await vi.advanceTimersByTimeAsync(20_000);
    expect(fetchJob.mock.calls.length).toBe(calls); // done: no more polling
  });

  it("stops polling once the socket is back", async () => {
    fetchJob.mockResolvedValue(state(msg("processing", 10)));
    const ev = start();
    last().drop();
    ev.track(J, (u) => updates.push(u));
    await vi.advanceTimersByTimeAsync(2000);
    const whileDown = fetchJob.mock.calls.length;
    expect(whileDown).toBeGreaterThan(1);

    await vi.advanceTimersByTimeAsync(500);
    last().open();
    await vi.advanceTimersByTimeAsync(0);
    const afterOpen = fetchJob.mock.calls.length; // one catch-up read on open
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetchJob.mock.calls.length).toBe(afterOpen);
  });

  it("does not poll while the socket is healthy", async () => {
    const ev = start();
    last().open();
    ev.track(J, () => {});
    await vi.advanceTimersByTimeAsync(0);
    const calls = fetchJob.mock.calls.length;
    last().send({ type: "ping" });
    await vi.advanceTimersByTimeAsync(30_000);
    expect(fetchJob.mock.calls.length).toBe(calls);
  });

  it("survives failing polls and keeps trying", async () => {
    fetchJob.mockRejectedValueOnce(new Error("offline")).mockRejectedValueOnce(new Error("offline"));
    fetchJob.mockResolvedValue(state(msg("done", 100, { url: "u" })));
    const ev = start();
    last().drop();
    ev.track(J, (u) => updates.push(u));

    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(2000);

    expect(updates.map((u) => u.status)).toEqual(["done"]);
  });

  it("a read that hangs forever does not stop later reads", async () => {
    // First read never answers (the default mock). Polling resumes once it is clearly stale...
    const ev = start();
    last().drop();
    ev.track(J, (u) => updates.push(u));
    fetchJob.mockResolvedValue(state(msg("processing", 25)));
    await vi.advanceTimersByTimeAsync(9_000);
    expect(fetchJob).toHaveBeenCalledTimes(1); // still waiting on the hung one
    await vi.advanceTimersByTimeAsync(3_000);
    expect(updates.map((u) => u.pct)).toEqual([25]);
  });

  it("never has two polls in flight at once", async () => {
    let inflight = 0;
    let peak = 0;
    fetchJob.mockImplementation(async () => {
      inflight++;
      peak = Math.max(peak, inflight);
      await new Promise((r) => setTimeout(r, 5000)); // slower than the poll interval
      inflight--;
      return state(msg("processing", 10));
    });
    const ev = start();
    last().drop();
    ev.track(J, () => {});
    await vi.advanceTimersByTimeAsync(20_000);
    expect(peak).toBe(1);
  });
});

describe("closing", () => {
  it("closes the socket, cancels every timer and stops reconnecting", async () => {
    const ev = start();
    ev.track(J, (u) => updates.push(u));
    const ws = last();
    ws.open();
    ws.drop();
    await vi.advanceTimersByTimeAsync(0);

    ev.close();

    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeSocket.all).toHaveLength(2 - 1); // no reconnect after close
    expect(updates).toEqual([]);
  });

  it("closes an open socket", () => {
    const ev = start();
    const ws = last();
    ws.open();
    ev.close();
    expect(ws.closeCalls).toBe(1);
    expect(vi.getTimerCount()).toBe(0);
    ws.send(msg("processing", 1)); // detached: nothing happens
  });

  it("is safe to close twice", () => {
    const ev = start();
    ev.close();
    expect(() => ev.close()).not.toThrow();
  });
});
