import { describe, expect, it } from "vitest";
import { centeredCrop } from "./capture";

describe("centeredCrop", () => {
  it("cuts a portrait slice from the middle of a landscape webcam frame", () => {
    expect(centeredCrop(1920, 1080)).toEqual({ sx: 555, sy: 0, sw: 810, sh: 1080 });
  });

  it("handles a 640x480 frame (4:3 is wider than 3:4)", () => {
    const c = centeredCrop(640, 480);
    expect(c).toEqual({ sx: 140, sy: 0, sw: 360, sh: 480 });
    expect(c.sw / c.sh).toBeCloseTo(0.75, 2);
  });

  it("trims the height of a frame that is already narrower than 3:4", () => {
    const c = centeredCrop(720, 1280);
    expect(c).toEqual({ sx: 0, sy: 160, sw: 720, sh: 960 });
  });

  it("keeps a frame that is exactly 3:4", () => {
    expect(centeredCrop(900, 1200)).toEqual({ sx: 0, sy: 0, sw: 900, sh: 1200 });
  });

  it("always stays inside the frame, whatever the input", () => {
    for (const [w, h] of [[1920, 1080], [1280, 720], [640, 480], [480, 640], [1080, 1920], [1000, 1000], [3840, 2160]]) {
      const { sx, sy, sw, sh } = centeredCrop(w, h);
      expect(sx).toBeGreaterThanOrEqual(0);
      expect(sy).toBeGreaterThanOrEqual(0);
      expect(sx + sw).toBeLessThanOrEqual(w);
      expect(sy + sh).toBeLessThanOrEqual(h);
      expect(sw / sh).toBeCloseTo(0.75, 1);
    }
  });

  it("supports other aspect ratios", () => {
    const c = centeredCrop(1920, 1080, 1);
    expect(c).toEqual({ sx: 420, sy: 0, sw: 1080, sh: 1080 });
  });
});
