"use client";

/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Banner } from "@/components/Banner";
import { Pagination } from "@/components/Pagination";
import { ProductForm } from "@/components/ProductForm";
import { StockCell } from "@/components/StockCell";
import { api, ApiError } from "@/lib/api";
import { config } from "@/lib/config";
import { formatPkr } from "@/lib/money";
import { isBusy, PROCESSING_LABEL, PROCESSING_STYLE } from "@/lib/processing";
import { CATEGORIES, categoryLabel, type CatalogPage, type Category, type Product } from "@/lib/types";

const filterInput = "rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm";

export default function ProductsPage() {
  const [category, setCategory] = useState<Category | "all">("all");
  const [onSale, setOnSale] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [reloads, setReloads] = useState(0);

  const [data, setData] = useState<CatalogPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "success" | "error"; text: string } | null>(null);
  const [editing, setEditing] = useState<{ product: Product | null } | null>(null);

  // Wait for a pause in typing before asking the API.
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchText);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchText]);

  useEffect(() => {
    let cancelled = false; // a newer filter must not be overwritten by a slower, older answer
    setLoading(true);
    api
      .listProducts({ category, onSale, search, page })
      .then((res) => {
        if (cancelled) return;
        setData(res);
        setError(null);
        if (res.items.length === 0 && page > 1) setPage(res.pages || 1); // deleted the last item of the last page
      })
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Couldn't load the products."))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [category, onSale, search, page, reloads]);

  const reload = useCallback(() => setReloads((n) => n + 1), []);

  // While any product on screen is being processed, look again every few seconds so its status updates.
  const anyBusy = (data?.items ?? []).some(isBusy);
  useEffect(() => {
    if (!anyBusy) return;
    const t = setInterval(reload, config.processingPollMs);
    return () => clearInterval(t);
  }, [anyBusy, reload]);

  async function process(p: Product) {
    try {
      await api.processProduct(p.id);
      setNotice({ kind: "success", text: `Removing the background of “${p.name}”. This takes a minute.` });
      reload();
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't start processing." });
    }
  }

  async function embed(opts: { productIds?: string[]; onlyMissing?: boolean }, what: string) {
    try {
      await api.regenerateEmbeddings(opts);
      setNotice({ kind: "success", text: `Updating the embeddings for ${what}. Recommendations use the new ones as they finish.` });
      reload();
    } catch (e) {
      setNotice({ kind: "error", text: e instanceof ApiError ? e.message : "Couldn't start the embedding job." });
    }
  }

  async function remove(p: Product) {
    if (!confirm(`Delete “${p.name}”? This can't be undone.`)) return;
    try {
      await api.deleteProduct(p.id);
      setNotice({ kind: "success", text: `Deleted “${p.name}”.` });
      reload();
    } catch (e) {
      const message = e instanceof ApiError ? e.message : "Couldn't delete the product.";
      setNotice({
        kind: "error",
        text: e instanceof ApiError && e.status === 409 ? `${message}. Set its stock to 0 to mark it sold out instead.` : message,
      });
    }
  }

  function updated(p: Product) {
    setData((d) => (d ? { ...d, items: d.items.map((x) => (x.id === p.id ? p : x)) } : d));
  }

  const rows = data?.items ?? [];
  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Products</h1>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={() => void embed({ onlyMissing: true }, "products that have none")} className="rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm hover:bg-neutral-100">
            Embed missing
          </button>
          <button
            type="button"
            onClick={() => confirm("Recompute the embedding of every product? This can take a few minutes.") && void embed({}, "every product")}
            className="rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm hover:bg-neutral-100"
          >
            Re-embed all
          </button>
          <Link href="/products/import" className="rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm hover:bg-neutral-100">
            Import CSV
          </Link>
          <button type="button" onClick={() => setEditing({ product: null })} className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700">
            Add product
          </button>
        </div>
      </div>

      {notice && (
        <Banner kind={notice.kind} onDismiss={() => setNotice(null)}>
          {notice.text}
        </Banner>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <select
          aria-label="Category"
          className={filterInput}
          value={category}
          onChange={(e) => {
            setCategory(e.target.value as Category | "all");
            setPage(1);
          }}
        >
          <option value="all">All categories</option>
          {CATEGORIES.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={onSale}
            onChange={(e) => {
              setOnSale(e.target.checked);
              setPage(1);
            }}
          />
          On sale
        </label>
        <input type="search" aria-label="Search products" placeholder="Search by name" className={`${filterInput} w-64`} value={searchText} onChange={(e) => setSearchText(e.target.value)} />
        {loading && <span className="text-sm text-neutral-500">Loading…</span>}
      </div>

      {error && <Banner>{error}</Banner>}

      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="p-3">Image</th>
              <th className="p-3">Name</th>
              <th className="p-3">Price</th>
              <th className="p-3 text-right">Stock</th>
              <th className="p-3">Options</th>
              <th className="p-3">Image processing</th>
              <th className="p-3" />
            </tr>
          </thead>
          <tbody>
            {rows.map((p) => (
              <tr key={p.id} className="border-t border-neutral-100 align-middle">
                <td className="p-3">
                  <div className="flex h-16 w-12 items-center justify-center overflow-hidden rounded bg-neutral-100">
                    <img src={p.garment_image_url} alt="" className="h-full w-full object-contain" />
                  </div>
                </td>
                <td className="p-3">
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-neutral-500">{categoryLabel(p.category)}</div>
                </td>
                <td className="p-3 tabular-nums">
                  {p.on_sale ? (
                    <>
                      <div className="font-medium">{formatPkr(p.sale_price_pkr ?? p.price_pkr)}</div>
                      <s className="text-xs text-neutral-400">{formatPkr(p.price_pkr)}</s>
                    </>
                  ) : (
                    formatPkr(p.price_pkr)
                  )}
                </td>
                <td className="p-3">
                  <div className="flex justify-end">
                    <StockCell product={p} onSaved={updated} />
                  </div>
                </td>
                <td className="p-3">
                  <div className="text-xs text-neutral-600">{p.sizes.length ? p.sizes.join(" ") : "no sizes"}</div>
                  <div className="mt-1 flex gap-1">
                    {p.colors.map((c) => (
                      <span key={c.name} title={c.name} className="h-4 w-4 rounded-full border border-neutral-300" style={{ backgroundColor: c.hex }} />
                    ))}
                  </div>
                </td>
                <td className="p-3">
                  <span
                    title={p.processing_error ?? undefined}
                    className={`rounded-full px-2 py-0.5 text-xs font-medium ${PROCESSING_STYLE[p.processing_status]}`}
                    data-testid="processing-status"
                  >
                    {PROCESSING_LABEL[p.processing_status]}
                  </span>
                  {p.processing_status === "failed" && p.processing_error && <div className="mt-1 max-w-[14rem] text-xs text-red-700">{p.processing_error}</div>}
                  <div className="mt-1 text-xs text-neutral-500">{p.has_embedding ? "Embedded" : "No embedding"}</div>
                </td>
                <td className="p-3 text-right">
                  <button type="button" disabled={isBusy(p)} onClick={() => void process(p)} className="mr-3 text-xs text-neutral-700 hover:underline disabled:cursor-not-allowed disabled:opacity-40">
                    {p.processing_status === "done" ? "Reprocess image" : "Remove background"}
                  </button>
                  <button type="button" onClick={() => void embed({ productIds: [p.id] }, `“${p.name}”`)} className="mr-3 text-xs text-neutral-700 hover:underline">
                    Re-embed
                  </button>
                  <button type="button" onClick={() => setEditing({ product: p })} className="mr-3 text-xs text-neutral-700 hover:underline">
                    Edit
                  </button>
                  <button type="button" onClick={() => void remove(p)} className="text-xs text-red-600 hover:underline">
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {!loading && !error && rows.length === 0 && (
              <tr>
                <td colSpan={7} className="p-8 text-center text-neutral-500">
                  {category !== "all" || onSale || search ? "No products match those filters." : <>No products yet. Add one, or run <code>make seed</code>.</>}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <Pagination page={data?.page ?? 1} pages={data?.pages ?? 1} total={data?.total ?? 0} pageSize={config.productsPageSize} onPage={setPage} />

      {editing && (
        <ProductForm
          key={editing.product?.id ?? "new"}
          product={editing.product}
          onClose={() => setEditing(null)}
          onSaved={(_, message) => {
            setEditing(null);
            setNotice({ kind: "success", text: message });
            reload();
          }}
        />
      )}
    </div>
  );
}
