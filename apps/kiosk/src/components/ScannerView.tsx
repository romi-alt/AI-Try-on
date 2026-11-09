"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { canScan, parseProductCode } from "@/lib/scanner";
import { useKioskStore } from "@/store/useKioskStore";

type Detector = { detect: (source: CanvasImageSource) => Promise<{ rawValue: string }[]> };

/**
 * Point a product tag's QR code at the camera to open that product. The camera starts only when the shopper taps
 * Start, shows no recording and keeps nothing: each frame is read and dropped.
 */
export function ScannerView() {
  const video = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<"idle" | "scanning" | "looking">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const setView = useKioskStore((s) => s.setView);
  const openDetail = useKioskStore((s) => s.openDetail);

  useEffect(() => {
    if (state !== "scanning") return;
    let stop = false;
    let stream: MediaStream | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;

    async function run() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" }, audio: false });
        if (stop || !video.current) return;
        video.current.srcObject = stream;
        await video.current.play();
        const Ctor = (window as unknown as { BarcodeDetector: new (o: { formats: string[] }) => Detector }).BarcodeDetector;
        const detector = new Ctor({ formats: ["qr_code"] });
        const tick = async () => {
          if (stop || !video.current) return;
          try {
            const found = await detector.detect(video.current);
            const id = found.map((f) => parseProductCode(f.rawValue)).find(Boolean);
            if (id) {
              setState("looking");
              try {
                const product = await api.getProduct(id);
                if (stop) return;
                setView("shop");
                openDetail(product);
              } catch {
                if (stop) return;
                setMessage("That tag isn't one of our products. Try another.");
                setState("scanning");
              }
              return;
            }
          } catch {
            /* a frame that cannot be read is skipped */
          }
          timer = setTimeout(tick, 250);
        };
        void tick();
      } catch {
        if (!stop) {
          setMessage("The camera isn't available. Ask a team member for help.");
          setState("idle");
        }
      }
    }
    void run();
    return () => {
      stop = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((t) => t.stop()); // the camera is released as soon as the shopper leaves this view
    };
  }, [state, setView, openDetail]);

  return (
    <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-8 p-10 text-center">
      <h1 className="text-5xl font-semibold">Scan a tag</h1>
      <p className="max-w-xl text-2xl text-mist/70">Hold the QR code on a product tag up to the camera to see it here.</p>

      {state === "idle" && (
        <>
          {!canScan() && (
            <p className="max-w-xl rounded-2xl bg-white/10 px-6 py-4 text-xl">This screen can&apos;t read codes. Browse the shop, or ask a team member.</p>
          )}
          <button type="button" className="btn-primary h-24 px-12 text-3xl" disabled={!canScan()} onClick={() => (setMessage(null), setState("scanning"))}>
            Start scanning
          </button>
          <p className="max-w-lg text-lg text-mist/50">Nothing is recorded or saved. The camera turns off when you leave this screen.</p>
        </>
      )}

      {state !== "idle" && (
        <>
          <video ref={video} playsInline muted className="aspect-square w-[640px] max-w-full rounded-[2rem] border border-white/20 object-cover" />
          <button type="button" className="btn-ghost" onClick={() => setState("idle")}>
            Stop
          </button>
        </>
      )}

      {message && (
        <p role="alert" className="rounded-2xl bg-red-500/15 px-6 py-4 text-xl text-red-200">
          {message}
        </p>
      )}
    </div>
  );
}
