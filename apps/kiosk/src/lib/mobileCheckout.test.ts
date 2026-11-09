import { describe, expect, it } from "vitest";
import { ApiError } from "./api";
import { createCheckoutAttempts } from "./mobileCheckout";

const keys = () => {
  let n = 0;
  return () => `key-${++n}`;
};

describe("createCheckoutAttempts", () => {
  it("reuses the key until the outcome is known", () => {
    const a = createCheckoutAttempts(keys());
    expect(a.current()).toBe("key-1");
    a.failed(new ApiError(0, "Can't reach the server"));
    expect(a.current()).toBe("key-1");
    a.failed(new ApiError(503, "down"));
    expect(a.current()).toBe("key-1");
    a.failed(new Error("something odd"));
    expect(a.current()).toBe("key-1");
  });

  it("starts a fresh attempt after a definite refusal", () => {
    const a = createCheckoutAttempts(keys());
    expect(a.current()).toBe("key-1");
    a.failed(new ApiError(402, "The payment was declined"));
    expect(a.current()).toBe("key-2");
    a.failed(new ApiError(409, "Not enough stock"));
    expect(a.current()).toBe("key-3");
  });

  it("starts fresh after a reset", () => {
    const a = createCheckoutAttempts(keys());
    a.current();
    a.reset();
    expect(a.current()).toBe("key-2");
  });
});
