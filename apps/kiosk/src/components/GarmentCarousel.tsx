"use client";

/* eslint-disable @next/next/no-img-element */
import { useSessionStore } from "@/store/useSessionStore";

export function GarmentCarousel() {
  const garments = useSessionStore((s) => s.garments);
  const selectedId = useSessionStore((s) => s.selectedGarmentId);
  const status = useSessionStore((s) => s.status);
  const selectGarment = useSessionStore((s) => s.selectGarment);
  const runTryOn = useSessionStore((s) => s.runTryOn);

  const busy = status === "capturing" || status === "uploading" || status === "processing";
  const canTryOn = !busy && status !== "idle" && !!selectedId;

  return (
    <div className="flex items-center gap-4">
      <div className="flex flex-1 gap-3 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {garments.length === 0 && (
          <p className="py-6 text-sm text-mist/50">No garments yet — run `make seed` or add some in the admin app.</p>
        )}
        {garments.map((g) => {
          const selected = g.id === selectedId;
          return (
            <button
              key={g.id}
              type="button"
              onClick={() => selectGarment(g.id)}
              disabled={busy}
              className={`group relative h-28 w-24 flex-none overflow-hidden rounded-xl border-2 transition ${
                selected ? "border-accent" : "border-transparent hover:border-white/30"
              } disabled:opacity-60`}
              aria-pressed={selected}
            >
              <img src={g.image_url} alt={g.name} className="h-full w-full object-cover" draggable={false} />
              <span className="absolute inset-x-0 bottom-0 truncate bg-black/60 px-2 py-1 text-left text-[11px] text-mist">
                {g.name}
              </span>
            </button>
          );
        })}
      </div>

      <button
        type="button"
        onClick={() => void runTryOn()}
        disabled={!canTryOn}
        className="flex-none rounded-full bg-mist px-8 py-4 text-lg font-medium text-ink transition hover:scale-[1.02] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
      >
        {busy ? "Working…" : "Try it on"}
      </button>
    </div>
  );
}
