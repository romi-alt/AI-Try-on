"use client";

import { useEffect, useState } from "react";
import { Banner } from "@/components/Banner";
import { api, ApiError } from "@/lib/api";
import { formatRate, PERIODS } from "@/lib/analytics";
import type { Analytics } from "@/lib/types";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums">{value}</p>
      {hint && <p className="mt-1 text-xs text-neutral-500">{hint}</p>}
    </div>
  );
}

function RateBar({ rate }: { rate: number | null }) {
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-neutral-100" aria-hidden>
        <div className="h-full bg-neutral-800" style={{ width: `${Math.round((rate ?? 0) * 100)}%` }} />
      </div>
      <span className="tabular-nums">{formatRate(rate)}</span>
    </div>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState<number>(30);
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .analytics(days)
      .then((a) => {
        if (cancelled) return;
        setData(a);
        setError(null);
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Couldn't load the analytics."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [days]);

  return (
    <div className="max-w-5xl">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Analytics</h1>
        <div className="flex items-center gap-3">
          {loading && <span className="text-sm text-neutral-500">Loading…</span>}
          <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))} className="rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm">
            {PERIODS.map((p) => (
              <option key={p.days} value={p.days}>
                {p.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && <Banner>{error}</Banner>}

      {data && (
        <div className="space-y-8">
          <div className="grid grid-cols-3 gap-4">
            <Tile label="Try-ons" value={String(data.tryons)} hint="Finished looks" />
            <Tile label="Led to a cart add" value={String(data.tryons_with_cart)} hint="Looks after which a tried-on item was added" />
            <Tile label="Try-on to cart rate" value={formatRate(data.cart_rate)} />
          </div>

          <section>
            <h2 className="mb-3 text-lg font-medium">Try-ons per product</h2>
            <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
              <table className="w-full text-sm">
                <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <tr>
                    <th className="p-3">Product</th>
                    <th className="p-3 text-right">Try-ons</th>
                    <th className="p-3 text-right">Added to cart</th>
                    <th className="p-3">Rate</th>
                  </tr>
                </thead>
                <tbody>
                  {data.products.map((p) => (
                    <tr key={p.product_id} className="border-t border-neutral-100">
                      <td className="p-3">
                        <div className="font-medium">{p.name}</div>
                        {p.category && <div className="text-xs text-neutral-500">{p.category}</div>}
                      </td>
                      <td className="p-3 text-right tabular-nums">{p.tryons}</td>
                      <td className="p-3 text-right tabular-nums">{p.added_to_cart}</td>
                      <td className="p-3">
                        <RateBar rate={p.cart_rate} />
                      </td>
                    </tr>
                  ))}
                  {data.products.length === 0 && (
                    <tr>
                      <td colSpan={4} className="p-8 text-center text-neutral-500">
                        No finished try-ons in this period.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>

          <section>
            <h2 className="mb-1 text-lg font-medium">Top recommended pairings</h2>
            <p className="mb-3 text-sm text-neutral-500">Suggestions shoppers added to a look from “More styles” or “Complete your look”, with the item they were added to.</p>
            <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
              <table className="w-full text-sm">
                <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
                  <tr>
                    <th className="p-3">Look item</th>
                    <th className="p-3">Suggested item</th>
                    <th className="p-3 text-right">Tried together</th>
                    <th className="p-3 text-right">Suggestion added to cart</th>
                  </tr>
                </thead>
                <tbody>
                  {data.pairings.map((p) => (
                    <tr key={`${p.base_product_id}:${p.recommended_product_id}`} className="border-t border-neutral-100">
                      <td className="p-3">{p.base_name}</td>
                      <td className="p-3">{p.recommended_name}</td>
                      <td className="p-3 text-right tabular-nums">{p.tryons}</td>
                      <td className="p-3 text-right tabular-nums">{p.added_to_cart}</td>
                    </tr>
                  ))}
                  {data.pairings.length === 0 && (
                    <tr>
                      <td colSpan={4} className="p-8 text-center text-neutral-500">
                        No suggestions were used in this period.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </div>
  );
}
