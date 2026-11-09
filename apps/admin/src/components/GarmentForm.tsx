"use client";

import { useState } from "react";
import { api, type Garment } from "@/lib/api";

const categories: Garment["category"][] = ["top", "bottom", "dress", "outerwear", "accessory"];

export function GarmentForm({ onSaved }: { onSaved: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!file) {
      setError("Choose a garment image (flat-lay or product shot, transparent PNG works best).");
      return;
    }
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const presign = await api.presignUpload(file.type);
      await api.uploadToPresigned(presign.upload_url, file);

      const price = String(form.get("price") ?? "").trim();
      await api.createGarment({
        sku: String(form.get("sku")),
        name: String(form.get("name")),
        brand: String(form.get("brand") || "") || null,
        category: form.get("category") as Garment["category"],
        color: String(form.get("color") || "") || null,
        price_cents: price ? Math.round(parseFloat(price) * 100) : null,
        image_key: presign.key,
        is_active: true,
      });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="grid grid-cols-2 gap-4 text-sm">
      <Field label="SKU" name="sku" required />
      <Field label="Name" name="name" required />
      <Field label="Brand" name="brand" />
      <Field label="Color" name="color" />
      <label className="flex flex-col gap-1">
        <span className="text-neutral-600">Category</span>
        <select name="category" className="rounded-md border border-neutral-300 px-3 py-2" defaultValue="top">
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
      </label>
      <Field label="Price (USD)" name="price" type="number" step="0.01" min="0" />
      <label className="col-span-2 flex flex-col gap-1">
        <span className="text-neutral-600">Image</span>
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          className="text-sm"
        />
      </label>
      {error && <p className="col-span-2 text-red-600">{error}</p>}
      <div className="col-span-2">
        <button
          type="submit"
          disabled={busy}
          className="rounded-md bg-neutral-900 px-4 py-2 text-white hover:bg-neutral-700 disabled:opacity-50"
        >
          {busy ? "Saving…" : "Save garment"}
        </button>
      </div>
    </form>
  );
}

function Field({
  label,
  name,
  ...rest
}: { label: string; name: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-neutral-600">{label}</span>
      <input name={name} {...rest} className="rounded-md border border-neutral-300 px-3 py-2" />
    </label>
  );
}
