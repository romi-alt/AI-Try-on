"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { MAX_AMOUNT, parseWholeNumber } from "@/lib/productForm";
import type { Product } from "@/lib/types";

/** Stock you can change in place: type a number, then press Enter or leave the field. */
export function StockCell({ product, onSaved }: { product: Product; onSaved: (p: Product) => void }) {
  const [text, setText] = useState(String(product.stock));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => setText(String(product.stock)), [product.stock]);

  async function commit() {
    const next = parseWholeNumber(text);
    if (next === null || next > MAX_AMOUNT) {
      setError("Whole number, please");
      return;
    }
    if (next === product.stock) {
      setError(null);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onSaved(await api.updateProduct(product.id, { stock: next }));
    } catch (e) {
      setText(String(product.stock));
      setError(e instanceof ApiError ? e.message : "Couldn't save");
    } finally {
      setSaving(false);
    }
  }

  const tone = product.stock === 0 ? "border-red-300 bg-red-50" : product.stock <= 5 ? "border-amber-300 bg-amber-50" : "border-neutral-300";
  return (
    <div className="w-24">
      <input
        type="text"
        inputMode="numeric"
        value={text}
        disabled={saving}
        aria-label={`Stock for ${product.name}`}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => void commit()}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") {
            setText(String(product.stock));
            setError(null);
          }
        }}
        className={`w-full rounded-md border px-2 py-1 text-right tabular-nums disabled:opacity-50 ${tone}`}
      />
      {error && (
        <p role="alert" className="mt-1 text-xs text-red-600">
          {error}
        </p>
      )}
    </div>
  );
}
