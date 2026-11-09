"use client";

import { retentionText } from "@/lib/privacy";
import { useCallback, useEffect, useRef, useState } from "react";
import { CloseIcon } from "@/components/Icons";
import { CAMERA_CONSTRAINTS, describeCameraError } from "@/lib/cameraErrors";
import { centeredCrop } from "@/lib/capture";
import { CaptureController, type CaptureDeps, type CaptureEvents } from "@/lib/captureController";
import { config } from "@/lib/config";
import { captureRegion, type Guidance, idealLandmarks, type GuidanceCode } from "@/lib/pose";
import { PoseClient } from "@/lib/poseClient";
import { laplacianVariance, toGray } from "@/lib/sharpness";
import { useKioskStore } from "@/store/useKioskStore";

const WASM_BASE = "/mediapipe/wasm";
const MODEL_URL = "/mediapipe/pose_landmarker_lite.task";
const POSE_WIDTH = 640; // the frame the pose model looks at is a downscaled copy: it does not need Full HD
const SHARPNESS_SIZE = { w: 192, h: 256 }; // and sharpness is scored on a small copy of the cropped photo

const TONE: Record<GuidanceCode, string> = {
  no_person: "bg-white/15 text-mist",
  step_back: "bg-amber-400 text-ink",
  step_closer: "bg-amber-400 text-ink",
  center: "bg-amber-400 text-ink",
  hold_still: "bg-emerald-400 text-ink",
  ready: "bg-emerald-400 text-ink",
};


/** Everything the controller needs from the real camera. With no pose client, the shopper is always "in position". */
function makeDeps(el: HTMLVideoElement, poseClient: PoseClient | null): CaptureDeps<HTMLCanvasElement> {
  const aspect = config.captureWidth / config.captureHeight;
  const scratch = document.createElement("canvas");
  scratch.width = SHARPNESS_SIZE.w;
  scratch.height = SHARPNESS_SIZE.h;
  const scratchCtx = scratch.getContext("2d", { willReadFrequently: true });
  return {
    detect: async () => {
      if (!poseClient) return idealLandmarks(captureRegion(el.videoWidth, el.videoHeight, aspect));
      const h = Math.round((POSE_WIDTH * el.videoHeight) / el.videoWidth);
      const bitmap = await createImageBitmap(el, { resizeWidth: POSE_WIDTH, resizeHeight: h, resizeQuality: "low" });
      return poseClient.detect(bitmap, performance.now());
    },
    grab: async () => {
      const canvas = document.createElement("canvas");
      canvas.width = config.captureWidth;
      canvas.height = config.captureHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx || !scratchCtx) throw new Error("Couldn't take the photo in this browser.");
      const { sx, sy, sw, sh } = centeredCrop(el.videoWidth, el.videoHeight, aspect);
      ctx.drawImage(el, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height); // not mirrored: the model must see you the right way round
      scratchCtx.drawImage(canvas, 0, 0, SHARPNESS_SIZE.w, SHARPNESS_SIZE.h);
      const px = scratchCtx.getImageData(0, 0, SHARPNESS_SIZE.w, SHARPNESS_SIZE.h);
      return { frame: canvas, score: laplacianVariance(toGray(px.data, px.width, px.height), px.width, px.height) };
    },
    release: (canvas) => {
      canvas.width = 0; // frees the pixel memory of a frame that is no longer one of the last five
    },
    encode: (canvas) =>
      new Promise((resolve, reject) =>
        canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("Couldn't take the photo."))), "image/jpeg", config.captureQuality),
      ),
    region: () => captureRegion(el.videoWidth, el.videoHeight, aspect),
    now: () => performance.now(),
  };
}

/** Connects the controller to the store (phase and countdown) and to the screen's guidance text. */
function makeEvents(isDead: () => boolean, onGuidance: (g: Guidance) => void, onError: (e: Error) => void): CaptureEvents {
  const store = useKioskStore;
  let first = true;
  return {
    onGuidance: (g) => !isDead() && onGuidance(g),
    onCountdown: (n) => {
      if (isDead()) return;
      if (first) {
        first = false;
        store.getState().beginCountdown();
      }
      store.getState().setCountdown(n);
    },
    onCountdownCancelled: () => {
      first = true;
      if (!isDead()) store.getState().cancelCountdown();
    },
    onCaptured: (photo) => {
      if (!isDead()) void store.getState().submitCapture(photo);
    },
    onGiveUp: () => !isDead() && store.getState().cancelCapture(), // nobody came: back to the shop
    onError: (e) => !isDead() && onError(e),
  };
}

type Status = "starting" | "ready" | "error";

/**
 * The camera screen: a mirrored live preview with spoken-style guidance ("Step back", "Center yourself", "Hold still"),
 * then "Strike a pose" 3-2-1 and a photo. The camera opens here, never before the shopper has agreed on the consent screen.
 */
export function CaptureScreen() {
  const phase = useKioskStore((s) => s.phase);
  const countdown = useKioskStore((s) => s.countdown);
  const cameraError = useKioskStore((s) => s.cameraError);
  const store = useKioskStore;

  const video = useRef<HTMLVideoElement>(null);
  const controller = useRef<CaptureController<HTMLCanvasElement> | null>(null);
  const [status, setStatus] = useState<Status>("starting");
  const [poseReady, setPoseReady] = useState<"loading" | "ready" | "unavailable">("loading");
  const [delegate, setDelegate] = useState<string | null>(null);
  const [guidance, setGuidance] = useState<Guidance | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [manual, setManual] = useState(false);

  const cancel = useCallback(() => store.getState().cancelCapture(), [store]);

  useEffect(() => {
    let dead = false;
    let stream: MediaStream | null = null;
    let client: PoseClient | null = null;
    const el = video.current;
    store.getState().setCameraError(null);
    setStatus("starting");
    setPoseReady("loading");
    setGuidance(null);
    setManual(false);

    const fail = (e: unknown) => {
      if (dead) return;
      store.getState().setCameraError(describeCameraError(e));
      setStatus("error");
    };

    async function run() {
      if (!el) return;
      try {
        stream = await navigator.mediaDevices.getUserMedia(CAMERA_CONSTRAINTS);
        if (dead) return;
        el.srcObject = stream;
        await el.play();
      } catch (e) {
        return fail(e);
      }
      if (dead) return;
      setStatus("ready");

      // The pose model runs in a worker. If it cannot load, the shopper can still start the countdown by hand.
      try {
        client = new PoseClient({ wasmBase: WASM_BASE, modelUrl: MODEL_URL, delegate: config.poseDelegate });
        const used = await client.ready;
        if (!dead) setDelegate(used);
      } catch {
        client?.close();
        client = null;
        if (!dead) setPoseReady("unavailable");
        return;
      }
      if (dead) return;
      setPoseReady("ready");
      controller.current = new CaptureController(makeDeps(el, client), makeEvents(() => dead, setGuidance, fail), {
        countdownSeconds: config.countdownSeconds,
      });
      controller.current.start();
    }

    void run();
    return () => {
      dead = true;
      controller.current?.stop();
      controller.current = null;
      client?.close();
      stream?.getTracks().forEach((t) => t.stop()); // the camera light goes off the moment the shopper leaves
      if (el) el.srcObject = null;
    };
  }, [store, attempt]);

  // "Take my photo", when pose detection could not load: the same countdown and sharpest-frame choice, started by hand.
  const takeByHand = useCallback(() => {
    const el = video.current;
    if (!el) return;
    setManual(true);
    controller.current?.stop();
    controller.current = new CaptureController(
      makeDeps(el, null),
      makeEvents(() => false, () => undefined, (e) => store.getState().setCameraError(describeCameraError(e))),
      { countdownSeconds: config.countdownSeconds, steadyMs: 0 },
    );
    controller.current.start();
  }, [store]);

  const counting = phase === "countdown";
  const code = guidance?.code ?? "no_person";
  const message = status === "starting" ? "Starting the camera…" : poseReady === "loading" ? "Getting ready…" : (guidance?.message ?? "Step in front of the mirror");

  return (
    <div className="fixed inset-0 flex flex-col bg-ink" role="region" aria-label="Camera" data-pose-delegate={delegate ?? undefined} data-pose={poseReady}>
      <header className="flex flex-none items-center justify-between px-8 py-5">
        <button type="button" onClick={cancel} className="btn-ghost" aria-label="Cancel and go back to the shop">
          <CloseIcon /> Cancel
        </button>
        <div className="text-center">
          <h1 className="text-3xl font-semibold">{counting ? "Strike a pose" : "Step into the mirror"}</h1>
          {/* The privacy badge steps aside on this screen (it would cover the guidance), so the promise is stated here. */}
          <p className="mt-1 text-lg text-mist/60" data-testid="capture-privacy">
            🔒 Your photo is deleted within {retentionText()}
          </p>
        </div>
        <span className="w-40" aria-hidden />
      </header>

      <div className="relative mx-auto min-h-0 w-full flex-1 px-8 pb-6">
        <div className="relative mx-auto h-full max-w-full overflow-hidden rounded-[2.5rem] border border-white/15 bg-black" style={{ aspectRatio: "3 / 4" }}>
          {/* Mirrored, like a real mirror. The photo that is taken is not: see `grab`. */}
          <video ref={video} playsInline muted className="mirrored h-full w-full object-cover" />

          {status === "ready" && !counting && (
            <svg viewBox="0 0 300 400" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden>
              <g fill="none" stroke="white" strokeOpacity={code === "hold_still" || code === "ready" ? 0.2 : 0.55} strokeWidth="3" strokeDasharray="10 10">
                <circle cx="150" cy="62" r="26" />
                <path d="M110 108h80l16 120-24 6-6 150h-26l-4-110-4 110h-26l-6-150-24-6z" />
              </g>
            </svg>
          )}

          {status === "ready" && !counting && (code === "hold_still" || code === "ready") && guidance && (
            <div className="pointer-events-none absolute right-6 top-6" role="progressbar" aria-label="Hold still" aria-valuenow={Math.round(guidance.progress * 100)} aria-valuemin={0} aria-valuemax={100}>
              <svg viewBox="0 0 100 100" className="h-28 w-28 -rotate-90">
                <circle cx="50" cy="50" r="42" fill="rgba(0,0,0,0.45)" stroke="rgba(255,255,255,0.25)" strokeWidth="8" />
                <circle cx="50" cy="50" r="42" fill="none" stroke="#6ee7b7" strokeWidth="8" strokeLinecap="round" strokeDasharray={`${guidance.progress * 264} 264`} />
              </svg>
            </div>
          )}

          {counting && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-black/30" aria-live="assertive">
              <p className="text-5xl font-semibold">Strike a pose</p>
              <p className="text-[14rem] font-semibold leading-none tabular-nums" data-testid="countdown">
                {countdown}
              </p>
            </div>
          )}

          {status === "error" && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-8 bg-ink/95 p-10 text-center" role="alert">
              <p className="text-4xl">{cameraError ?? "The camera couldn't start."}</p>
              <div className="flex gap-4">
                <button type="button" className="btn-primary" onClick={() => setAttempt((n) => n + 1)}>
                  Try again
                </button>
                <button type="button" className="btn-ghost" onClick={cancel}>
                  Back to the shop
                </button>
              </div>
            </div>
          )}

          {status !== "error" && !counting && (
            <p
              className={`absolute inset-x-6 bottom-6 rounded-3xl px-6 py-5 text-center text-5xl font-semibold shadow-lg transition-colors ${
                status === "ready" && poseReady !== "loading" ? TONE[code] : "bg-white/15 text-mist"
              }`}
              aria-live="polite"
              data-testid="guidance"
            >
              {poseReady === "unavailable" && !manual ? "Stand in front of the mirror" : message}
            </p>
          )}
        </div>
      </div>

      {poseReady === "unavailable" && status === "ready" && !counting && !manual && (
        <div className="flex flex-none flex-col items-center gap-3 px-8 pb-8">
          <p className="text-2xl text-mist/70">We couldn&apos;t start pose guidance. Stand back so you&apos;re fully in the picture, then:</p>
          <button type="button" className="btn-primary h-24 px-16 text-3xl" onClick={takeByHand}>
            Take my photo
          </button>
        </div>
      )}
    </div>
  );
}
