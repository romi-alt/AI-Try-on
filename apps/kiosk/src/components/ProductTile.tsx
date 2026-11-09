"use client";

/* eslint-disable @next/next/no-img-element */
import { CheckIcon } from "@/components/Icons";
import { Price } from "@/components/Price";
import { discountPercent } from "@/lib/money";
import type { Product } from "@/lib/types";

export function ProductTile({ product, selected, onOpen }: { product: Product; selected: boolean; onOpen: (p: Product) => void }) {
  const soldOut = product.stock <= 0;
  const off = discountPercent(product.price_pkr, product.sale_price_pkr);
  return (
    <button
      type="button"
      onClick={() => onOpen(product)}
      aria-label={`${product.name}, ${soldOut ? "sold out" : `Rs ${product.current_price_pkr}`}${selected ? ", in your outfit" : ""}`}
      className={`glass relative flex min-h-64 flex-col overflow-hidden rounded-3xl text-left transition active:scale-[0.98] ${
        selected ? "ring-4 ring-accent" : ""
      }`}
    >
      <div className="relative aspect-[3/4] w-full bg-[#e9e5da]">
        <img src={product.garment_image_url} alt="" draggable={false} className="h-full w-full object-contain p-3" />
        {off > 0 && !soldOut && (
          <span className="absolute left-3 top-3 rounded-full bg-accent px-4 py-1.5 text-lg font-semibold text-ink">-{off}%</span>
        )}
        {selected && (
          <span className="absolute right-3 top-3 flex h-12 w-12 items-center justify-center rounded-full bg-accent text-ink">
            <CheckIcon />
          </span>
        )}
        {soldOut && (
          <span className="absolute inset-0 flex items-center justify-center bg-black/55 text-2xl uppercase tracking-widest">Sold out</span>
        )}
      </div>
      <div className="space-y-1 p-4">
        <p className="line-clamp-2 min-h-[3.25rem] text-xl leading-snug">{product.name}</p>
        <Price product={product} />
      </div>
    </button>
  );
}
