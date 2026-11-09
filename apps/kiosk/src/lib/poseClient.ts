import type { Landmark } from "./pose";

export type WorkerLike = {
  postMessage: (message: unknown, transfer?: Transferable[]) => void;
  terminate: () => void;
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
};

export type PoseClientOptions = {
  wasmBase: string;
  modelUrl: string;
  /** Which MediaPipe delegate to try first (it falls back to the other if that one cannot start). Default CPU. */
  delegate?: "GPU" | "CPU";
  /** How the worker is made. The default starts the real one; tests give a fake. */
  createWorker?: () => WorkerLike;
  /** Give up on loading the model after this long (the model is a few MB and loads from the kiosk's own server). */
  loadTimeoutMs?: number;
};

/**
 * The main thread's handle on the pose worker: wait for it to load, then ask about one frame at a time.
 * A frame is transferred to the worker (not copied), and a result that never comes back is not waited on forever.
 */
export class PoseClient {
  private worker: WorkerLike | null;
  private nextId = 1;
  private pending = new Map<number, (landmarks: Landmark[] | null) => void>();
  readonly ready: Promise<"GPU" | "CPU">;
  private closed = false;

  constructor(private readonly opts: PoseClientOptions) {
    this.worker = (opts.createWorker ?? defaultWorker)();
    this.ready = new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error("The pose model took too long to load.")), opts.loadTimeoutMs ?? 20_000);
      this.worker!.onmessage = (event) => {
        const m = event.data;
        if (m.type === "ready") {
          clearTimeout(timer);
          resolve(m.delegate);
        } else if (m.type === "error") {
          clearTimeout(timer);
          reject(new Error(m.message || "The pose model could not be loaded."));
        } else if (m.type === "result") {
          this.pending.get(m.id)?.(m.landmarks ?? null);
          this.pending.delete(m.id);
        }
      };
      this.worker!.onerror = (event) => {
        clearTimeout(timer);
        reject(new Error(event.message || "The pose worker failed to start."));
      };
    });
    this.ready.catch(() => undefined); // the caller handles it; this only stops an "unhandled rejection" warning
    this.worker.postMessage({ type: "init", wasmBase: opts.wasmBase, modelUrl: opts.modelUrl, delegate: opts.delegate ?? "CPU" });
  }

  /** Landmarks for one frame (a downscaled ImageBitmap, which is handed over to the worker), or null for nobody. */
  detect(bitmap: ImageBitmap, timestampMs: number, timeoutMs = 3000): Promise<Landmark[] | null> {
    const worker = this.worker;
    if (!worker || this.closed) {
      bitmap.close();
      return Promise.resolve(null);
    }
    const id = this.nextId++;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        resolve(null);
      }, timeoutMs);
      this.pending.set(id, (landmarks) => {
        clearTimeout(timer);
        resolve(landmarks);
      });
      worker.postMessage({ type: "frame", id, bitmap, ts: timestampMs }, [bitmap]);
    });
  }

  close() {
    this.closed = true;
    this.worker?.terminate();
    this.worker = null;
    for (const done of this.pending.values()) done(null);
    this.pending.clear();
  }
}

function defaultWorker(): WorkerLike {
  return new Worker(new URL("../workers/pose.worker.ts", import.meta.url)) as unknown as WorkerLike;
}
