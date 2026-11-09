import { describe, expect, it } from "vitest";
import { hashPassword, verifyPassword } from "./password";

describe("passwords", () => {
  it("accepts the right password and refuses a wrong one", () => {
    const h = hashPassword("correct horse");
    expect(verifyPassword("correct horse", h)).toBe(true);
    expect(verifyPassword("correct horsf", h)).toBe(false);
    expect(verifyPassword("", h)).toBe(false);
  });
  it("salts, so the same password hashes differently", () => {
    expect(hashPassword("x")).not.toBe(hashPassword("x"));
  });
  it("never matches or throws on a malformed hash", () => {
    for (const bad of ["", "plain", "scrypt:", "scrypt:zz:zz", "scrypt:00:00", "bcrypt:aa:bb", "scrypt:aa:" + "ab".repeat(64) + ":extra"]) {
      expect(verifyPassword("x", bad)).toBe(false);
    }
  });
  it("is stable for a fixed salt (the format the CLI prints)", () => {
    const salt = Buffer.alloc(16, 7);
    expect(hashPassword("pw", salt)).toBe(hashPassword("pw", salt));
    expect(hashPassword("pw", salt).startsWith(`scrypt:${"07".repeat(16)}:`)).toBe(true);
  });
});
