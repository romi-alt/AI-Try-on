"use client";

/* eslint-disable @next/next/no-img-element */
import { useKioskStore } from "@/store/useKioskStore";
import { WebcamMirror } from "./WebcamMirror";

function stageText(status: string | undefined, pct: number): string {
  if (status === "queued") return "Waiting for a free mirror…";
  if (pct < 10) return "Getting started…";
  if (pct < 90) return "Fitting your look…";
  return "Finishing up…";
}

/** The portrait frame on the left: live camera while choosing, progress while rendering, then the result. */
export function MirrorStage() {
  const phase = useKioskStore((s) => s.phase);
  const countdown = useKioskStore((s) => s.countdown);
  const job = useKioskStore((s) => s.job);
  const resultUrl = useKioskStore((s) => s.resultUrl);
  const error = useKioskStore((s) => s.error);
  const cameraReady = useKioskStore((s) => s.cameraReady);
  const cancelCountdown = useKioskStore((s) => s.cancelCountdown);
  const backToBrowsing = useKioskStore((s) => s.backToBrowsing);

  const showResult = phase === "result" && resultUrl;
  const pct = job?.pct ?? 0;

  return (
    <section className="flex min-h-0 items-center justify-center p-4">
      <div className="relative aspect-[3/4] h-full max-h-full overflow-hidden rounded-3xl bg-black ring-1 ring-white/10">
        {showResult ? (
          <img src={resultUrl} alt="You wearing your selection" className="absolute inset-0 h-full w-full object-cover" />
        ) : (
          <WebcamMirror />
        )}

        {phase === "browsing" && cameraReady && (
          <p className="pointer-events-none absolute inset-x-0 bottom-4 text-center text-sm text-white/80 drop-shadow">
            Stand back so you&apos;re fully in the frame
          </p>
        )}

        {phase === "countdown" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-6 bg-black/30">
            <span key={countdown} className="text-9xl font-semibold drop-shadow-lg" aria-live="assertive">
              {countdown}
            </span>
            <button
              type="button"
              onClick={cancelCountdown}
              className="rounded-full border border-white/40 bg-black/40 px-6 py-3 text-sm uppercase tracking-widest hover:bg-black/60"
            >
              Cancel
            </button>
          </div>
        )}

        {(phase === "uploading" || phase === "working") && (
          <div
            className="absolute inset-0 flex flex-col items-center justify-center gap-5 bg-black/60 p-8 backdrop-blur-sm"
            role="status"
          >
            <span className="h-12 w-12 animate-spin rounded-full border-4 border-white/20 border-t-accent" />
            <p className="text-xl">{phase === "uploading" ? "Sending your photo…" : stageText(job?.status, pct)}</p>
            {phase === "working" && (
              <div className="w-full max-w-xs">
                <div
                  className="h-2 overflow-hidden rounded-full bg-white/15"
                  role="progressbar"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={pct}
                >
                  <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />
                </div>
                <p className="mt-2 text-center text-sm tabular-nums text-white/70">{pct}%</p>
              </div>
            )}
          </div>
        )}

        {phase === "error" && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-5 bg-black/80 p-8 text-center" role="alert">
            <p className="text-2xl font-medium">We couldn&apos;t finish your look</p>
            <p className="max-w-sm text-mist/80">{error}</p>
            <button
              type="button"
              onClick={backToBrowsing}
              className="rounded-full bg-mist px-8 py-4 text-lg font-medium text-ink hover:scale-[1.02] active:scale-[0.98]"
            >
              Try again
            </button>
          </div>
        )}
      </div>
    </section>
  );
}
