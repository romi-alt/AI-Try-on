"use client";

/* eslint-disable @next/next/no-img-element */
import { CloseIcon } from "@/components/Icons";
import { config } from "@/lib/config";
import { useKioskStore } from "@/store/useKioskStore";

/** "Selected items" across the top: what the shopper has chosen, with a big "Try it on" button. */
export function SelectedTray() {
  const selected = useKioskStore((s) => s.selected);
  const deselect = useKioskStore((s) => s.deselect);
  const openDetail = useKioskStore((s) => s.openDetail);
  const startCapture = useKioskStore((s) => s.startCapture);
  const max = config.maxOutfitItems;

  return (
    <section aria-label="Selected items" className="glass mx-6 mt-4 flex flex-none items-center gap-5 rounded-[2rem] p-4">
      <div className="w-44 flex-none">
        <h2 className="text-2xl font-semibold">Selected items</h2>
        <p className="text-lg text-mist/60">
          {selected.length} of {max}
        </p>
      </div>

      <ul className="scroll-x flex min-w-0 flex-1 gap-3">
        {selected.length === 0 && <li className="self-center text-xl text-mist/50">Tap an item to see it and add it to your outfit.</li>}
        {selected.map((item) => (
          <li key={item.product.id} className="relative flex-none">
            <button
              type="button"
              onClick={() => openDetail(item.product)}
              aria-label={`${item.product.name}${item.size ? `, size ${item.size}` : ""}${item.color ? `, ${item.color}` : ""}. Open details`}
              className="block h-32 w-24 overflow-hidden rounded-2xl bg-[#e9e5da] active:scale-[0.97]"
            >
              <img src={item.product.garment_image_url} alt="" draggable={false} className="h-full w-full object-contain p-1.5" />
            </button>
            {item.size && (
              <span className="absolute bottom-1 left-1 rounded-lg bg-black/70 px-2 py-0.5 text-base">{item.size}</span>
            )}
            <button
              type="button"
              onClick={() => deselect(item.product.id)}
              aria-label={`Remove ${item.product.name}`}
              className="absolute -right-2 -top-2 flex h-16 w-16 items-center justify-center rounded-full border border-white/25 bg-ink/90 active:scale-95"
            >
              <CloseIcon />
            </button>
          </li>
        ))}
      </ul>

      <button type="button" className="btn-primary h-24 flex-none px-8 text-2xl" disabled={selected.length === 0} onClick={startCapture}>
        Try it on
      </button>
    </section>
  );
}
