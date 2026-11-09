import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PoseClient, type WorkerLike } from "./poseClient";

class FakeWorker implements WorkerLike {
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: ErrorEvent) => void) | null = null;
  sent: { message: any; transfer?: Transferable[] }[] = [];
  terminated = false;
  postMessage(message: unknown, transfer?: Transferable[]) {
    this.sent.push({ message, transfer });
  }
  terminate() {
    this.terminated = true;
  }
  reply(data: unknown) {
    this.onmessage?.({ data } as MessageEvent);
  }
}

const bitmap = () => ({ close: vi.fn() }) as unknown as ImageBitmap;
const make = (over = {}) => {
  const worker = new FakeWorker();
  const client = new PoseClient({ wasmBase: "/mediapipe/wasm", modelUrl: "/mediapipe/m.task", createWorker: () => worker, ...over });
  return { worker, client };
};

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("PoseClient", () => {
  it("asks the worker to load the model and reports which delegate it got", async () => {
    const { worker, client } = make();
    expect(worker.sent[0].message).toEqual({ type: "init", wasmBase: "/mediapipe/wasm", modelUrl: "/mediapipe/m.task", delegate: "CPU" });
    worker.reply({ type: "ready", delegate: "CPU" });
    await expect(client.ready).resolves.toBe("CPU");
  });

  it("tries the GPU first only when told to", () => {
    const { worker } = make({ delegate: "GPU" });
    expect(worker.sent[0].message).toMatchObject({ delegate: "GPU" });
  });

  it("rejects when the model cannot be loaded, with the worker's reason", async () => {
    const { worker, client } = make();
    worker.reply({ type: "error", message: "Failed to fetch the model" });
    await expect(client.ready).rejects.toThrow("Failed to fetch the model");
  });

  it("rejects if the worker script itself fails to start", async () => {
    const { worker, client } = make();
    worker.onerror?.({ message: "Script error" } as ErrorEvent);
    await expect(client.ready).rejects.toThrow("Script error");
  });

  it("rejects if the model takes too long", async () => {
    const { client } = make({ loadTimeoutMs: 5000 });
    const outcome = expect(client.ready).rejects.toThrow(/too long/i);
    await vi.advanceTimersByTimeAsync(5001);
    await outcome;
  });

  it("hands a frame over to the worker (transferred, not copied) and returns the landmarks", async () => {
    const { worker, client } = make();
    const frame = bitmap();
    const result = client.detect(frame, 1234);

    const { message, transfer } = worker.sent[1];
    expect(message).toMatchObject({ type: "frame", ts: 1234 });
    expect(transfer).toEqual([frame]);
    worker.reply({ type: "result", id: message.id, landmarks: [{ x: 0.5, y: 0.5 }] });
    await expect(result).resolves.toEqual([{ x: 0.5, y: 0.5 }]);
  });

  it("returns null when the worker sees nobody", async () => {
    const { worker, client } = make();
    const result = client.detect(bitmap(), 1);
    worker.reply({ type: "result", id: worker.sent[1].message.id, landmarks: null });
    await expect(result).resolves.toBeNull();
  });

  it("matches each answer to its own frame, whatever order they come back in", async () => {
    const { worker, client } = make();
    const first = client.detect(bitmap(), 1);
    const second = client.detect(bitmap(), 2);
    const [a, b] = [worker.sent[1].message.id, worker.sent[2].message.id];
    worker.reply({ type: "result", id: b, landmarks: [{ x: 2, y: 2 }] });
    worker.reply({ type: "result", id: a, landmarks: [{ x: 1, y: 1 }] });
    expect(await first).toEqual([{ x: 1, y: 1 }]);
    expect(await second).toEqual([{ x: 2, y: 2 }]);
  });

  it("does not wait forever for an answer that never comes", async () => {
    const { client } = make();
    const result = client.detect(bitmap(), 1, 1000);
    await vi.advanceTimersByTimeAsync(1001);
    await expect(result).resolves.toBeNull();
  });

  it("ignores a late answer to a frame it already gave up on", async () => {
    const { worker, client } = make();
    const result = client.detect(bitmap(), 1, 500);
    await vi.advanceTimersByTimeAsync(501);
    await result;
    expect(() => worker.reply({ type: "result", id: worker.sent[1].message.id, landmarks: [] })).not.toThrow();
  });

  it("stops the worker on close, answers anything outstanding with null, and frees later frames", async () => {
    const { worker, client } = make();
    const waiting = client.detect(bitmap(), 1);
    client.close();
    await expect(waiting).resolves.toBeNull();
    expect(worker.terminated).toBe(true);

    const late = bitmap();
    await expect(client.detect(late, 2)).resolves.toBeNull();
    expect((late as unknown as { close: () => void }).close).toHaveBeenCalled(); // not leaked
    expect(worker.sent.filter((s) => s.message.type === "frame")).toHaveLength(1);
  });
});
