import { describe, expect, it } from "vitest";
import { formatRate } from "./analytics";

describe("formatRate", () => {
  it("shows a percentage with one decimal", () => {
    expect(formatRate(0)).toBe("0.0%");
    expect(formatRate(0.42857)).toBe("42.9%");
    expect(formatRate(1)).toBe("100.0%");
  });
  it("shows a dash when there is nothing to divide", () => {
    expect(formatRate(null)).toBe("–");
  });
});
