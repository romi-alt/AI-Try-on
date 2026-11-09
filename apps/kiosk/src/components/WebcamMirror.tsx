"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { config } from "@/lib/config";
import { useSessionStore } from "@/store/useSessionStore";

/**
 * Full-bleed, horizontally mirrored webcam preview.
 * Registers a capture function with the store that grabs the current frame
 * (un-mirrored, so the model sees the real orientation) as a JPEG blob.
 */
export function WebcamMirror() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [camError, setCamError] = useState<string | null>(null);
  const registerCapture = useSessionStore((s) => s.registerCapture);
  const status = useSessionStore((s) => s.status);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let cancelled = false;

    (async () => {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: "user",
            width: { ideal: config.captureWidth },
            height: { ideal: config.captureHeight },
          },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
      } catch (e) {
        setCamError(e instanceof Error ? e.message : "Camera unavailable");
      }
    })();

    return () => {
      cancelled = true;
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  const capture = useCallback(async (): Promise<Blob> => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas || video.readyState < 2) throw new Error("Camera not ready");

    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Canvas unsupported");
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    return new Promise((resolve, reject) => {
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error("Capture failed"))), "image/jpeg", 0.92);
    });
  }, []);

  useEffect(() => {
    registerCapture(capture);
    return () => registerCapture(null);
  }, [capture, registerCapture]);

  const busy = status === "capturing" || status === "uploading" || status === "processing";

  return (
    <div className="relative h-full w-full bg-black">
      <video ref={videoRef} playsInline muted className="mirrored h-full w-full object-cover" />
      <canvas ref={canvasRef} className="hidden" />

      {camError && (
        <div className="absolute inset-0 flex items-center justify-center p-8 text-center text-mist/80">
          <div>
            <p className="text-xl">Camera unavailable</p>
            <p className="mt-2 text-sm text-mist/60">{camError}</p>
          </div>
        </div>
      )}

      {busy && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/50 backdrop-blur-sm">
          <div className="flex flex-col items-center gap-4">
            <span className="h-12 w-12 animate-spin rounded-full border-4 border-white/20 border-t-accent" />
            <p className="text-lg">
              {status === "capturing" && "Hold still…"}
              {status === "uploading" && "Uploading…"}
              {status === "processing" && "Rendering your look…"}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
