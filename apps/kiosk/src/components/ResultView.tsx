"use client";

/* eslint-disable @next/next/no-img-element */
import { useSessionStore } from "@/store/useSessionStore";

export function ResultView() {
  const job = useSessionStore((s) => s.job);
  const garments = useSessionStore((s) => s.garments);
  const backToMirror = useSessionStore((s) => s.backToMirror);

  const garment = garments.find((g) => g.id === job?.garment_id);

  if (!job?.result_url) {
    return (
      <div className="flex h-full items-center justify-center text-mist/60">No result to show.</div>
    );
  }

  return (
    <div className="relative h-full w-full bg-black">
      <img src={job.result_url} alt="Your try-on result" className="h-full w-full object-contain" />

      <div className="absolute inset-x-0 bottom-0 flex items-end justify-between bg-gradient-to-t from-black/80 to-transparent p-6">
        <div>
          {garment && (
            <>
              <p className="text-xs uppercase tracking-[0.3em] text-accent">{garment.brand ?? "Look"}</p>
              <p className="text-2xl font-medium">{garment.name}</p>
              {garment.price_cents != null && (
                <p className="text-mist/70">${(garment.price_cents / 100).toFixed(2)}</p>
              )}
            </>
          )}
        </div>
        <button
          type="button"
          onClick={backToMirror}
          className="rounded-full border border-white/30 px-6 py-3 text-sm uppercase tracking-widest hover:bg-white/10"
        >
          Try another
        </button>
      </div>
    </div>
  );
}
