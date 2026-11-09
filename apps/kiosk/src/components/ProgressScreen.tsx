"use client";

import { clampPct, ringDash, stageLabel } from "@/lib/progress";
import { useKioskStore } from "@/store/useKioskStore";

const RADIUS = 130;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;

/** The ring that fills as the look is made. */
export function ProgressRing({ pct }: { pct: number }) {
  const value = clampPct(pct);
  return (
    <div className="relative h-80 w-80" role="progressbar" aria-label="Creating your look" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <svg viewBox="0 0 300 300" className="h-full w-full -rotate-90">
        <circle cx="150" cy="150" r={RADIUS} fill="rgba(0,0,0,0.35)" stroke="rgba(255,255,255,0.18)" strokeWidth="14" />
        <circle
          cx="150"
          cy="150"
          r={RADIUS}
          fill="none"
          stroke="#d7c8a8"
          strokeWidth="14"
          strokeLinecap="round"
          strokeDasharray={ringDash(value, CIRCUMFERENCE)}
          style={{ transition: "stroke-dasharray 0.6s ease" }}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-8xl font-semibold tabular-nums">{value}%</span>
    </div>
  );
}

/** Shown while the photo uploads and the look is made, over a blurred copy of the photo that was taken. */
export function ProgressScreen() {
  const phase = useKioskStore((s) => s.phase);
  const pct = useKioskStore((s) => (s.phase === "uploading" ? 2 : (s.job?.pct ?? 0)));
  const photoUrl = useKioskStore((s) => s.photoUrl);
  const timedOut = useKioskStore((s) => s.timedOut);
  const retry = useKioskStore((s) => s.retryTryOn);
  const backToShop = useKioskStore((s) => s.backToShop);

  return (
    <div className="fixed inset-0 flex flex-col items-center justify-center gap-10 overflow-hidden" role="status" aria-live="polite" aria-busy="true">
      {photoUrl && (
        // The shopper's own photo, blurred past recognition so it is a backdrop and not a second preview.
        // eslint-disable-next-line @next/next/no-img-element
        <img src={photoUrl} alt="" className="absolute inset-0 h-full w-full scale-125 object-cover opacity-60 blur-3xl" />
      )}
      <div className="absolute inset-0 bg-ink/40" />

      <div className="relative flex flex-col items-center gap-10 text-center">
        <ProgressRing pct={pct} />
        <div className="space-y-3">
          <p className="text-6xl font-semibold">Almost there...</p>
          <p className="text-3xl text-mist/70">{stageLabel(phase, pct)}</p>
        </div>

        {timedOut && (
          <div className="glass-strong max-w-xl space-y-6 rounded-[2rem] p-8">
            <p className="text-3xl">This is taking longer than usual.</p>
            <div className="flex justify-center gap-4">
              <button type="button" className="btn-primary h-20 px-10 text-3xl" onClick={() => void retry()}>
                Try again
              </button>
              <button type="button" className="btn-ghost h-20 px-10 text-3xl" onClick={backToShop}>
                Back to shop
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
