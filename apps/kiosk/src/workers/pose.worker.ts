/// <reference lib="webworker" />
// Runs MediaPipe Pose Landmarker off the main thread, so the video preview and the countdown never stutter.
//
//   main -> worker  { type: "init", wasmBase, modelUrl }          load the model
//   main -> worker  { type: "frame", id, bitmap, ts }              detect in this frame (bitmap is transferred)
//   worker -> main  { type: "ready", delegate }                    model loaded ("GPU" or "CPU")
//   worker -> main  { type: "error", message }                     the model could not be loaded
//   worker -> main  { type: "result", id, landmarks }              33 normalised landmarks, or null for nobody
import { FilesetResolver, PoseLandmarker } from "@mediapipe/tasks-vision";

type Delegate = "GPU" | "CPU";
type InitMessage = { type: "init"; wasmBase: string; modelUrl: string; delegate?: Delegate };
type FrameMessage = { type: "frame"; id: number; bitmap: ImageBitmap; ts: number };

const ctx = self as unknown as DedicatedWorkerGlobalScope;
let landmarker: PoseLandmarker | null = null;

async function create(wasmBase: string, modelUrl: string, delegate: Delegate) {
  const vision = await FilesetResolver.forVisionTasks(wasmBase);
  return PoseLandmarker.createFromOptions(vision, {
    baseOptions: { modelAssetPath: modelUrl, delegate },
    runningMode: "VIDEO",
    numPoses: 1,
  });
}

async function init({ wasmBase, modelUrl, delegate: preferred = "CPU" }: InitMessage) {
  // The preferred delegate first, then the other. CPU is the default: on a machine without a real GPU the GPU delegate
  // falls back to software rendering, which is several times slower and spends seconds compiling on its first frame.
  const order: Delegate[] = preferred === "GPU" ? ["GPU", "CPU"] : ["CPU", "GPU"];
  for (const [i, delegate] of order.entries()) {
    try {
      landmarker = await create(wasmBase, modelUrl, delegate);
      ctx.postMessage({ type: "ready", delegate });
      return;
    } catch (e) {
      if (i === order.length - 1) ctx.postMessage({ type: "error", message: e instanceof Error ? e.message : String(e) });
    }
  }
}

function detect({ id, bitmap, ts }: FrameMessage) {
  try {
    const result = landmarker?.detectForVideo(bitmap, ts);
    const first = result?.landmarks?.[0];
    ctx.postMessage({
      type: "result",
      id,
      landmarks: first ? first.map((p) => ({ x: p.x, y: p.y, z: p.z, visibility: p.visibility })) : null,
    });
  } catch {
    ctx.postMessage({ type: "result", id, landmarks: null });
  } finally {
    bitmap.close();
  }
}

ctx.onmessage = (event: MessageEvent<InitMessage | FrameMessage>) => {
  const message = event.data;
  if (message.type === "init") void init(message);
  else if (message.type === "frame") detect(message);
};
