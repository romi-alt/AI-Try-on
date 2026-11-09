import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createIdleTimer, isIdleTrackedPhase, type IdleOptions } from "./idleTimer";
import { parseSeconds } from "./config";

const WARN = 60_000;
const GRACE = 15_000;

let calls: { warn: number; resume: number; expire: number; ticks: number[] };

function make(over: Partial<IdleOptions> = {}) {
  return createIdleTimer({
    warnAfterMs: WARN,
    graceMs: GRACE,
    onWarn: () => calls.warn++,
    onResume: () => calls.resume++,
    onTick: (s) => calls.ticks.push(s),
    onExpire: () => calls.expire++,
    ...over,
  });
}
const advance = (ms: number) => vi.advanceTimersByTime(ms);

beforeEach(() => {
  vi.useFakeTimers();
  calls = { warn: 0, resume: 0, expire: 0, ticks: [] };
});
afterEach(() => vi.useRealTimers());

describe("the idle sequence", () => {
  it("is quiet for the first minute, then warns once", () => {
    const t = make();
    t.start();
    advance(WARN - 500);
    expect(calls.warn).toBe(0);
    expect(t.state).toBe("active");

    advance(1000);
    expect(calls.warn).toBe(1);
    expect(t.state).toBe("warning");
    advance(5000);
    expect(calls.warn).toBe(1); // not repeated
  });

  it("counts the grace period down one second at a time, then expires once", () => {
    const t = make();
    t.start();
    advance(WARN + GRACE + 5000);

    expect(calls.ticks).toEqual(Array.from({ length: 15 }, (_, i) => 15 - i)); // 15 ... 1, then it expires
    expect(calls.expire).toBe(1);
    expect(t.state).toBe("stopped");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not expire before the grace period is over", () => {
    make().start();
    advance(WARN + GRACE - 500);
    expect(calls.expire).toBe(0);
  });

  it("lets the callback see a stopped timer and start a new one", () => {
    let t!: ReturnType<typeof make>;
    t = make({
      onExpire: () => {
        calls.expire++;
        expect(t.state).toBe("stopped");
        t.start();
      },
    });
    t.start();
    advance(WARN + GRACE);
    expect(calls.expire).toBe(1);
    expect(t.state).toBe("active"); // restarted from scratch
    advance(WARN - 500);
    expect(calls.warn).toBe(1); // only the first round's warning so far
  });
});

describe("input before the warning", () => {
  it("restarts the full period (a confirm counts too)", () => {
    const t = make();
    t.start();
    advance(50_000);
    t.activity("confirm");
    advance(WARN - 500);
    expect(calls.warn).toBe(0);
    advance(1000);
    expect(calls.warn).toBe(1);
  });

  it("counts presence too (a mouse move, a press: somebody is there)", () => {
    const t = make();
    t.start();
    advance(50_000);
    t.activity("presence");
    advance(WARN - 500);
    expect(calls.warn).toBe(0);
  });

  it("copes with a flood of mouse moves", () => {
    const t = make();
    t.start();
    for (let i = 0; i < 500; i++) {
      advance(10);
      t.activity("presence");
    }
    expect(vi.getTimerCount()).toBe(1); // still one interval, nothing piled up
    advance(WARN - 500);
    expect(calls.warn).toBe(0);
  });
});

describe("the warning", () => {
  function warned() {
    const t = make();
    t.start();
    advance(WARN + 100);
    expect(t.state).toBe("warning");
    return t;
  }

  it("ignores presence, so a nudged mouse or a stray press cannot keep an abandoned screen alive", () => {
    const t = warned();
    advance(3000);
    t.activity("presence");
    t.activity("presence");
    expect(t.state).toBe("warning");
    advance(GRACE);
    expect(calls.expire).toBe(1);
  });

  it("is dismissed by an explicit confirm, which restarts the full period", () => {
    const t = warned();
    advance(5000);
    t.activity("confirm");

    expect(t.state).toBe("active");
    expect(calls.resume).toBe(1);
    advance(GRACE + 5000);
    expect(calls.expire).toBe(0); // the old deadline no longer applies
    advance(WARN - GRACE - 5000 - 500);
    expect(calls.warn).toBe(1);
    advance(1000);
    expect(calls.warn).toBe(2); // warns again after a fresh full period
  });

  it("starts the countdown from the top the second time", () => {
    const t = warned();
    t.activity("confirm");
    calls.ticks.length = 0;
    advance(WARN + 500); // the timer checks every 250ms, so allow for the tick after the deadline
    expect(calls.ticks[0]).toBe(15);
  });
});

describe("stopping and starting", () => {
  it("ignores input while stopped", () => {
    const t = make();
    t.activity("confirm");
    t.activity("presence");
    expect(t.state).toBe("stopped");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stop() cancels everything and nothing fires afterwards", () => {
    const t = make();
    t.start();
    advance(WARN + 3000);
    t.stop();
    expect(vi.getTimerCount()).toBe(0);
    advance(10 * WARN);
    expect(calls.expire).toBe(0);
    expect(calls.warn).toBe(1);
  });

  it("starting again counts from the start", () => {
    const t = make();
    t.start();
    advance(50_000);
    t.stop();
    t.start();
    advance(WARN - 500);
    expect(calls.warn).toBe(0);
  });

  it("start() twice does not create two timers", () => {
    const t = make();
    t.start();
    t.start();
    expect(vi.getTimerCount()).toBe(1);
  });

  it("stop() when never started is harmless", () => {
    const t = make();
    expect(() => t.stop()).not.toThrow();
  });
});

describe("the clock, not the number of ticks", () => {
  it("expires at once, without a warning, if the machine slept past the deadline", () => {
    const t = make();
    t.start();
    advance(10_000);
    vi.setSystemTime(Date.now() + 10 * 60_000); // laptop lid closed, then reopened
    advance(250);

    expect(calls.expire).toBe(1);
    expect(calls.warn).toBe(0);
    expect(t.state).toBe("stopped");
  });

  it("shows the real time left if it wakes inside the grace period", () => {
    const t = make();
    t.start();
    vi.setSystemTime(Date.now() + WARN + 9_000);
    advance(250);
    expect(calls.warn).toBe(1);
    expect(calls.ticks.at(-1)).toBe(6);
  });
});

describe("configuration", () => {
  it("is off when the warning time is 0", () => {
    const t = make({ warnAfterMs: 0 });
    t.start();
    expect(t.state).toBe("stopped");
    expect(vi.getTimerCount()).toBe(0);
    advance(10 * WARN);
    expect(calls).toEqual({ warn: 0, resume: 0, expire: 0, ticks: [] });
  });

  it("expires straight away, with no warning, if there is no grace period", () => {
    make({ graceMs: 0 }).start();
    advance(WARN + 250);
    expect(calls.expire).toBe(1);
    expect(calls.warn).toBe(0);
  });

  it("reads seconds from the environment, falling back on anything unusable", () => {
    expect(parseSeconds("90", 60)).toBe(90);
    expect(parseSeconds("0", 60)).toBe(0); // 0 turns it off
    expect(parseSeconds("1.5", 60)).toBe(1.5);
    for (const bad of [undefined, "", "  ", "abc", "-5", "NaN", "Infinity"]) expect(parseSeconds(bad, 60), String(bad)).toBe(60);
  });
});

describe("which phases are timed", () => {
  it("times the screens a shopper can walk away from", () => {
    for (const p of ["consent", "browsing", "result", "error"]) expect(isIdleTrackedPhase(p), p).toBe(true);
  });
  it("does not time a shopper who is waiting for a try-on", () => {
    for (const p of ["starting", "countdown", "uploading", "working"]) expect(isIdleTrackedPhase(p), p).toBe(false);
  });
});
