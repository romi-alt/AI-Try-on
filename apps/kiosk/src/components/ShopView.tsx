"use client";

import { CategoryTabs } from "@/components/CategoryTabs";
import { ProductTile } from "@/components/ProductTile";
import { SelectedTray } from "@/components/SelectedTray";
import { flattenPages, useCatalog } from "@/lib/queries";
import { useKioskStore } from "@/store/useKioskStore";

/** Selected-items tray, category tabs and the three-column product grid. */
export function ShopView() {
  const tab = useKioskStore((s) => s.tab);
  const selected = useKioskStore((s) => s.selected);
  const openDetail = useKioskStore((s) => s.openDetail);
  const query = useCatalog(tab);
  const products = flattenPages(query.data?.pages);
  const chosen = new Set(selected.map((i) => i.product.id));

  return (
    <>
      <SelectedTray />
      <div className="mt-4">
        <CategoryTabs />
      </div>

      <div className="scroll-y mt-4 min-h-0 flex-1 px-6 pb-24" aria-busy={query.isPending}>
        {query.isPending && (
          <div className="grid grid-cols-3 gap-4" aria-label="Loading items">
            {Array.from({ length: 6 }, (_, i) => (
              <div key={i} className="glass h-96 animate-pulse rounded-3xl" />
            ))}
          </div>
        )}

        {query.isError && (
          <div role="alert" className="glass mx-auto mt-16 max-w-xl space-y-5 rounded-3xl p-8 text-center">
            <p className="text-2xl">{query.error instanceof Error ? query.error.message : "We couldn't load the items."}</p>
            <button type="button" className="btn-primary" onClick={() => query.refetch()}>
              Try again
            </button>
          </div>
        )}

        {query.isSuccess && products.length === 0 && (
          <p className="mt-24 text-center text-2xl text-mist/60">Nothing here right now. Try another category.</p>
        )}

        {products.length > 0 && (
          <div className="grid grid-cols-3 gap-4">
            {products.map((p) => (
              <ProductTile key={p.id} product={p} selected={chosen.has(p.id)} onOpen={openDetail} />
            ))}
          </div>
        )}

        {query.hasNextPage && (
          <div className="mt-6 flex justify-center">
            <button type="button" className="btn-ghost" disabled={query.isFetchingNextPage} onClick={() => query.fetchNextPage()}>
              {query.isFetchingNextPage ? "Loading…" : "Show more"}
            </button>
          </div>
        )}
      </div>
    </>
  );
}
