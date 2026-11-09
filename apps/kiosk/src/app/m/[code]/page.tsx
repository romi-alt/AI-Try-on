"use client";

/* eslint-disable @next/next/no-img-element */
import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { createCheckoutAttempts } from "@/lib/mobileCheckout";
import { formatPkr } from "@/lib/money";
import type { MobileCheckout, MobileLook, Order } from "@/lib/types";

type Load = { kind: "loading" } | { kind: "error"; status: number; message: string } | { kind: "ready"; look: MobileLook };

function OrderConfirmation({ order, payment }: { order: Order; payment: MobileCheckout["payment"] | null }) {
  return (
    <section className="glass-strong space-y-4 rounded-3xl p-6 text-center" aria-label="Order confirmation">
      <p className="text-5xl">✓</p>
      <h2 className="text-3xl font-semibold">Order placed</h2>
      <p className="text-mist/80">Show this code at the counter to collect your items.</p>
      <p className="select-text text-5xl font-semibold tracking-[0.25em] text-accent" data-testid="pickup-code">
        {order.pickup_code}
      </p>
      <p className="text-lg text-mist/80">
        {order.item_count} {order.item_count === 1 ? "item" : "items"} · {formatPkr(order.subtotal_pkr)}
        {payment && (
          <>
            <br />
            {payment.status === "paid" ? "Paid" : "Payment pending"} ({payment.provider})
          </>
        )}
      </p>
      <ul className="space-y-1 text-left text-base text-mist/70">
        {order.items.map((i, n) => (
          <li key={n}>
            {i.quantity}× {i.product_name}
            {i.size ? ` · ${i.size}` : ""}
            {i.color ? ` · ${i.color}` : ""}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function MobilePage() {
  const { code } = useParams<{ code: string }>();
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [paying, setPaying] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [done, setDone] = useState<MobileCheckout | null>(null);
  const attempts = useMemo(() => createCheckoutAttempts(), []);

  const refresh = useCallback(async () => {
    try {
      const look = await api.getMobileLook(code);
      setLoad({ kind: "ready", look });
    } catch (e) {
      const status = e instanceof ApiError ? e.status : 0;
      setLoad((prev) => (prev.kind === "ready" && status === 0 ? prev : { kind: "error", status, message: e instanceof Error ? e.message : "Something went wrong" }));
    }
  }, [code]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function pay() {
    setPaying(true);
    setProblem(null);
    try {
      const result = await api.mobileCheckout(code, attempts.current());
      attempts.reset();
      if (result.payment.status === "pending" && result.payment.redirect_url) {
        window.location.href = result.payment.redirect_url; // the provider's own page takes the payment details
        return;
      }
      setDone(result);
    } catch (e) {
      attempts.failed(e);
      setProblem(e instanceof Error ? e.message : "Something went wrong");
      if (e instanceof ApiError && e.status === 409) await refresh(); // the cart changed under us: show the real one
    } finally {
      setPaying(false);
    }
  }

  if (load.kind === "loading") {
    return (
      <main className="grid min-h-screen place-items-center p-6" role="status">
        Loading your look…
      </main>
    );
  }
  if (load.kind === "error") {
    const text =
      load.status === 404
        ? "We couldn't find that link. Check the code under the QR on the mirror."
        : load.status === 410
          ? "This link has expired. Ask a team member for a new one."
          : load.message;
    return (
      <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-4 p-6 text-center">
        <p role="alert" className="text-xl">
          {text}
        </p>
        {load.status === 0 && (
          <button type="button" className="btn-primary" onClick={() => void refresh()}>
            Try again
          </button>
        )}
      </main>
    );
  }

  const { look } = load;
  const order = done?.order ?? look.order;
  const cart = look.cart;

  return (
    <main className="mx-auto min-h-screen max-w-md space-y-6 p-4 pb-12">
      <h1 className="pt-2 text-3xl font-semibold">Your look</h1>

      {look.look_image_url ? (
        <img src={look.look_image_url} alt="You wearing your chosen outfit" className="w-full rounded-3xl bg-white/5" />
      ) : (
        <p className="glass rounded-3xl p-6 text-center text-mist/70">Your look isn&apos;t available here, but your cart is saved.</p>
      )}

      {order ? (
        <OrderConfirmation order={order} payment={done?.payment ?? null} />
      ) : (
        <section aria-label="Cart" className="space-y-4">
          <h2 className="text-2xl font-semibold">Your cart</h2>
          {cart.items.length === 0 ? (
            <p className="glass rounded-3xl p-6 text-center text-mist/70">Your cart is empty.</p>
          ) : (
            <>
              <ul className="space-y-3">
                {cart.items.map((item) => (
                  <li key={item.id} className="glass flex gap-4 rounded-3xl p-3" data-testid="cart-line">
                    <img src={item.product.garment_image_url} alt="" className="h-24 w-20 flex-none rounded-2xl bg-[#e9e5da] object-contain p-1" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-lg font-medium">{item.product.name}</p>
                      <p className="text-base text-mist/70">
                        {[item.size && `Size ${item.size}`, item.color].filter(Boolean).join(" · ")}
                        {item.quantity > 1 ? ` · ×${item.quantity}` : ""}
                      </p>
                      <p className="mt-1 text-lg">{formatPkr(item.line_total_pkr)}</p>
                    </div>
                  </li>
                ))}
              </ul>
              <div className="flex items-center justify-between text-2xl font-semibold">
                <span>Total</span>
                <span data-testid="total">{formatPkr(cart.subtotal_pkr)}</span>
              </div>
              {problem && (
                <p role="alert" className="rounded-2xl bg-red-500/15 px-4 py-3 text-red-200">
                  {problem}
                </p>
              )}
              <button type="button" className="btn-primary w-full text-2xl" disabled={paying} onClick={() => void pay()}>
                {paying ? "Processing…" : `Pay ${formatPkr(cart.subtotal_pkr)}`}
              </button>
              <p className="text-center text-sm text-mist/60">Your items are held for you. Pay here, then collect at the counter.</p>
            </>
          )}
        </section>
      )}
    </main>
  );
}
