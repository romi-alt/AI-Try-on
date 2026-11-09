import { describe, expect, it } from "vitest";
import { createLoginLimiter } from "./loginLimiter";

describe("login limiter", () => {
  it("blocks after the allowed number of failures, until the oldest one ages out", () => {
    let t = 0;
    const l = createLoginLimiter(3, 60_000, () => t);
    for (let i = 0; i < 2; i++) l.fail("a");
    expect(l.blockedFor("a")).toBe(0);
    t = 10_000;
    l.fail("a");
    expect(l.blockedFor("a")).toBe(50);
    t = 59_999;
    expect(l.blockedFor("a")).toBeGreaterThan(0);
    t = 60_000; // the first two failures (at 0) have aged out
    expect(l.blockedFor("a")).toBe(0);
  });
  it("counts each email separately and forgets after a success", () => {
    const l = createLoginLimiter(2, 60_000, () => 0);
    l.fail("a");
    l.fail("a");
    expect(l.blockedFor("a")).toBeGreaterThan(0);
    expect(l.blockedFor("b")).toBe(0);
    l.succeed("a");
    expect(l.blockedFor("a")).toBe(0);
  });
});
