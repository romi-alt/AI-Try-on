import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { sentryOptions } from "./sentryOptions";
import { redactDeep, redactText, scrubBreadcrumb, scrubEvent } from "./sentryScrub";

// A 240x320 JPEG, base64 encoded: what a captured photo looks like if it ever ended up in a string.
const PHOTO = "/9j/4AAQSkZJRgABAQEASABIAAD/" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6".repeat(40);

describe("redactText", () => {
  it("removes photos in every form they could arrive in", () => {
    for (const text of [PHOTO, `data:image/jpeg;base64,${PHOTO}`, `{"image":"${PHOTO}"}`, PHOTO.slice(0, 300)]) {
      const out = redactText(text);
      expect(out).not.toContain("/9j/");
      expect(out).not.toContain("A1b2C3d4E5f6");
    }
  });

  it("removes the object URL of a captured photo", () => {
    expect(redactText("img src=blob:http://localhost:3000/3f2a9c1e-7b1d-4c55-9a39-2f6d3c1b8e44 failed")).toBe(
      "img src=blob:[removed] failed",
    );
  });

  it("removes signatures from signed links but keeps the rest", () => {
    const out = redactText("https://b.example/results/s/j.webp?X-Amz-Expires=3600&X-Amz-Signature=deadbeef&X-Amz-Credential=AKIA");
    expect(out).not.toContain("deadbeef");
    expect(out).not.toContain("AKIA");
    expect(out).toContain("results/s/j.webp");
    expect(out).toContain("X-Amz-Expires=3600");
  });

  it("masks the mobile-page code, which is a credential", () => {
    expect(redactText("https://mirror.example/m/K7TQ4M2X?x=1")).toBe("https://mirror.example/m/[code]?x=1");
  });

  it("leaves ordinary text alone", () => {
    const text = "Failed to load product 3f2a9c1e-7b1d-4c55-9a39-2f6d3c1b8e44 (HTTP 404) at /catalog?page=2";
    expect(redactText(text)).toBe(text);
  });
});

describe("redactDeep", () => {
  it("cleans nested values and replaces binary data by its size", () => {
    const out = redactDeep({ a: [PHOTO, { b: "ok" }], file: new Blob([new Uint8Array(10)]), n: 3, buf: new ArrayBuffer(8) });
    expect(JSON.stringify(out)).not.toContain("/9j/");
    expect(out.file).toBe("<10 bytes>");
    expect(out.buf).toBe("<8 bytes>");
    expect(out.n).toBe(3);
    expect(out.a[1]).toEqual({ b: "ok" });
  });

  it("truncates absurdly long strings", () => {
    expect(redactDeep("word ".repeat(1000)).length).toBeLessThan(2100);
  });

  it("does not loop forever on a cyclic-looking deep structure", () => {
    let deep: Record<string, unknown> = { v: "x" };
    for (let i = 0; i < 50; i++) deep = { child: deep };
    expect(() => redactDeep(deep)).not.toThrow();
  });
});

describe("scrubEvent", () => {
  const event = () => ({
    message: `upload failed data:image/jpeg;base64,${PHOTO}`,
    user: { ip_address: "203.0.113.9", id: "u1" },
    request: { url: "https://x/m/K7TQ4M2X", cookies: { a: "b" }, data: { file: PHOTO }, headers: { "X-Admin-Key": "k" }, query_string: "a=b" },
    exception: { values: [{ type: "Error", value: `bad ${PHOTO}`, stacktrace: { frames: [{ function: "f", vars: { img: PHOTO } }] } }] },
    breadcrumbs: [{ category: "fetch", data: { url: "https://b/x.webp?X-Amz-Signature=zzz" } }],
  });

  it("removes request data, headers, cookies, users and stack-frame variables", () => {
    const out = scrubEvent(event());
    expect(out).not.toHaveProperty("user");
    expect(out.request).toEqual({ url: "https://x/m/[code]" });
    expect(out.exception.values[0].stacktrace.frames[0]).toEqual({ function: "f" });
  });

  it("leaves no photo, signature, key or code anywhere in the event", () => {
    const text = JSON.stringify(scrubEvent(event()));
    for (const secret of ["/9j/", "A1b2C3d4E5f6", "zzz", "K7TQ4M2X", "203.0.113.9"]) expect(text).not.toContain(secret);
    expect(text).toContain("Error"); // still useful for debugging
  });

  it("scrubs breadcrumbs too", () => {
    expect(JSON.stringify(scrubBreadcrumb({ message: `x ${PHOTO}` }))).not.toContain("/9j/");
  });
});

describe("sentryOptions", () => {
  it("is switched off without a DSN", () => {
    expect(sentryOptions(undefined).enabled).toBe(false);
    expect(sentryOptions("https://k@o1.ingest.sentry.io/1").enabled).toBe(true);
  });

  it("never records the screen, never sends personal data and adds no trace headers to API calls", () => {
    const o = sentryOptions("https://k@o1.ingest.sentry.io/1") as Record<string, unknown>;
    expect(o.sendDefaultPii).toBe(false);
    expect(o.tracePropagationTargets).toEqual([]);
    for (const replay of ["replaysSessionSampleRate", "replaysOnErrorSampleRate", "integrations"]) expect(o[replay]).toBeUndefined();
  });

  it("wires the scrubbers into every hook", () => {
    const o = sentryOptions("https://k@o1.ingest.sentry.io/1");
    expect(JSON.stringify(o.beforeSend({ message: PHOTO }))).not.toContain("/9j/");
    expect(JSON.stringify(o.beforeSendTransaction({ message: PHOTO }))).not.toContain("/9j/");
    expect(JSON.stringify(o.beforeBreadcrumb({ message: PHOTO }))).not.toContain("/9j/");
  });
});
