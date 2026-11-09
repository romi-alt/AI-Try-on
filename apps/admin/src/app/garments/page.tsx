"use client";

/* eslint-disable @next/next/no-img-element */
import { useEffect, useState } from "react";
import { api, type Garment } from "@/lib/api";
import { GarmentForm } from "@/components/GarmentForm";

export default function GarmentsPage() {
  const [garments, setGarments] = useState<Garment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const refresh = () => api.listGarments().then(setGarments).catch((e: Error) => setError(e.message));

  useEffect(() => {
    void refresh();
  }, []);

  const toggleActive = async (g: Garment) => {
    await api.updateGarment(g.id, { is_active: !g.is_active });
    await refresh();
  };

  const remove = async (g: Garment) => {
    if (!confirm(`Delete "${g.name}"? This cannot be undone.`)) return;
    await api.deleteGarment(g.id);
    await refresh();
  };

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Garments</h1>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700"
        >
          {showForm ? "Close" : "Add garment"}
        </button>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {showForm && (
        <div className="mb-8 rounded-lg border border-neutral-200 bg-white p-5">
          <GarmentForm
            onSaved={() => {
              setShowForm(false);
              void refresh();
            }}
          />
        </div>
      )}

      <table className="w-full overflow-hidden rounded-lg border border-neutral-200 bg-white text-sm">
        <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
          <tr>
            <th className="p-3">Image</th>
            <th className="p-3">SKU</th>
            <th className="p-3">Name</th>
            <th className="p-3">Category</th>
            <th className="p-3">Price</th>
            <th className="p-3">Active</th>
            <th className="p-3" />
          </tr>
        </thead>
        <tbody>
          {garments.map((g) => (
            <tr key={g.id} className="border-t border-neutral-100">
              <td className="p-3">
                <img src={g.image_url} alt="" className="h-14 w-12 rounded object-cover" />
              </td>
              <td className="p-3 font-mono text-xs">{g.sku}</td>
              <td className="p-3">
                <div>{g.name}</div>
                <div className="text-xs text-neutral-500">{g.brand}</div>
              </td>
              <td className="p-3">{g.category}</td>
              <td className="p-3 tabular-nums">
                {g.price_cents != null ? `$${(g.price_cents / 100).toFixed(2)}` : "–"}
              </td>
              <td className="p-3">
                <button
                  type="button"
                  onClick={() => void toggleActive(g)}
                  className={`rounded-full px-2 py-0.5 text-xs ${
                    g.is_active ? "bg-green-100 text-green-800" : "bg-neutral-200 text-neutral-600"
                  }`}
                >
                  {g.is_active ? "active" : "hidden"}
                </button>
              </td>
              <td className="p-3 text-right">
                <button type="button" onClick={() => void remove(g)} className="text-xs text-red-600 hover:underline">
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {garments.length === 0 && (
            <tr>
              <td colSpan={7} className="p-6 text-center text-neutral-500">
                No garments. Add one above or run <code>make seed</code>.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
