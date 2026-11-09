"use client";

import { useEffect, useRef, useState } from "react";
import { captureFrame } from "@/lib/capture";
import { config } from "@/lib/config";
import { useKioskStore } from "@/store/useKioskStore";

/**
 * The live preview, mirrored like a real mirror and cropped to the same portrait frame the photo will use
 * (what you see is what is captured). Mounted only while it is needed, so the camera light is off on the
 * consent screen and while the result is shown.
 */
export function WebcamMirror() {
  const videoRef = useRef<HTMLVideoElement>(null);
  const setCamera = useKioskStore((s) => s.setCamera);
  const registerCapture = useKioskStore((s) => s.registerCapture);
  const cameraError = useKioskStore((s) => s.cameraError);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let stream: MediaStream | null = null;
    let cancelled = false;
    setCamera(false);

    (async () => {
      try {
        if (!navigator.mediaDevices?.getUserMedia) throw new Error("This browser can't use a camera here.");
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "user", width: { ideal: 1920 }, height: { ideal: 1080 } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        const video = videoRef.current;
        if (!video) return;
        video.srcObject = stream;
        await video.play();
        if (!cancelled) setCamera(true);
      } catch (e) {
        if (cancelled) return;
        const denied = e instanceof DOMException && (e.name === "NotAllowedError" || e.name === "SecurityError");
        setCamera(
          false,
          denied
            ? "Camera access is blocked. Allow the camera for this page, then try again."
            : e instanceof DOMException && e.name === "NotFoundError"
              ? "No camera was found."
              : e instanceof Error
                ? e.message
                : "The camera couldn't be started.",
        );
      }
    })();

    registerCapture(() => {
      const video = videoRef.current;
      if (!video) return Promise.reject(new Error("The camera isn't ready yet."));
      return captureFrame(video, {
        width: config.captureWidth,
        height: config.captureHeight,
        quality: config.captureQuality,
      });
    });

    return () => {
      cancelled = true;
      registerCapture(null);
      setCamera(false);
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [attempt, setCamera, registerCapture]);

  return (
    <>
      <video ref={videoRef} playsInline muted className="mirrored absolute inset-0 h-full w-full object-cover" />
      {cameraError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-black/80 p-8 text-center">
          <p className="text-xl">Camera unavailable</p>
          <p className="text-sm text-mist/70">{cameraError}</p>
          <button
            type="button"
            onClick={() => setAttempt((n) => n + 1)}
            className="rounded-full border border-white/30 px-6 py-3 text-sm uppercase tracking-widest hover:bg-white/10"
          >
            Try again
          </button>
        </div>
      )}
    </>
  );
}
