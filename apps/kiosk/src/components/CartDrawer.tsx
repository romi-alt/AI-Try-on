"use client";

/* eslint-disable @next/next/no-img-element */
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { formatPkr } from "@/lib/money";
import type { CartItem } from "@/lib/types";
import { useKioskStore } from "@/store/useKioskStore";

const MAX_LINE_QUANTITY = 99; // the API's limit for one line

function describe(item: CartItem): string {
  const variant = [item.size, item.color].filter(Boolean).join(", ");
  return `${item.product.name}${variant ? `, ${variant}` : ""}`;
}

const stepperButton =
  "flex h-11 w-11 items-center justify-center rounded-full border border-white/25 text-xl hover:bg-white/10 disabled:opacity-40";

export function CartDrawer() {
  const open = useKioskStore((s) => s.cartOpen);
  const cart = useKioskStore((s) => s.cart);
  const close = useKioskStore((s) => s.closeCart);
  const removeFromCart = useKioskStore((s) => s.removeFromCart);
  const setCartQuantity = useKioskStore((s) => s.setCartQuantity);
  const placeOrder = useKioskStore((s) => s.placeOrder);
  const order = useKioskStore((s) => s.order);
  const dismissOrder = useKioskStore((s) => s.dismissOrder);
  const reset = useKioskStore((s) => s.reset);
  const router = useRouter();
  const [placing, setPlacing] = useState(false);
  const [working, setWorking] = useState<{ id: string; what: "remove" | "quantity" } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!open) setError(null);
  }, [open]);
  if (!open) return null;

  async function place() {
    setPlacing(true);
    setError(null);
    const result = await placeOrder();
    setPlacing(false);
    if (!result.ok) setError(result.message ?? null);
  }

  function finish() {
    reset(); // ends the session, so the next shopper starts clean
    router.push("/");
  }

  async function change(id: string, what: "remove" | "quantity", action: () => Promise<{ ok: boolean; message?: string }>) {
    setWorking({ id, what });
    setError(null);
    const result = await action();
    setWorking(null);
    if (!result.ok) setError(result.message ?? null);
  }

  const items = cart?.items ?? [];
  // Stock is shared by every size and colour of a product, so the limit is on the product's total in the cart.
  const inCart = (productId: string) =>
    items.filter((i) => i.product.id === productId).reduce((n, i) => n + i.quantity, 0);
  if (order) {
    return (
      <div className="fixed inset-0 z-50 flex justify-end" role="dialog" aria-modal="true" aria-label="Order placed">
        <div className="absolute inset-0 bg-black/60" />
        <aside className="relative flex h-full w-full max-w-md flex-col bg-[#15151b] shadow-2xl">
          <div className="border-b border-white/10 p-6">
            <h2 className="text-2xl font-semibold">Order placed</h2>
            <p className="mt-1 text-mist/70">Show this code at the counter to pay and collect your items.</p>
          </div>
          <div className="flex-1 space-y-6 overflow-y-auto p-6">
            <p
              className="rounded-2xl bg-white/5 py-6 text-center font-mono text-5xl font-semibold tracking-[0.3em]"
              aria-label={`Your order code is ${order.pickup_code.split("").join(" ")}`}
            >
              {order.pickup_code}
            </p>
            <ul className="space-y-3">
              {order.items.map((item, i) => (
                <li key={`${item.product_id}-${i}`} className="flex justify-between gap-4">
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{item.product_name}</span>
                    <span className="block text-sm text-mist/60">
                      {[item.size, item.color].filter(Boolean).join(" · ") || "—"} · {item.quantity} ×{" "}
                      {formatPkr(item.unit_price_pkr)}
                    </span>
                  </span>
                  <span className="font-medium tabular-nums">{formatPkr(item.line_total_pkr)}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="space-y-3 border-t border-white/10 p-6">
            <div className="flex items-baseline justify-between text-xl">
              <span>To pay at the counter</span>
              <span className="font-semibold tabular-nums">{formatPkr(order.subtotal_pkr)}</span>
            </div>
            <div className="flex gap-3">
              <button type="button" onClick={finish} className="min-h-12 flex-1 rounded-full bg-white px-6 font-medium text-black hover:bg-white/90">
                Done
              </button>
              <button
                type="button"
                onClick={() => {
                  dismissOrder();
                  close();
                }}
                className="min-h-12 rounded-full border border-white/25 px-6 hover:bg-white/10"
              >
                Keep shopping
              </button>
            </div>
          </div>
        </aside>
      </div>
    );
  }

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
                <p className="text-sm text-mist/80">{formatPkr(item.unit_price_pkr)} each</p>
                <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
                  <div className="flex items-center gap-2" role="group" aria-label={`Quantity of ${describe(item)}`}>
                    <button
                      type="button"
                      className={stepperButton}
                      aria-label={`Decrease quantity of ${describe(item)}`}
                      disabled={working !== null || placing || item.quantity <= 1}
                      onClick={() => change(item.id, "quantity", () => setCartQuantity(item.id, item.quantity - 1))}
                    >
                      −
                    </button>
                    <span className="min-w-8 text-center text-lg tabular-nums" aria-live="polite">
                      {item.quantity}
                    </span>
                    <button
                      type="button"
                      className={stepperButton}
                      aria-label={`Increase quantity of ${describe(item)}`}
                      disabled={
                        working !== null || placing ||
                        item.quantity >= MAX_LINE_QUANTITY ||
                        inCart(item.product.id) >= item.product.stock
                      }
                      onClick={() => change(item.id, "quantity", () => setCartQuantity(item.id, item.quantity + 1))}
                    >
                      +
                    </button>
                  </div>
                  <button
                    type="button"
                    onClick={() => change(item.id, "remove", () => removeFromCart(item.id))}
                    disabled={working !== null || placing}
                    aria-label={working?.id === item.id && working.what === "remove" ? undefined : `Remove ${describe(item)} from cart`}
                    className="min-h-11 rounded-full border border-white/25 px-4 text-sm hover:bg-white/10 disabled:opacity-50"
                  >
                    {working?.id === item.id && working.what === "remove" ? "Removing…" : "Remove"}
                  </button>
                </div>
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
          <button
            type="button"
            onClick={place}
            disabled={placing || working !== null || items.length === 0}
            className="!mt-4 min-h-14 w-full rounded-full bg-white px-6 text-lg font-medium text-black hover:bg-white/90 disabled:opacity-40"
          >
            {placing ? "Placing your order…" : "Place order"}
          </button>
          <p className="text-center text-sm text-mist/50">You pay at the counter. Nothing is charged here.</p>
        </div>
      </aside>
    </div>
  );
}
