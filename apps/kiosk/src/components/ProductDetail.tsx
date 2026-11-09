"use client";

/* eslint-disable @next/next/no-img-element */
import { useEffect, useState } from "react";
import { CloseIcon } from "@/components/Icons";
import { Price } from "@/components/Price";
import { config } from "@/lib/config";
import { discountPercent } from "@/lib/money";
import { useKioskStore } from "@/store/useKioskStore";

/** The product detail panel: a large image, price, size and colour selectors, and add to / remove from the outfit. */
export function ProductDetail() {
  const product = useKioskStore((s) => s.detail);
  const selection = useKioskStore((s) => s.selected.find((i) => i.product.id === s.detail?.id));
  const count = useKioskStore((s) => s.selected.length);
  const openDetail = useKioskStore((s) => s.openDetail);
  const select = useKioskStore((s) => s.select);
  const deselect = useKioskStore((s) => s.deselect);

  const [size, setSize] = useState<string | null>(null);
  const [color, setColor] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  // Start from the options already chosen for this item, or the only option there is.
  useEffect(() => {
    setMessage(null);
    if (!product) return;
    setSize(selection?.size ?? (product.sizes.length === 1 ? product.sizes[0] : null));
    setColor(selection?.color ?? (product.colors.length === 1 ? product.colors[0].name : null));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset only when a different product opens
  }, [product?.id]);

  if (!product) return null;
  const soldOut = product.stock <= 0;
  const needsSize = product.sizes.length > 1 && !size;
  const needsColor = product.colors.length > 1 && !color;
  const missing = needsSize ? "a size" : needsColor ? "a colour" : null;
  const off = discountPercent(product.price_pkr, product.sale_price_pkr);
  const full = !selection && count >= config.maxOutfitItems;

  function add() {
    if (missing) return setMessage(`Choose ${missing} first.`);
    const result = select(product!, { size, color });
    if (!result.ok) return setMessage(result.message);
    openDetail(null);
  }

  return (
    <div className="absolute inset-0 z-30 flex items-end" role="dialog" aria-modal="true" aria-label={product.name}>
      <button type="button" aria-label="Close details" className="absolute inset-0 bg-black/60" onClick={() => openDetail(null)} />
      <div className="glass-strong relative mx-auto flex max-h-[88%] w-full flex-col overflow-hidden rounded-t-[2.5rem]">
        <div className="flex items-center justify-between px-8 pt-6">
          <h2 className="text-3xl font-semibold">{product.name}</h2>
          <button type="button" onClick={() => openDetail(null)} aria-label="Close" className="btn-ghost !px-0 w-16">
            <CloseIcon />
          </button>
        </div>

        <div className="scroll-y grid grid-cols-[minmax(0,5fr)_minmax(0,6fr)] gap-8 p-8">
          <div className="relative aspect-[3/4] overflow-hidden rounded-3xl bg-[#e9e5da]">
            <img src={product.garment_image_url} alt={product.name} draggable={false} className="h-full w-full object-contain p-4" />
            {off > 0 && <span className="absolute left-4 top-4 rounded-full bg-accent px-5 py-2 text-2xl font-semibold text-ink">-{off}%</span>}
          </div>

          <div className="flex flex-col gap-7">
            <Price product={product} size="lg" />
            <p className="text-xl text-mist/70">{soldOut ? "Sold out" : product.stock <= 3 ? `Only ${product.stock} left` : "In stock"}</p>

            {product.sizes.length > 0 && (
              <fieldset>
                <legend className="mb-3 text-xl text-mist/70">Size</legend>
                <div className="flex flex-wrap gap-3" role="group" aria-label="Size">
                  {product.sizes.map((s) => (
                    <button key={s} type="button" aria-pressed={size === s} onClick={() => (setSize(s), setMessage(null))} className="chip">
                      {s}
                    </button>
                  ))}
                </div>
              </fieldset>
            )}

            {product.colors.length > 0 && (
              <fieldset>
                <legend className="mb-3 text-xl text-mist/70">Colour{color ? `: ${color}` : ""}</legend>
                <div className="flex flex-wrap gap-3" role="group" aria-label="Colour">
                  {product.colors.map((c) => (
                    <button
                      key={c.name}
                      type="button"
                      aria-pressed={color === c.name}
                      aria-label={c.name}
                      onClick={() => (setColor(c.name), setMessage(null))}
                      className={`h-16 w-16 rounded-full border-4 transition active:scale-95 ${color === c.name ? "border-accent" : "border-white/25"}`}
                      style={{ background: c.hex }}
                    />
                  ))}
                </div>
              </fieldset>
            )}

            {message && (
              <p role="alert" className="rounded-2xl bg-red-500/15 px-5 py-4 text-xl text-red-200">
                {message}
              </p>
            )}

            <div className="mt-auto flex flex-col gap-3">
              {selection ? (
                <>
                  <button type="button" className="btn-primary h-20 text-2xl" onClick={add}>
                    Update outfit
                  </button>
                  <button type="button" className="btn-ghost h-20 text-2xl" onClick={() => (deselect(product.id), openDetail(null))}>
                    Remove from outfit
                  </button>
                </>
              ) : (
                <button type="button" className="btn-primary h-20 text-2xl" disabled={soldOut || full} onClick={add}>
                  {soldOut ? "Sold out" : full ? `Outfit is full (${config.maxOutfitItems})` : "Add to outfit"}
                </button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
