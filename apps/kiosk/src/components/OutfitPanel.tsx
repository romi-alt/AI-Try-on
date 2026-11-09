"use client";

/* eslint-disable @next/next/no-img-element */
import { useEffect, useRef, useState } from "react";
import type { Product } from "@/lib/types";
import { useKioskStore } from "@/store/useKioskStore";
import { Price } from "./ProductCard";

function OutfitItem({ product }: { product: Product }) {
  const cart = useKioskStore((s) => s.cart);
  const addToCart = useKioskStore((s) => s.addToCart);

  // With nothing to choose between (one size, one colour) there is nothing to ask.
  const [size, setSize] = useState<string | null>(product.sizes.length === 1 ? product.sizes[0] : null);
  const [color, setColor] = useState<string | null>(product.colors.length === 1 ? product.colors[0].name : null);
  const [status, setStatus] = useState<"idle" | "adding" | "added">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);

  const inCart = cart?.items.filter((i) => i.product.id === product.id).reduce((n, i) => n + i.quantity, 0) ?? 0;
  const missing = product.sizes.length > 1 && !size ? "size" : product.colors.length > 1 && !color ? "colour" : null;

  async function add() {
    setStatus("adding");
    setMessage(null);
    const result = await addToCart(product, size, color);
    if (result.ok) {
      setStatus("added");
      timer.current = setTimeout(() => setStatus("idle"), 1800);
    } else {
      setStatus("idle");
      setMessage(result.message);
    }
  }

  return (
    <div className="flex gap-4 rounded-2xl bg-white/5 p-3">
      <div className="h-28 w-[5.25rem] flex-none overflow-hidden rounded-xl bg-[#e9e5da]">
        <img src={product.garment_image_url} alt="" className="h-full w-full object-contain p-2" draggable={false} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div>
          <p className="truncate font-medium">{product.name}</p>
          <Price product={product} className="text-sm text-mist/80" />
        </div>

        {product.sizes.length > 1 && (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Size">
            {product.sizes.map((s) => (
              <button
                key={s}
                type="button"
                aria-pressed={size === s}
                onClick={() => setSize(s)}
                className={`min-w-10 rounded-full border px-3 py-1 text-sm ${
                  size === s ? "border-accent bg-accent text-ink" : "border-white/20 hover:bg-white/10"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
        )}

        {product.colors.length > 1 && (
          <div className="flex flex-wrap gap-2" role="group" aria-label="Colour">
            {product.colors.map((c) => (
              <button
                key={c.name}
                type="button"
                aria-pressed={color === c.name}
                aria-label={c.name}
                title={c.name}
                onClick={() => setColor(c.name)}
                style={{ backgroundColor: c.hex }}
                className={`h-8 w-8 rounded-full border-2 ${color === c.name ? "border-accent ring-2 ring-accent/50" : "border-white/30"}`}
              />
            ))}
          </div>
        )}

        <div className="mt-auto flex items-center gap-3">
          <button
            type="button"
            onClick={() => void add()}
            disabled={!!missing || status === "adding" || product.stock <= 0}
            className="rounded-full bg-mist px-5 py-2 text-sm font-medium text-ink transition hover:scale-[1.02] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {missing
              ? `Choose a ${missing}`
              : status === "adding"
                ? "Adding…"
                : status === "added"
                  ? "Added ✓"
                  : "Add to cart"}
          </button>
          {inCart > 0 && <span className="text-xs text-mist/60">{inCart} in cart</span>}
        </div>
        {message && (
          <p role="alert" className="text-sm text-red-200">
            {message}
          </p>
        )}
      </div>
    </div>
  );
}

/** Shown beside the result: the items in the look, with size and colour choice and add to cart. */
export function OutfitPanel() {
  const selected = useKioskStore((s) => s.selected);
  const cart = useKioskStore((s) => s.cart);
  const backToBrowsing = useKioskStore((s) => s.backToBrowsing);
  const openCart = useKioskStore((s) => s.openCart);

  return (
    <div className="flex min-h-0 flex-col">
      <div className="px-2 pb-3">
        <p className="text-sm uppercase tracking-[0.3em] text-accent">Your look</p>
        <h2 className="text-2xl font-semibold">
          {selected.length} {selected.length === 1 ? "item" : "items"}
        </h2>
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-2 pb-4">
        {selected.map((p) => (
          <OutfitItem key={p.id} product={p} />
        ))}
      </div>
      <div className="flex items-center gap-3 border-t border-white/10 bg-black/40 px-4 py-3 backdrop-blur">
        <button
          type="button"
          onClick={backToBrowsing}
          className="flex-1 rounded-full bg-mist px-6 py-4 text-lg font-medium text-ink transition hover:scale-[1.02] active:scale-[0.98]"
        >
          Try another look
        </button>
        <button
          type="button"
          onClick={openCart}
          className="rounded-full border border-white/30 px-6 py-4 text-lg hover:bg-white/10"
        >
          View cart{cart && cart.item_count > 0 ? ` (${cart.item_count})` : ""}
        </button>
      </div>
    </div>
  );
}
