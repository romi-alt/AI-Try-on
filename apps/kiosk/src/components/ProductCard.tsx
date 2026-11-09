"use client";

/* eslint-disable @next/next/no-img-element */
import { discountPercent, formatPkr } from "@/lib/money";
import type { Product } from "@/lib/types";

export function Price({ product, className = "" }: { product: Product; className?: string }) {
  return (
    <span className={`flex items-baseline gap-2 ${className}`}>
      <span className={product.on_sale ? "font-medium text-accent" : ""}>{formatPkr(product.current_price_pkr)}</span>
      {product.on_sale && <s className="text-xs text-mist/50">{formatPkr(product.price_pkr)}</s>}
    </span>
  );
}

type Props = { product: Product; selected: boolean; disabled: boolean; onToggle: () => void };

export function ProductCard({ product, selected, disabled, onToggle }: Props) {
  const soldOut = product.stock <= 0;
  const off = discountPercent(product.price_pkr, product.sale_price_pkr);

  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={disabled || soldOut}
      aria-pressed={selected}
      className={`group relative flex flex-col gap-2 rounded-2xl border-2 p-2 text-left transition ${
        selected ? "border-accent bg-white/10" : "border-transparent bg-white/5 hover:bg-white/10"
      } disabled:cursor-not-allowed disabled:opacity-50`}
    >
      <div className="relative aspect-[3/4] overflow-hidden rounded-xl bg-[#e9e5da]">
        <img src={product.garment_image_url} alt="" className="h-full w-full object-contain p-3" draggable={false} />
        {off > 0 && (
          <span className="absolute left-2 top-2 rounded-full bg-accent px-2 py-0.5 text-xs font-semibold text-ink">
            -{off}%
          </span>
        )}
        {selected && (
          <span className="absolute right-2 top-2 flex h-7 w-7 items-center justify-center rounded-full bg-accent text-ink" aria-hidden>
            ✓
          </span>
        )}
        {soldOut && (
          <span className="absolute inset-0 flex items-center justify-center bg-black/55 text-sm font-medium uppercase tracking-widest">
            Sold out
          </span>
        )}
      </div>
      <div className="px-1 pb-1">
        <p className="truncate text-sm font-medium">{product.name}</p>
        <Price product={product} className="text-sm text-mist/80" />
      </div>
    </button>
  );
}
