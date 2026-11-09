"use client";

/* eslint-disable @next/next/no-img-element */
import { useEffect, useState } from "react";
import { formatPkr } from "@/lib/money";
import type { CartItem } from "@/lib/types";
import { useKioskStore } from "@/store/useKioskStore";

function removeLabel(item: CartItem): string {
  const variant = [item.size, item.color].filter(Boolean).join(", ");
  return `Remove ${item.product.name}${variant ? `, ${variant}` : ""} from cart`;
}

export function CartDrawer() {
  const open = useKioskStore((s) => s.cartOpen);
  const cart = useKioskStore((s) => s.cart);
  const close = useKioskStore((s) => s.closeCart);
  const removeFromCart = useKioskStore((s) => s.removeFromCart);
  const [removing, setRemoving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) setError(null);
  }, [open]);
  if (!open) return null;

  async function remove(itemId: string) {
    setRemoving(itemId);
    setError(null);
    const result = await removeFromCart(itemId);
    setRemoving(null);
    if (!result.ok) setError(result.message);
  }

  const items = cart?.items ?? [];
  return (
    <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Your cart">
      <button type="button" aria-label="Close cart" onClick={close} className="absolute inset-0 bg-black/60" />
      <aside className="relative flex h-full w-full max-w-md flex-col bg-[#15151b] shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/10 p-6">
          <h2 className="text-2xl font-semibold">Your cart</h2>
          <button type="button" onClick={close} className="rounded-full border border-white/25 px-4 py-2 text-sm hover:bg-white/10">
            Close
          </button>
        </div>

        <ul className="flex-1 space-y-4 overflow-y-auto p-6">
          {items.length === 0 && <li className="text-mist/60">Your cart is empty.</li>}
          {items.map((item) => (
            <li key={item.id} className="flex gap-4">
              <div className="h-20 w-16 flex-none overflow-hidden rounded-lg bg-[#e9e5da]">
                <img src={item.product.garment_image_url} alt="" className="h-full w-full object-contain p-1" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{item.product.name}</p>
                <p className="text-sm text-mist/60">{[item.size, item.color].filter(Boolean).join(" · ") || "—"}</p>
                <p className="text-sm text-mist/80">
                  {item.quantity} × {formatPkr(item.unit_price_pkr)}
                </p>
                <button
                  type="button"
                  onClick={() => remove(item.id)}
                  disabled={removing !== null}
                  aria-label={removing === item.id ? undefined : removeLabel(item)}
                  className="mt-2 min-h-11 rounded-full border border-white/25 px-4 text-sm hover:bg-white/10 disabled:opacity-50"
                >
                  {removing === item.id ? "Removing…" : "Remove"}
                </button>
              </div>
              <p className="font-medium tabular-nums">{formatPkr(item.line_total_pkr)}</p>
            </li>
          ))}
        </ul>

        {error && (
          <p role="alert" className="mx-6 mb-2 rounded-lg bg-red-500/15 px-4 py-3 text-sm text-red-200">
            {error}
          </p>
        )}

        <div className="space-y-1 border-t border-white/10 p-6">
          <div className="flex items-baseline justify-between text-xl">
            <span>Subtotal</span>
            <span className="font-semibold tabular-nums">{formatPkr(cart?.subtotal_pkr ?? 0)}</span>
          </div>
          <p className="text-sm text-mist/50">
            {cart?.item_count ?? 0} {(cart?.item_count ?? 0) === 1 ? "item" : "items"}
          </p>
        </div>
      </aside>
    </div>
  );
}
