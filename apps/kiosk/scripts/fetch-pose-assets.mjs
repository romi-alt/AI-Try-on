// Puts MediaPipe's WASM files and the Pose Landmarker model under public/mediapipe/, so the kiosk serves them itself
// (no CDN at runtime: a store's network can be slow or offline). Runs before `dev` and `build`.
//
// The WASM files are copied from node_modules/@mediapipe/tasks-vision. The model (about 5 MB) is downloaded once from
// Google's model storage; set POSE_MODEL_URL to fetch it from somewhere else (an internal mirror), or put the file
// at public/mediapipe/pose_landmarker_lite.task yourself.
import { copyFile, mkdir, readdir, stat, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const out = path.join(here, "..", "public", "mediapipe");
const MODEL = "pose_landmarker_lite.task";
const MODEL_URL =
  process.env.POSE_MODEL_URL ??
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task";

const require = createRequire(import.meta.url);
// The package restricts its `exports`, so locate it through its main file (vision_bundle.cjs, next to wasm/).
const pkgDir = path.dirname(require.resolve("@mediapipe/tasks-vision"));

await mkdir(path.join(out, "wasm"), { recursive: true });
for (const file of await readdir(path.join(pkgDir, "wasm"))) {
  await copyFile(path.join(pkgDir, "wasm", file), path.join(out, "wasm", file));
}

const target = path.join(out, MODEL);
const have = await stat(target).then((s) => s.size).catch(() => 0);
if (have > 1_000_000) {
  console.log(`pose assets: ${MODEL} already present (${(have / 1e6).toFixed(1)} MB)`);
} else {
  console.log(`pose assets: downloading ${MODEL} ...`);
  const res = await fetch(MODEL_URL, { redirect: "follow" });
  if (!res.ok) {
    console.error(`pose assets: could not download the model (HTTP ${res.status}) from ${MODEL_URL}.`);
    console.error(`Put ${MODEL} in ${out} yourself, or set POSE_MODEL_URL.`);
    process.exit(1);
  }
  const bytes = Buffer.from(await res.arrayBuffer());
  if (bytes.length < 1_000_000) {
    console.error(`pose assets: the model download is only ${bytes.length} bytes; refusing to use it.`);
    process.exit(1);
  }
  await writeFile(target, bytes);
  console.log(`pose assets: saved ${MODEL} (${(bytes.length / 1e6).toFixed(1)} MB)`);
}
