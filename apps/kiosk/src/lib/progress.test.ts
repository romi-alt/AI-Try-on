import { describe, expect, it } from "vitest";
import { clampPct, ringDash, stageLabel } from "./progress";

describe("clampPct", () => {
  it("keeps 0 to 100 as a whole number and clamps everything else", () => {
    expect([0, 1, 49.6, 100].map(clampPct)).toEqual([0, 1, 50, 100]);
    expect([-5, 130, Number.POSITIVE_INFINITY].map(clampPct)).toEqual([0, 100, 100]);
    expect([null, undefined, Number.NaN].map(clampPct)).toEqual([0, 0, 0]);
  });
});

describe("ringDash", () => {
  it("fills the share of the circle that is done", () => {
    expect(ringDash(0, 200)).toBe("0 200");
    expect(ringDash(25, 200)).toBe("50 200");
    expect(ringDash(100, 200)).toBe("200 200");
    expect(ringDash(250, 200)).toBe("200 200"); // never more than a full circle
    expect(ringDash(-10, 200)).toBe("0 200");
  });
});

describe("stageLabel", () => {
  it("describes the stage", () => {
    expect(stageLabel("uploading", 0)).toBe("Sending your photo");
    expect(stageLabel("working", 3)).toBe("Getting ready");
    expect(stageLabel("working", 40)).toBe("Dressing you up");
    expect(stageLabel("working", 95)).toBe("Adding the finishing touches");
  });
});
