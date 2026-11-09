/** Grey levels (0..255) from RGBA pixels, using the standard luma weights. */
export function toGray(rgba: Uint8ClampedArray | Uint8Array, width: number, height: number): Float32Array {
  const gray = new Float32Array(width * height);
  for (let i = 0, p = 0; i < gray.length; i++, p += 4) {
    gray[i] = 0.299 * rgba[p] + 0.587 * rgba[p + 1] + 0.114 * rgba[p + 2];
  }
  return gray;
}

/**
 * How sharp an image is: the variance of its Laplacian (the 4-neighbour second derivative). A blurred frame has few
 * strong edges, so its Laplacian is nearly flat and the variance is low; a crisp one scores high. Only comparable
 * between frames of the same size and scene, which is how it is used here (the last few frames of one capture).
 */
export function laplacianVariance(gray: ArrayLike<number>, width: number, height: number): number {
  if (width < 3 || height < 3) return 0;
  let sum = 0;
  let sumSq = 0;
  let n = 0;
  for (let y = 1; y < height - 1; y++) {
    for (let x = 1; x < width - 1; x++) {
      const i = y * width + x;
      const v = gray[i - width] + gray[i + width] + gray[i - 1] + gray[i + 1] - 4 * gray[i];
      sum += v;
      sumSq += v * v;
      n++;
    }
  }
  const mean = sum / n;
  return sumSq / n - mean * mean;
}

/** The latest `capacity` items with a score; `best()` is the highest-scoring one (the most recent if tied). */
export class BestRecent<T> {
  private items: { item: T; score: number }[] = [];
  constructor(private readonly capacity = 5) {}

  push(item: T, score: number): T | undefined {
    this.items.push({ item, score });
    return this.items.length > this.capacity ? this.items.shift()?.item : undefined; // the one that fell off, to release
  }

  best(): T | undefined {
    let top: { item: T; score: number } | undefined;
    for (const entry of this.items) if (!top || entry.score >= top.score) top = entry;
    return top?.item;
  }

  clear(): T[] {
    const dropped = this.items.map((e) => e.item);
    this.items = [];
    return dropped;
  }

  get size() {
    return this.items.length;
  }
}
