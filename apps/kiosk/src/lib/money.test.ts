import { describe, expect, it } from "vitest";
import { discountPercent, formatPkr } from "./money";

describe("formatPkr", () => {
  it("formats whole rupees with thousands separators", () => {
    expect(formatPkr(4390)).toBe("Rs 4,390");
    expect(formatPkr(0)).toBe("Rs 0");
    expect(formatPkr(1250000)).toBe("Rs 1,250,000");
  });
});

describe("discountPercent", () => {
  it("rounds to a whole percent", () => {
    expect(discountPercent(5490, 4390)).toBe(20);
    expect(discountPercent(1000, 667)).toBe(33);
  });
  it("is 0 when there is no real discount", () => {
    expect(discountPercent(1000, null)).toBe(0);
    expect(discountPercent(1000, 1000)).toBe(0);
    expect(discountPercent(1000, 1200)).toBe(0);
    expect(discountPercent(0, 0)).toBe(0);
  });
});
