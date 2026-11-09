"use client";

import { useCallback, useEffect, useState } from "react";
import { Banner } from "@/components/Banner";
import { api, ApiError } from "@/lib/api";
import { config } from "@/lib/config";
import { formatPkr } from "@/lib/money";
import type { Order, OrderStatus } from "@/lib/types";

type Filter = "all" | OrderStatus;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "all", label: "All" },
  { value: "placed", label: "Waiting" },
  { value: "collected", label: "Collected" },
  { value: "cancelled", label: "Cancelled" },
];

const PILL: Record<OrderStatus, { label: string; style: string }> = {
  placed: { label: "Waiting", style: "bg-amber-100 text-amber-800" },
  collected: { label: "Collected", style: "bg-green-100 text-green-800" },
  cancelled: { label: "Cancelled", style: "bg-neutral-200 text-neutral-600" },
};

const button = "rounded-md border px-3 py-1.5 text-sm disabled:opacity-50";

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [typed, setTyped] = useState("");
  const [code, setCode] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [busy, setBusy] = useState<string | null>(null);

  // `keepError`: refreshing after a refused change must not wipe the message explaining the refusal.
  const load = useCallback(
    (keepError = false) => {
      setLoading(true);
      return api
        .listOrders({ code, status: filter === "all" ? undefined : filter })
        .then((o) => (setOrders(o), keepError || setError(null)))
        .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Couldn't load the orders."))
        .finally(() => setLoading(false));
    },
    [code, filter],
  );

  useEffect(() => {
    void load();
  }, [load]);

  async function change(order: Order, status: "collected" | "cancelled") {
    if (
      status === "cancelled" &&
      !confirm(
        `Cancel order ${order.pickup_code}? Its ${order.item_count} ${order.item_count === 1 ? "item goes" : "items go"} back into stock. This can't be undone.`,
      )
    )
      return;
    setBusy(order.id);
    let refused = false;
    try {
      await api.setOrderStatus(order.id, status);
      setError(null);
    } catch (e) {
      refused = true;
      setError(e instanceof ApiError ? e.message : "Couldn't update the order.");
    } finally {
      setBusy(null);
    }
    await load(refused); // show what the server now says, and keep the reason if it refused
  }

  const nothing = code
    ? filter === "all"
      ? "No order has that code."
      : `No ${PILL[filter as OrderStatus].label.toLowerCase()} order has that code.`
    : filter === "all"
      ? "No orders yet."
      : `No ${PILL[filter as OrderStatus].label.toLowerCase()} orders.`;

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Orders</h1>
        <button type="button" onClick={() => void load()} disabled={loading} className={`${button} border-neutral-300 px-4 py-2 hover:bg-neutral-100`}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {error && <Banner>{error}</Banner>}

      <div className="mb-3 flex flex-wrap items-center gap-x-6 gap-y-3">
        <div className="flex gap-1" role="group" aria-label="Show orders">
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              aria-pressed={filter === f.value}
              onClick={() => setFilter(f.value)}
              className={`${button} ${filter === f.value ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300 hover:bg-neutral-100"}`}
            >
              {f.label}
            </button>
          ))}
        </div>

        <form
          className="flex items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setCode(typed.trim());
          }}
        >
          <label htmlFor="order-code" className="text-sm text-neutral-600">
            Pickup code
          </label>
          <input
            id="order-code"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            maxLength={12}
            autoComplete="off"
            placeholder="e.g. K7TQ4M"
            className="w-40 rounded-md border border-neutral-300 px-3 py-2 font-mono text-sm uppercase"
          />
          <button type="submit" className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700">
            Find
          </button>
          {code && (
            <button
              type="button"
              onClick={() => {
                setTyped("");
                setCode("");
              }}
              className="rounded-md border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-100"
            >
              Show all
            </button>
          )}
        </form>
      </div>
      <p className="mb-3 text-sm text-neutral-500">
        {code ? `Orders with the code ${code.toUpperCase()}.` : `The latest ${config.listLimit}.`} Shoppers pay at the counter; mark an order
        collected once they have paid and taken their items. Prices are as they were when the order was placed.
      </p>

      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="p-3">Code</th>
              <th className="p-3">Status</th>
              <th className="p-3">Placed</th>
              <th className="p-3">Items</th>
              <th className="p-3 text-right">Total</th>
              <th className="p-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {(orders ?? []).map((o) => (
              <tr key={o.id} className="border-t border-neutral-100 align-top">
                <td className="p-3 font-mono text-base font-semibold tracking-widest">{o.pickup_code}</td>
                <td className="p-3 whitespace-nowrap">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${PILL[o.status].style}`}>{PILL[o.status].label}</span>
                  {o.status_changed_at && <div className="mt-1 text-xs text-neutral-500">{new Date(o.status_changed_at).toLocaleString()}</div>}
                </td>
                <td className="p-3 whitespace-nowrap">{new Date(o.created_at).toLocaleString()}</td>
                <td className="p-3">
                  <ul className="space-y-0.5">
                    {o.items.map((i, n) => (
                      <li key={`${i.product_id}-${n}`}>
                        {i.quantity} × {i.product_name}
                        {[i.size, i.color].filter(Boolean).length > 0 && (
                          <span className="text-neutral-500"> ({[i.size, i.color].filter(Boolean).join(", ")})</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </td>
                <td className="p-3 text-right tabular-nums">{formatPkr(o.subtotal_pkr)}</td>
                <td className="p-3 text-right whitespace-nowrap">
                  {o.status === "placed" ? (
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => change(o, "collected")}
                        aria-label={`Mark order ${o.pickup_code} collected`}
                        className={`${button} border-green-700 bg-green-700 text-white hover:bg-green-800`}
                      >
                        {busy === o.id ? "Saving…" : "Mark collected"}
                      </button>
                      <button
                        type="button"
                        disabled={busy !== null}
                        onClick={() => change(o, "cancelled")}
                        aria-label={`Cancel order ${o.pickup_code}`}
                        className={`${button} border-neutral-300 hover:bg-neutral-100`}
                      >
                        Cancel
                      </button>
                    </div>
                  ) : (
                    <span className="text-neutral-400">—</span>
                  )}
                </td>
              </tr>
            ))}
            {orders && orders.length === 0 && (
              <tr>
                <td colSpan={6} className="p-8 text-center text-neutral-500">
                  {nothing}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
