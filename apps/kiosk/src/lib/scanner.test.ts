import { describe, expect, it } from "vitest";
import { parseProductCode } from "./scanner";

const ID = "3f2b8c1e-9d4a-4e7b-8a21-5c6d7e8f9a0b";

describe("parseProductCode", () => {
  it("accepts a bare id, any case, with spaces around it", () => {
    expect(parseProductCode(ID)).toBe(ID);
    expect(parseProductCode(`  ${ID.toUpperCase()}\n`)).toBe(ID);
  });

  it("finds the id inside a URL or a prefixed code", () => {
    expect(parseProductCode(`https://shop.example/p/${ID}?ref=tag`)).toBe(ID);
    expect(parseProductCode(`tryon:product:${ID}`)).toBe(ID);
  });

  it("returns null when there is no id", () => {
    for (const text of ["", "hello", "1234567890123", "3f2b8c1e-9d4a-4e7b-8a21", "https://example.com"]) {
      expect(parseProductCode(text)).toBeNull();
    }
  });

  it("takes the first id when a code carries two", () => {
    expect(parseProductCode(`${ID} 00000000-0000-0000-0000-000000000000`)).toBe(ID);
  });
});
