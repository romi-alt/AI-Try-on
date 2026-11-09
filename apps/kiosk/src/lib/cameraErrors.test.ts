import { describe, expect, it } from "vitest";
import { CAMERA_CONSTRAINTS, describeCameraError } from "./cameraErrors";

const err = (name: string) => Object.assign(new Error(name), { name });

describe("describeCameraError", () => {
  it("explains a blocked camera, a missing one, and one that is busy", () => {
    expect(describeCameraError(err("NotAllowedError"))).toMatch(/blocked/i);
    expect(describeCameraError(err("SecurityError"))).toMatch(/blocked/i);
    expect(describeCameraError(err("NotFoundError"))).toMatch(/no camera/i);
    expect(describeCameraError(err("NotReadableError"))).toMatch(/used by something else/i);
    expect(describeCameraError(err("AbortError"))).toMatch(/stopped/i);
  });

  it("has a plain fallback for anything else, including non-errors", () => {
    expect(describeCameraError(err("WeirdError"))).toMatch(/couldn't start/i);
    expect(describeCameraError("string")).toMatch(/couldn't start/i);
    expect(describeCameraError(null)).toMatch(/couldn't start/i);
    expect(describeCameraError(undefined)).toMatch(/couldn't start/i);
  });

  it("never shows the browser's own jargon", () => {
    for (const n of ["NotAllowedError", "NotFoundError", "NotReadableError", "OverconstrainedError"]) {
      expect(describeCameraError(err(n))).not.toMatch(/Error|constraint|getUserMedia|DOMException/);
    }
  });
});

describe("CAMERA_CONSTRAINTS", () => {
  it("prefers 1920x1080 without insisting on it, facing the shopper, with no microphone", () => {
    const v = CAMERA_CONSTRAINTS.video as MediaTrackConstraints;
    expect(v.width).toEqual({ ideal: 1920 });
    expect(v.height).toEqual({ ideal: 1080 });
    expect(v.facingMode).toBe("user");
    expect(CAMERA_CONSTRAINTS.audio).toBe(false);
    expect(JSON.stringify(v)).not.toMatch(/exact|min/); // a camera that cannot do Full HD must still start
  });
});
