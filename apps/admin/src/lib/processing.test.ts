import { describe, expect, it } from "vitest";
import { isBusy } from "./processing";

describe("isBusy", () => {
  it("is true only while queued or processing", () => {
    expect(isBusy({ processing_status: "queued" })).toBe(true);
    expect(isBusy({ processing_status: "processing" })).toBe(true);
    for (const s of ["idle", "done", "failed"] as const) expect(isBusy({ processing_status: s })).toBe(false);
  });
});
