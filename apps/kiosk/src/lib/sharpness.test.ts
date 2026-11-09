import { describe, expect, it } from "vitest";
import { BestRecent, laplacianVariance, toGray } from "./sharpness";

/** A checkerboard: lots of hard edges. */
function checker(size = 32, cell = 2): Float32Array {
  const g = new Float32Array(size * size);
  for (let y = 0; y < size; y++) for (let x = 0; x < size; x++) g[y * size + x] = ((x / cell) | 0) % 2 === ((y / cell) | 0) % 2 ? 230 : 25;
  return g;
}

/** A box blur, the way a defocused or moving subject smears edges. */
function blur(src: Float32Array, size: number, radius = 2): Float32Array {
  const out = new Float32Array(src.length);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      let sum = 0;
      let n = 0;
      for (let dy = -radius; dy <= radius; dy++)
        for (let dx = -radius; dx <= radius; dx++) {
          const yy = y + dy;
          const xx = x + dx;
          if (yy >= 0 && yy < size && xx >= 0 && xx < size) (sum += src[yy * size + xx]), n++;
        }
      out[y * size + x] = sum / n;
    }
  }
  return out;
}

describe("laplacianVariance", () => {
  it("is zero for a flat image", () => {
    expect(laplacianVariance(new Float32Array(32 * 32).fill(128), 32, 32)).toBe(0);
  });

  it("is zero for a smooth ramp, which has no second derivative", () => {
    const ramp = new Float32Array(32 * 32).map((_, i) => (i % 32) * 4);
    expect(laplacianVariance(ramp, 32, 32)).toBeCloseTo(0, 5);
  });

  it("scores a sharp image far above the same image blurred", () => {
    const sharp = checker();
    const soft = blur(sharp, 32, 1);
    const softer = blur(sharp, 32, 3);
    const [a, b, c] = [sharp, soft, softer].map((g) => laplacianVariance(g, 32, 32));
    expect(a).toBeGreaterThan(b * 3);
    expect(b).toBeGreaterThan(c);
  });

  it("sees edges in every direction, not just across the image", () => {
    const stripes = new Float32Array(32 * 32).map((_, i) => (((i / 32) | 0) % 2 ? 230 : 25)); // rows alternate: edges run sideways
    const columns = new Float32Array(32 * 32).map((_, i) => ((i % 32) % 2 ? 230 : 25)); // columns alternate
    expect(laplacianVariance(stripes, 32, 32)).toBeGreaterThan(1000);
    expect(laplacianVariance(columns, 32, 32)).toBeGreaterThan(1000);
    expect(laplacianVariance(stripes, 32, 32)).toBeCloseTo(laplacianVariance(columns, 32, 32), 0);
  });

  it("does not depend on overall brightness", () => {
    const base = checker();
    const brighter = base.map((v) => v * 0.5 + 100);
    const dim = base.map((v) => v * 0.5);
    expect(laplacianVariance(brighter, 32, 32)).toBeCloseTo(laplacianVariance(dim, 32, 32), 3); // an offset changes nothing
  });

  it("handles images too small to have an interior", () => {
    expect(laplacianVariance(new Float32Array(4), 2, 2)).toBe(0);
    expect(laplacianVariance(new Float32Array(0), 0, 0)).toBe(0);
  });
});

describe("toGray", () => {
  it("weights green most and blue least", () => {
    const px = (r: number, g: number, b: number) => toGray(new Uint8ClampedArray([r, g, b, 255]), 1, 1)[0];
    expect(px(255, 0, 0)).toBeCloseTo(76.2, 0);
    expect(px(0, 255, 0)).toBeCloseTo(149.7, 0);
    expect(px(0, 0, 255)).toBeCloseTo(29.1, 0);
    expect(px(255, 255, 255)).toBeCloseTo(255, 0);
  });

  it("converts every pixel", () => {
    const rgba = new Uint8ClampedArray([10, 10, 10, 255, 200, 200, 200, 255]);
    expect(Array.from(toGray(rgba, 2, 1)).map(Math.round)).toEqual([10, 200]);
  });
});

describe("BestRecent", () => {
  it("picks the sharpest of the last five frames", () => {
    const ring = new BestRecent<string>(5);
    ["a", "b", "c", "d", "e"].forEach((f, i) => ring.push(f, [10, 90, 40, 30, 20][i]));
    expect(ring.best()).toBe("b");
  });

  it("forgets frames older than the last five and gives them back to be released", () => {
    const ring = new BestRecent<string>(5);
    const dropped: string[] = [];
    ["sharp-but-old", "b", "c", "d", "e", "f"].forEach((f, i) => {
      const gone = ring.push(f, i === 0 ? 1000 : i);
      if (gone) dropped.push(gone);
    });
    expect(dropped).toEqual(["sharp-but-old"]);
    expect(ring.best()).toBe("f"); // the old sharp frame no longer counts
    expect(ring.size).toBe(5);
  });

  it("prefers the most recent of equally sharp frames", () => {
    const ring = new BestRecent<string>(3);
    ring.push("first", 5);
    ring.push("second", 5);
    expect(ring.best()).toBe("second");
  });

  it("is empty at the start and after clearing, which returns what it held", () => {
    const ring = new BestRecent<number>(3);
    expect(ring.best()).toBeUndefined();
    ring.push(1, 1);
    ring.push(2, 2);
    expect(ring.clear()).toEqual([1, 2]);
    expect(ring.best()).toBeUndefined();
    expect(ring.size).toBe(0);
  });
});
