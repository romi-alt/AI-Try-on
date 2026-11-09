"use client";

/* eslint-disable @next/next/no-img-element */
import { useRouter } from "next/navigation";
import { useState } from "react";
import { formatPkr } from "@/lib/money";
import type { CartItem } from "@/lib/types";
import { useKioskStore } from "@/store/useKioskStore";

const MAX_LINE_QUANTITY = 99; // the API's limit for one line

function describe(item: CartItem): string {
  const variant = [item.size, item.color].filter(Boolean).join(", ");
  return `${item.product.name}${variant ? `, ${variant}` : ""}`;
}

const stepper = "flex h-16 w-16 items-center justify-center rounded-full border border-white/25 text-3xl active:scale-95 hover:bg-white/10 disabled:opacity-40";

/** The cart: change quantities, remove lines, pay at the counter, or take it to a phone. */
export function CartView() {
  const cart = useKioskStore((s) => s.cart);
  const order = useKioskStore((s) => s.order);
  const looks = useKioskStore((s) => s.looks);
  const removeFromCart = useKioskStore((s) => s.removeFromCart);
  const setCartQuantity = useKioskStore((s) => s.setCartQuantity);
  const placeOrder = useKioskStore((s) => s.placeOrder);
  const dismissOrder = useKioskStore((s) => s.dismissOrder);
  const addSelectionToCart = useKioskStore((s) => s.addSelectionToCart);
  const closeCart = useKioskStore((s) => s.closeCart);
  const reset = useKioskStore((s) => s.reset);
  const router = useRouter();

  const [working, setWorking] = useState<{ id: string; what: "remove" | "quantity" } | null>(null);
  const [placing, setPlacing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const items = cart?.items ?? [];
  // Stock is shared by every size and colour of a product, so the limit is on the product's total in the cart.
  const inCart = (productId: string) => items.filter((i) => i.product.id === productId).reduce((n, i) => n + i.quantity, 0);

  async function change(id: string, what: "remove" | "quantity", action: () => Promise<{ ok: boolean; message?: string }>) {
    setWorking({ id, what });
    setError(null);
    const result = await action();
    setWorking(null);
    if (!result.ok) setError(result.message ?? null);
  }

  async function place() {
    setPlacing(true);
    setError(null);
    const result = await placeOrder();
    setPlacing(false);
    if (!result.ok) setError(result.message ?? null);
  }

  async function payOnPhone() {
    setError(null);
    const result = await addSelectionToCart([], looks.at(-1)?.jobId ?? null);
    if (!result.ok) setError(result.message);
  }

  function finish() {
    reset(); // ends the session, so the next shopper starts clean
    router.push("/");
  }

  if (order) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-8 p-10" role="region" aria-label="Order placed">
        <div>
          <h1 className="text-5xl font-semibold">Order placed</h1>
          <p className="mt-2 text-2xl text-mist/70">Show this code at the counter to pay and collect your items.</p>
        </div>
        <p
          className="glass rounded-3xl py-10 text-center font-mono text-8xl font-semibold tracking-[0.3em]"
          aria-label={`Your order code is ${order.pickup_code.split("").join(" ")}`}
        >
          {order.pickup_code}
        </p>
        <ul className="scroll-y min-h-0 flex-1 space-y-4">
          {order.items.map((item, i) => (
            <li key={`${item.product_id}-${i}`} className="flex justify-between gap-6 text-2xl">
              <span className="min-w-0">
                <span className="block truncate font-medium">{item.product_name}</span>
                <span className="block text-xl text-mist/60">
                  {[item.size, item.color].filter(Boolean).join(" · ") || "—"} · {item.quantity} × {formatPkr(item.unit_price_pkr)}
                </span>
              </span>
              <span className="font-medium tabular-nums">{formatPkr(item.line_total_pkr)}</span>
            </li>
          ))}
        </ul>
        <div className="flex items-baseline justify-between text-4xl">
          <span>To pay at the counter</span>
          <span className="font-semibold tabular-nums">{formatPkr(order.subtotal_pkr)}</span>
        </div>
        <div className="flex gap-4">
          <button type="button" className="btn-primary h-24 flex-1 text-3xl" onClick={finish}>
            Done
          </button>
          <button type="button" className="btn-ghost h-24 text-3xl" onClick={() => (dismissOrder(), closeCart())}>
            Keep shopping
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <h1 className="p-10 pb-4 text-5xl font-semibold">Your cart</h1>

      <ul className="scroll-y min-h-0 flex-1 space-y-5 px-10 py-4">
        {items.length === 0 && <li className="mt-16 text-center text-3xl text-mist/60">Your cart is empty.</li>}
        {items.map((item) => (
          <li key={item.id} className="glass flex gap-6 rounded-3xl p-5">
            <div className="h-40 w-32 flex-none overflow-hidden rounded-2xl bg-[#e9e5da]">
              <img src={item.product.garment_image_url} alt="" className="h-full w-full object-contain p-1.5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-3xl font-medium">{item.product.name}</p>
              <p className="text-xl text-mist/60">{[item.size, item.color].filter(Boolean).join(" · ") || "—"}</p>
              <p className="text-xl text-mist/80">{formatPkr(item.unit_price_pkr)} each</p>
              <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-3">
                <div className="flex items-center gap-3" role="group" aria-label={`Quantity of ${describe(item)}`}>
                  <button
                    type="button"
                    className={stepper}
                    aria-label={`Decrease quantity of ${describe(item)}`}
                    disabled={working !== null || placing || item.quantity <= 1}
                    onClick={() => change(item.id, "quantity", () => setCartQuantity(item.id, item.quantity - 1))}
                  >
                    −
                  </button>
                  <span className="min-w-10 text-center text-3xl tabular-nums" aria-live="polite">
                    {item.quantity}
                  </span>
                  <button
                    type="button"
                    className={stepper}
                    aria-label={`Increase quantity of ${describe(item)}`}
                    disabled={working !== null || placing || item.quantity >= MAX_LINE_QUANTITY || inCart(item.product.id) >= item.product.stock}
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
                  className="btn-ghost h-16 text-xl"
                >
                  {working?.id === item.id && working.what === "remove" ? "Removing…" : "Remove"}
                </button>
              </div>
            </div>
            <p className="text-3xl font-medium tabular-nums">{formatPkr(item.line_total_pkr)}</p>
          </li>
        ))}
      </ul>

      {error && (
        <p role="alert" className="mx-10 mb-3 rounded-2xl bg-red-500/15 px-6 py-4 text-xl text-red-200">
          {error}
        </p>
      )}

      <div className="glass-strong m-6 mt-0 space-y-4 rounded-[2rem] p-8">
        <div className="flex items-baseline justify-between text-4xl">
          <span>Subtotal</span>
          <span className="font-semibold tabular-nums">{formatPkr(cart?.subtotal_pkr ?? 0)}</span>
        </div>
        <p className="text-xl text-mist/50">
          {cart?.item_count ?? 0} {(cart?.item_count ?? 0) === 1 ? "item" : "items"}
        </p>
        <div className="flex gap-4">
          <button type="button" onClick={place} disabled={placing || working !== null || items.length === 0} className="btn-primary h-24 flex-1 text-3xl">
            {placing ? "Placing your order…" : "Pay at the counter"}
          </button>
          <button type="button" onClick={payOnPhone} disabled={placing || working !== null || items.length === 0} className="btn-ghost h-24 flex-1 text-3xl">
            Pay on my phone
          </button>
        </div>
        <p className="text-center text-xl text-mist/50">Pay at the counter: you pay there, nothing is charged here.</p>
      </div>
    </div>
  );
}
