import { QueryClient, useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { type TabId, tabById } from "./categories";
import type { CatalogPage, Product } from "./types";

/**
 * Defaults for a kiosk: a failed request is retried once (the next shopper should not wait through a long backoff),
 * and a screen the shopper comes back to is not refetched just because the window regained focus.
 */
export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: 1, retryDelay: 800, refetchOnWindowFocus: false, staleTime: 30_000 },
    },
  });
}

export const queryKeys = {
  catalog: (tab: TabId) => ["catalog", tab] as const,
  recommend: (ids: readonly string[]) => ["recommend", [...ids].sort().join(",")] as const,
};

/** The products of every loaded page, in order, with a product that appears on two pages (the catalog moved) kept once. */
export function flattenPages(pages: readonly CatalogPage[] | undefined): Product[] {
  const seen = new Set<string>();
  const out: Product[] = [];
  for (const page of pages ?? []) {
    for (const p of page.items) {
      if (!seen.has(p.id)) {
        seen.add(p.id);
        out.push(p);
      }
    }
  }
  return out;
}

export function catalogQueryFn(tab: TabId, page: number): Promise<CatalogPage> {
  return api.listCatalog({ ...tabById(tab).query, page });
}

/** The shop grid for a tab, paged ("Show more" fetches the next page). */
export function useCatalog(tab: TabId) {
  return useInfiniteQuery({
    queryKey: queryKeys.catalog(tab),
    queryFn: ({ pageParam }) => catalogQueryFn(tab, pageParam),
    initialPageParam: 1,
    getNextPageParam: (last) => (last.page < last.pages ? last.page + 1 : undefined),
  });
}

/** Suggestions for the chosen items. Nothing is requested for an empty selection. */
export function useRecommendations(productIds: readonly string[]) {
  return useQuery({
    queryKey: queryKeys.recommend(productIds),
    queryFn: () => api.recommend([...productIds]),
    enabled: productIds.length > 0,
    staleTime: 60_000,
    placeholderData: (previous) => previous, // keep showing the last suggestions while the new ones load
  });
}
