import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createStaffFeed, mergeList, type StaffFeedState, type StaffSocket, upsertRequest } from "./staffFeed";
import type { StaffRequest } from "./types";

const req = (id: string, over: Partial<StaffRequest> = {}): StaffRequest => ({
  id,
  session_id: "s",
  product_id: "p",
  product_name: `Item ${id}`,
  size: "M",
  color: null,
  status: "open",
  created_at: `2026-01-01T10:00:0${id}Z`,
  updated_at: `2026-01-01T10:00:0${id}Z`,
  ...over,
});

describe("upsertRequest", () => {
  it("adds in order of age, replaces by id and drops done", () => {
    let list = upsertRequest([], req("2"));
    list = upsertRequest(list, req("1"));
    expect(list.map((r) => r.id)).toEqual(["1", "2"]);
    list = upsertRequest(list, req("1", { status: "bringing", updated_at: "2026-01-01T10:05:00Z" }));
    expect(list.find((r) => r.id === "1")?.status).toBe("bringing");
    list = upsertRequest(list, req("1", { status: "done", updated_at: "2026-01-01T10:06:00Z" }));
    expect(list.map((r) => r.id)).toEqual(["2"]);
  });

  it("ignores an older copy of a request", () => {
    const newer = req("1", { status: "bringing", updated_at: "2026-01-01T10:05:00Z" });
    const list = [newer];
    expect(upsertRequest(list, req("1"))).toBe(list);
  });
});

describe("mergeList", () => {
  it("keeps a local request that is newer than the fresh read", () => {
    const local = [req("1", { status: "bringing", updated_at: "2026-01-01T10:05:00Z" })];
    const merged = mergeList(local, [req("1"), req("2")]);
    expect(merged.map((r) => [r.id, r.status])).toEqual([["1", "bringing"], ["2", "open"]]);
  });

  it("drops requests the server no longer lists", () => {
    expect(mergeList([req("1")], [req("2")]).map((r) => r.id)).toEqual(["2"]);
  });
});

class FakeSocket implements StaffSocket {
  static all: FakeSocket[] = [];
  onopen: StaffSocket["onopen"] = null;
  onmessage: StaffSocket["onmessage"] = null;
  onclose: StaffSocket["onclose"] = null;
  onerror: StaffSocket["onerror"] = null;
  sent: string[] = [];
  closed = false;
  constructor(public url: string) {
    FakeSocket.all.push(this);
  }
  send(d: string) {
    this.sent.push(d);
  }
  close() {
    this.closed = true;
  }
  open() {
    this.onopen?.();
  }
  say(msg: object) {
    this.onmessage?.({ data: JSON.stringify(msg) });
  }
  drop(code = 1006) {
    this.onclose?.({ code });
  }
}
const last = () => FakeSocket.all[FakeSocket.all.length - 1];

describe("createStaffFeed", () => {
  let states: StaffFeedState[];
  let fetchList: ReturnType<typeof vi.fn>;
  const start = (extra = {}) =>
    createStaffFeed({
      wsUrl: "ws://api.test",
      key: "k1",
      fetchList: fetchList as unknown as () => Promise<StaffRequest[]>,
      onChange: (s) => states.push(s),
      createSocket: (u) => new FakeSocket(u),
      ...extra,
    });
  const now = () => states[states.length - 1];

  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.all = [];
    states = [];
    fetchList = vi.fn().mockResolvedValue([req("1")]);
  });
  afterEach(() => vi.useRealTimers());

  it("authenticates first, and reads the list only after the server says ready", async () => {
    const feed = start();
    expect(last().url).toBe("ws://api.test/ws/staff");
    last().open();
    expect(JSON.parse(last().sent[0])).toEqual({ type: "auth", key: "k1" });
    expect(fetchList).not.toHaveBeenCalled();
    last().say({ type: "ready" });
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchList).toHaveBeenCalledTimes(1);
    expect(now().status).toBe("live");
    expect(now().requests.map((r) => r.id)).toEqual(["1"]);
    feed.close();
  });

  it("applies created and updated events live", async () => {
    const feed = start();
    last().open();
    last().say({ type: "ready" });
    await vi.advanceTimersByTimeAsync(0);
    last().say({ type: "request.created", request: req("2") });
    expect(now().requests.map((r) => r.id)).toEqual(["1", "2"]);
    last().say({ type: "request.updated", request: req("1", { status: "bringing", updated_at: "2026-01-01T10:09:00Z" }) });
    expect(now().requests.find((r) => r.id === "1")?.status).toBe("bringing");
    last().say({ type: "request.updated", request: req("1", { status: "done", updated_at: "2026-01-01T10:10:00Z" }) });
    expect(now().requests.map((r) => r.id)).toEqual(["2"]);
    last().say({ type: "ping" });
    expect(now().requests.map((r) => r.id)).toEqual(["2"]);
    feed.close();
  });

  it("reconnects with exponential backoff, polls while down, and re-reads on ready", async () => {
    const feed = start({ reconnectMinMs: 500, reconnectMaxMs: 2000, pollIntervalMs: 3000 });
    last().open();
    last().say({ type: "ready" });
    await vi.advanceTimersByTimeAsync(0);
    expect(FakeSocket.all).toHaveLength(1);

    last().drop();
    expect(now().status).toBe("offline");
    await vi.advanceTimersByTimeAsync(499);
    expect(FakeSocket.all).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.all).toHaveLength(2);

    last().drop(); // never opened: next wait is doubled
    await vi.advanceTimersByTimeAsync(999);
    expect(FakeSocket.all).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(FakeSocket.all).toHaveLength(3);

    const before = fetchList.mock.calls.length;
    await vi.advanceTimersByTimeAsync(3000); // polling while offline
    expect(fetchList.mock.calls.length).toBeGreaterThan(before);

    last().drop(); // 1000 -> 2000 (capped)
    await vi.advanceTimersByTimeAsync(2000);
    expect(FakeSocket.all).toHaveLength(4);

    last().open();
    last().say({ type: "ready" });
    await vi.advanceTimersByTimeAsync(0);
    expect(now().status).toBe("live");
    const reads = fetchList.mock.calls.length;
    await vi.advanceTimersByTimeAsync(10_000); // polling stopped
    expect(fetchList.mock.calls.length).toBe(reads);
    feed.close();
  });

  it("does not retry when the server rejects the key", async () => {
    const feed = start();
    last().open();
    last().drop(1008);
    expect(now().status).toBe("unauthorized");
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeSocket.all).toHaveLength(1);
    expect(fetchList).not.toHaveBeenCalled();
    feed.close();
  });

  it("stops on a 401 from the list", async () => {
    fetchList.mockRejectedValue(Object.assign(new Error("no"), { status: 401 }));
    start();
    last().open();
    last().say({ type: "ready" });
    await vi.advanceTimersByTimeAsync(0);
    expect(now().status).toBe("unauthorized");
    expect(last().closed).toBe(true);
  });

  it("treats a silent socket as dead and replaces it", async () => {
    const feed = start({ staleAfterMs: 5000 });
    last().open();
    last().say({ type: "ready" });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(5000);
    expect(now().status).toBe("offline");
    await vi.advanceTimersByTimeAsync(500);
    expect(FakeSocket.all).toHaveLength(2);
    feed.close();
  });

  it("an event that arrives while the list read is in flight is not lost", async () => {
    let resolve!: (v: StaffRequest[]) => void;
    fetchList.mockReturnValue(new Promise((r) => (resolve = r)));
    const feed = start();
    last().open();
    last().say({ type: "ready" });
    last().say({ type: "request.created", request: req("3") });
    resolve([req("1")]);
    await vi.advanceTimersByTimeAsync(0);
    // The list was read after the subscription, so it already holds anything created before it; the event
    // for "3" is also applied, and a repeat is harmless.
    expect(now().requests.map((r) => r.id).sort()).toEqual(["1", "3"].sort());
    feed.close();
  });

  it("makes no more calls after close", async () => {
    const feed = start();
    last().open();
    feed.close();
    last().drop();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(FakeSocket.all).toHaveLength(1);
  });
});
