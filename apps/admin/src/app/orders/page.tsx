"use client";

import { useCallback, useEffect, useState } from "react";
import { Banner } from "@/components/Banner";
import { api, ApiError } from "@/lib/api";
import { config } from "@/lib/config";
import { formatPkr } from "@/lib/money";
import type { Order } from "@/lib/types";

export default function OrdersPage() {
  const [orders, setOrders] = useState<Order[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [typed, setTyped] = useState("");
  const [code, setCode] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    api
      .listOrders({ code })
      .then((o) => (setOrders(o), setError(null)))
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Couldn't load the orders."))
      .finally(() => setLoading(false));
  }, [code]);

  useEffect(load, [load]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Orders</h1>
        <button type="button" onClick={load} disabled={loading} className="rounded-md border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-100 disabled:opacity-50">
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {error && <Banner>{error}</Banner>}

      <form
        className="mb-3 flex items-center gap-2"
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
      <p className="mb-3 text-sm text-neutral-500">
        {code ? `Orders with the code ${code.toUpperCase()}.` : `The latest ${config.listLimit}.`} Shoppers pay at the counter; prices
        are as they were when the order was placed.
      </p>

      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="p-3">Code</th>
              <th className="p-3">Placed</th>
              <th className="p-3">Items</th>
              <th className="p-3 text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {(orders ?? []).map((o) => (
              <tr key={o.id} className="border-t border-neutral-100 align-top">
                <td className="p-3 font-mono text-base font-semibold tracking-widest">{o.pickup_code}</td>
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
              </tr>
            ))}
            {orders && orders.length === 0 && (
              <tr>
                <td colSpan={4} className="p-8 text-center text-neutral-500">
                  {code ? "No order has that code." : "No orders yet."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
