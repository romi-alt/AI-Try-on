"use client";

/* eslint-disable @next/next/no-img-element */
import { useEffect, useState } from "react";
import { config } from "@/lib/config";
import type { Category } from "@/lib/types";
import { useKioskStore } from "@/store/useKioskStore";
import { ProductCard } from "./ProductCard";

const CATEGORIES: { value: Category | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "top", label: "Tops" },
  { value: "bottom", label: "Bottoms" },
  { value: "dress", label: "Dresses" },
  { value: "shoes", label: "Shoes" },
  { value: "bag", label: "Bags" },
  { value: "accessory", label: "Accessories" },
];

function SearchBox() {
  const applied = useKioskStore((s) => s.filters.search);
  const setFilters = useKioskStore((s) => s.setFilters);
  const [text, setText] = useState(applied);

  // Wait for a pause in typing before asking the server.
  useEffect(() => {
    if (text.trim() === applied.trim()) return;
    const t = setTimeout(() => setFilters({ search: text }), config.searchDebounceMs);
    return () => clearTimeout(t);
  }, [text, applied, setFilters]);

  return (
    <input
      type="search"
      value={text}
      onChange={(e) => setText(e.target.value)}
      placeholder="Search"
      aria-label="Search the catalog"
      className="w-44 rounded-full border border-white/15 bg-white/5 px-4 py-2 text-sm placeholder:text-mist/40 focus:border-accent focus:outline-none"
    />
  );
}

/** Filters, the product grid and the outfit tray. */
export function CatalogPanel() {
  const filters = useKioskStore((s) => s.filters);
  const products = useKioskStore((s) => s.products);
  const page = useKioskStore((s) => s.page);
  const pages = useKioskStore((s) => s.pages);
  const total = useKioskStore((s) => s.total);
  const catalogState = useKioskStore((s) => s.catalogState);
  const catalogError = useKioskStore((s) => s.catalogError);
  const selected = useKioskStore((s) => s.selected);
  const cameraReady = useKioskStore((s) => s.cameraReady);
  const setFilters = useKioskStore((s) => s.setFilters);
  const loadCatalog = useKioskStore((s) => s.loadCatalog);
  const toggleProduct = useKioskStore((s) => s.toggleProduct);
  const removeProduct = useKioskStore((s) => s.removeProduct);
  const startTryOn = useKioskStore((s) => s.startTryOn);

  const full = selected.length >= config.maxOutfitItems;
  const filtered = filters.category !== "all" || filters.onSale || filters.search.trim() !== "";
  const loading = catalogState === "loading";

  return (
    <div className="flex min-h-0 flex-col">
      <div className="flex flex-wrap items-center gap-2 px-2 pb-3">
        <div className="flex flex-wrap gap-2" role="tablist" aria-label="Categories">
          {CATEGORIES.map((c) => (
            <button
              key={c.value}
              type="button"
              role="tab"
              aria-selected={filters.category === c.value}
              onClick={() => setFilters({ category: c.value })}
              className={`rounded-full px-4 py-2 text-sm transition ${
                filters.category === c.value ? "bg-mist text-ink" : "bg-white/10 text-mist/80 hover:bg-white/15"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            aria-pressed={filters.onSale}
            onClick={() => setFilters({ onSale: !filters.onSale })}
            className={`rounded-full border px-4 py-2 text-sm transition ${
              filters.onSale ? "border-accent bg-accent text-ink" : "border-white/15 text-mist/80 hover:bg-white/10"
            }`}
          >
            On sale
          </button>
          <SearchBox />
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {loading && (
          <div className="grid grid-cols-3 gap-3" aria-busy="true">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="aspect-[3/4.6] animate-pulse rounded-2xl bg-white/5" />
            ))}
          </div>
        )}

        {catalogState === "error" && (
          <div className="flex flex-col items-center gap-4 py-12 text-center" role="alert">
            <p className="text-mist/80">{catalogError}</p>
            <button
              type="button"
              onClick={() => void loadCatalog(page === 0)}
              className="rounded-full border border-white/30 px-6 py-3 text-sm uppercase tracking-widest hover:bg-white/10"
            >
              Retry
            </button>
          </div>
        )}

        {!loading && catalogState !== "error" && products.length === 0 && (
          <div className="flex flex-col items-center gap-4 py-12 text-center">
            <p className="text-mist/70">Nothing matches{filtered ? " those filters" : " yet"}.</p>
            {filtered && (
              <button
                type="button"
                onClick={() => setFilters({ category: "all", onSale: false, search: "" })}
                className="rounded-full border border-white/30 px-6 py-3 text-sm uppercase tracking-widest hover:bg-white/10"
              >
                Clear filters
              </button>
            )}
          </div>
        )}

        {!loading && products.length > 0 && (
          <>
            <div className="grid grid-cols-3 gap-3">
              {products.map((p) => {
                const isSelected = selected.some((s) => s.id === p.id);
                return (
                  <ProductCard
                    key={p.id}
                    product={p}
                    selected={isSelected}
                    disabled={full && !isSelected}
                    onToggle={() => toggleProduct(p)}
                  />
                );
              })}
            </div>
            <div className="flex flex-col items-center gap-2 py-5">
              {page < pages && (
                <button
                  type="button"
                  onClick={() => void loadCatalog(false)}
                  disabled={catalogState === "loadingMore"}
                  className="rounded-full border border-white/30 px-6 py-3 text-sm uppercase tracking-widest hover:bg-white/10 disabled:opacity-50"
                >
                  {catalogState === "loadingMore" ? "Loading…" : "Show more"}
                </button>
              )}
              <p className="text-xs text-mist/50">
                Showing {products.length} of {total}
              </p>
            </div>
          </>
        )}
      </div>

      <div className="flex items-center gap-4 border-t border-white/10 bg-black/40 px-4 py-3 backdrop-blur">
        <div className="flex min-w-0 flex-1 items-center gap-2 overflow-x-auto">
          {selected.length === 0 ? (
            <p className="text-sm text-mist/60">Pick up to {config.maxOutfitItems} items to try on together.</p>
          ) : (
            selected.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => removeProduct(p.id)}
                aria-label={`Remove ${p.name}`}
                className="group relative h-14 w-11 flex-none overflow-hidden rounded-lg bg-[#e9e5da]"
              >
                <img src={p.garment_image_url} alt="" className="h-full w-full object-contain p-1" draggable={false} />
                <span className="absolute inset-0 flex items-center justify-center bg-black/60 text-lg opacity-0 transition group-hover:opacity-100">
                  ×
                </span>
              </button>
            ))
          )}
        </div>
        <button
          type="button"
          onClick={() => void startTryOn()}
          disabled={selected.length === 0 || !cameraReady}
          className="flex-none rounded-full bg-mist px-8 py-4 text-lg font-medium text-ink transition hover:scale-[1.02] active:scale-[0.98] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {!cameraReady ? "Waiting for camera…" : selected.length > 1 ? `Try on ${selected.length} items` : "Try it on"}
        </button>
      </div>
    </div>
  );
}
