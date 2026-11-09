"use client";

/* eslint-disable @next/next/no-img-element */
import { useState } from "react";
import { Price } from "@/components/Price";
import { useRecommendations } from "@/lib/queries";
import type { Category, Product } from "@/lib/types";
import { useKioskStore } from "@/store/useKioskStore";

const CATEGORY_LABEL: Record<Category, string> = {
  top: "A top",
  bottom: "Bottoms",
  dress: "A dress",
  shoes: "Shoes",
  bag: "A bag",
  accessory: "An accessory",
};

/** More styles like the look, and one piece for each part of the outfit it is missing. Each is one tap to try on. */
export function RecommendationsPanel({ productIds }: { productIds: string[] }) {
  const query = useRecommendations(productIds);
  const tryOnWith = useKioskStore((s) => s.tryOnWith);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  async function tryOn(product: Product) {
    setBusy(product.id);
    setMessage(null);
    const result = await tryOnWith(product, { fromRecommendation: true });
    setBusy(null);
    if (!result.ok) setMessage(result.message);
  }

  const more = query.data?.more_styles ?? [];
  const complete = query.data?.complete_your_look ?? [];
  if (query.isPending) return <p className="px-2 text-xl text-mist/50">Finding more for you…</p>;
  if (query.isError || (more.length === 0 && complete.length === 0)) return null;

  return (
    <section aria-label="Suggestions" className="space-y-7">
      {message && (
        <p role="alert" className="rounded-2xl bg-red-500/15 px-4 py-3 text-xl text-red-200">
          {message}
        </p>
      )}

      {complete.length > 0 && (
        <div>
          <h3 className="mb-3 text-2xl font-semibold">Complete your look</h3>
          <ul className="space-y-3">
            {complete.map(({ category, product, reason }) => (
              <li key={product.id} className="glass flex items-center gap-4 rounded-3xl p-3">
                <img src={product.garment_image_url} alt="" draggable={false} className="h-28 w-20 flex-none rounded-2xl bg-[#e9e5da] object-contain p-1" />
                <div className="min-w-0 flex-1">
                  <p className="text-lg text-accent">{CATEGORY_LABEL[category]}</p>
                  <p className="truncate text-xl">{product.name}</p>
                  <Price product={product} />
                  <p className="line-clamp-1 text-base text-mist/50">{reason}</p>
                </div>
                <button type="button" className="btn-primary h-16 flex-none px-5 text-xl" disabled={busy !== null} onClick={() => void tryOn(product)} aria-label={`Try on ${product.name}`}>
                  {busy === product.id ? "…" : "Try on"}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {more.length > 0 && (
        <div>
          <h3 className="mb-3 text-2xl font-semibold">More styles</h3>
          <ul className="scroll-x flex gap-3 pb-2">
            {more.map((product) => (
              <li key={product.id} className="glass w-44 flex-none overflow-hidden rounded-3xl">
                <div className="aspect-[3/4] bg-[#e9e5da]">
                  <img src={product.garment_image_url} alt="" draggable={false} className="h-full w-full object-contain p-2" />
                </div>
                <div className="space-y-2 p-3">
                  <p className="truncate text-lg">{product.name}</p>
                  <Price product={product} />
                  <button type="button" className="btn-ghost h-16 w-full text-xl" disabled={busy !== null} onClick={() => void tryOn(product)} aria-label={`Try on ${product.name}`}>
                    {busy === product.id ? "…" : "Try on"}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
