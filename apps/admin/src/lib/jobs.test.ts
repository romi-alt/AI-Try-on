import { describe, expect, it } from "vitest";
import { formatDuration, linkExpired, productNames, shortId, signedUrlExpiry } from "./jobs";
import { validateImageFile } from "./images";
import { formatPkr } from "./money";

describe("jobs helpers", () => {
  it("shortens ids", () => expect(shortId("c55f54b8-6b80-49f8-aaf2-0815ae05cbd2")).toBe("c55f54b8"));

  it("formats how long a job took", () => {
    expect(formatDuration("2026-01-01T00:00:00Z", "2026-01-01T00:00:08Z")).toBe("8s");
    expect(formatDuration("2026-01-01T00:00:00Z", "2026-01-01T00:01:12Z")).toBe("1m 12s");
    expect(formatDuration("2026-01-01T00:00:00Z", "2026-01-01T00:00:00.400Z")).toBe("0s");
  });
  it("shows a dash for an impossible duration", () => {
    expect(formatDuration("2026-01-01T00:00:10Z", "2026-01-01T00:00:00Z")).toBe("-");
    expect(formatDuration("nonsense", "2026-01-01T00:00:00Z")).toBe("-");
  });

  it("names a job's products in order, and marks one that was deleted", () => {
    const names = new Map([["a", "Linen Camp Shirt"], ["b", "Wide-Leg Trouser"]]);
    expect(productNames(["b", "gone", "a"], names)).toEqual(["Wide-Leg Trouser", "(removed product)", "Linen Camp Shirt"]);
  });
});

describe("validateImageFile", () => {
  it("accepts PNG, JPEG and WebP", () => {
    for (const type of ["image/png", "image/jpeg", "image/webp"]) expect(validateImageFile({ type, size: 1000 })).toBeNull();
  });
  it("refuses other types", () => {
    for (const type of ["image/gif", "image/svg+xml", "application/pdf", ""]) expect(validateImageFile({ type, size: 1000 })).toMatch(/PNG, JPEG or WebP/);
  });
  it("refuses empty and oversized files", () => {
    expect(validateImageFile({ type: "image/png", size: 0 })).toMatch(/empty/);
    expect(validateImageFile({ type: "image/png", size: 10 * 1024 * 1024 + 1 })).toMatch(/10 MB/);
    expect(validateImageFile({ type: "image/png", size: 10 * 1024 * 1024 })).toBeNull();
  });
});

describe("formatPkr", () => {
  it("formats whole rupees", () => {
    expect(formatPkr(4390)).toBe("Rs 4,390");
    expect(formatPkr(0)).toBe("Rs 0");
  });
});

describe("signed result links", () => {
  const signed = (date: string, expires: string) =>
    `http://s3.test/bucket/results/x.webp?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Date=${date}&X-Amz-Expires=${expires}&X-Amz-Signature=abc`;

  it("reads when a presigned URL expires from the URL itself", () => {
    expect(signedUrlExpiry(signed("20261109T094600Z", "3600"))?.toISOString()).toBe("2026-11-09T10:46:00.000Z");
    expect(signedUrlExpiry(signed("20261109T094600Z", "60"))?.toISOString()).toBe("2026-11-09T09:47:00.000Z");
  });

  it("knows when a link has expired, whatever lifetime it was given", () => {
    const url = signed("20261109T094600Z", "3600");
    const at = (iso: string) => new Date(iso).getTime();
    expect(linkExpired(url, at("2026-11-09T10:45:59Z"))).toBe(false);
    expect(linkExpired(url, at("2026-11-09T10:46:00Z"))).toBe(true);
    expect(linkExpired(signed("20261109T094600Z", "86400"), at("2026-11-09T10:46:00Z"))).toBe(false);
  });

  it("treats anything that is not presigned as still valid", () => {
    expect(signedUrlExpiry("http://s3.test/bucket/results/x.webp")).toBeNull();
    expect(signedUrlExpiry("not a url")).toBeNull();
    expect(signedUrlExpiry(signed("garbage", "3600"))).toBeNull();
    expect(signedUrlExpiry(signed("20261109T094600Z", "0"))).toBeNull();
    expect(linkExpired("http://s3.test/x.webp")).toBe(false);
  });
});
