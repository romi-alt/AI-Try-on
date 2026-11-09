import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { type Connectivity, type ConnectivityOptions, createConnectivityMonitor } from "./connectivity";

type Listener = () => void;

function setup(overrides: Partial<ConnectivityOptions> = {}) {
  const changes: Connectivity[] = [];
  const results: boolean[] = [];
  let calls = 0;
  const listeners: Record<string, Listener[]> = { online: [], offline: [] };
  let browserOnline = true;
  const monitor = createConnectivityMonitor({
    ping: async () => {
      calls++;
      return results.length ? (results.shift() as boolean) : true;
    },
    onChange: (s) => changes.push(s),
    isBrowserOnline: () => browserOnline,
    listen: (type, handler) => {
      listeners[type].push(handler);
      return () => (listeners[type] = listeners[type].filter((h) => h !== handler));
    },
    ...overrides,
  });
  return {
    monitor,
    changes,
    results,
    calls: () => calls,
    fire: (type: "online" | "offline") => listeners[type].forEach((h) => h()),
    setBrowserOnline: (v: boolean) => (browserOnline = v),
    listenerCount: () => listeners.online.length + listeners.offline.length,
  };
}

describe("connectivity monitor", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("starts online and checks straight away, then every 15 s", async () => {
    const t = setup();
    t.monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(t.calls()).toBe(1);
    await vi.advanceTimersByTimeAsync(15_000);
    expect(t.calls()).toBe(2);
    expect(t.changes).toEqual([]); // no transitions, no noise
    t.monitor.stop();
  });

  it("does not call one failed check an outage; it looks again soon", async () => {
    const t = setup();
    t.results.push(false, true);
    t.monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    expect(t.monitor.state()).toBe("online");
    await vi.advanceTimersByTimeAsync(1_500);
    expect(t.calls()).toBe(2);
    expect(t.changes).toEqual([]);
    t.monitor.stop();
  });

  it("goes offline after two failures in a row, then back online on the first success", async () => {
    const t = setup();
    t.results.push(false, false, false, true);
    t.monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1_500);
    expect(t.changes).toEqual(["offline"]);
    await vi.advanceTimersByTimeAsync(3_000); // still failing
    expect(t.monitor.state()).toBe("offline");
    await vi.advanceTimersByTimeAsync(4_500); // backed off to 4.5 s, now succeeds
    expect(t.changes).toEqual(["offline", "online"]);
    t.monitor.stop();
  });

  it("backs off while offline but never beyond 10 s", async () => {
    const t = setup({ maxOfflineIntervalMs: 10_000 });
    t.results.push(...Array(40).fill(false));
    t.monitor.start();
    await vi.advanceTimersByTimeAsync(60_000);
    const early = t.calls();
    await vi.advanceTimersByTimeAsync(60_000);
    const perMinute = t.calls() - early;
    expect(perMinute).toBeGreaterThanOrEqual(5);
    expect(perMinute).toBeLessThanOrEqual(8); // about one every 10 s, not one every 3 s
    t.monitor.stop();
  });

  it("goes offline at once when the browser says so, and checks as soon as it says online", async () => {
    const t = setup();
    t.monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    t.setBrowserOnline(false);
    t.fire("offline");
    expect(t.changes).toEqual(["offline"]);
    t.setBrowserOnline(true);
    const before = t.calls();
    t.fire("online");
    await vi.advanceTimersByTimeAsync(0);
    expect(t.calls()).toBe(before + 1);
    expect(t.changes).toEqual(["offline", "online"]);
    t.monitor.stop();
  });

  it("treats a check that never answers as a failure", async () => {
    const t = setup({ ping: () => new Promise<boolean>(() => {}), timeoutMs: 1_000 });
    t.monitor.start();
    await vi.advanceTimersByTimeAsync(1_000 + 1_500 + 1_000);
    expect(t.changes).toEqual(["offline"]);
    t.monitor.stop();
  });

  it("treats a check that throws as a failure", async () => {
    const t = setup({ ping: async () => { throw new TypeError("Failed to fetch"); } });
    t.monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(1_500);
    expect(t.changes).toEqual(["offline"]);
    t.monitor.stop();
  });

  it("nudge() checks now, but never runs two checks at once", async () => {
    let release: (v: boolean) => void = () => {};
    let calls = 0;
    const t = setup({ ping: () => { calls++; return new Promise<boolean>((r) => (release = r)); } });
    t.monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    t.monitor.nudge();
    t.monitor.nudge();
    expect(calls).toBe(1);
    release(true);
    await vi.advanceTimersByTimeAsync(0);
    t.monitor.nudge();
    expect(calls).toBe(2);
    t.monitor.stop();
  });

  it("stop() ends the timers and the listeners", async () => {
    const t = setup();
    t.monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    t.monitor.stop();
    const calls = t.calls();
    await vi.advanceTimersByTimeAsync(120_000);
    expect(t.calls()).toBe(calls);
    expect(t.listenerCount()).toBe(0);
    t.fire("offline");
    expect(t.changes).toEqual([]);
  });

  it("a late answer after stop() changes nothing", async () => {
    let release: (v: boolean) => void = () => {};
    const t = setup({ ping: () => new Promise<boolean>((r) => (release = r)) });
    t.monitor.start();
    await vi.advanceTimersByTimeAsync(0);
    t.monitor.stop();
    release(false);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(t.changes).toEqual([]);
  });
});
