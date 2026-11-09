import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { DEFAULT_TAB, FLAT_OFF_PCT, NEW_ARRIVAL_DAYS, TABS, tabById } from "./categories";
import { catalogQueryFn, flattenPages, makeQueryClient, queryKeys } from "./queries";
import type { CatalogPage, Product } from "./types";

afterEach(() => vi.restoreAllMocks());

const product = (id: string): Product =>
  ({ id, name: id, category: "top", price_pkr: 1, sale_price_pkr: null, sizes: [], colors: [], stock: 1 }) as unknown as Product;
const page = (n: number, pages: number, ids: string[]): CatalogPage => ({
  items: ids.map(product),
  total: 0,
  page: n,
  page_size: 12,
  pages,
});

describe("the shop tabs", () => {
  it("are the six the design calls for, in order", () => {
    expect(TABS.map((t) => t.label)).toEqual(["Clothing", "Accessories", "Shoes", "Bags", "Flat 50% Off", "New Arrivals"]);
    expect(TABS.map((t) => t.id)).toEqual(["clothing", "accessories", "shoes", "bags", "sale", "new"]);
    expect(DEFAULT_TAB).toBe("clothing");
  });

  it("send the right filters to the API", async () => {
    const list = vi.spyOn(api, "listCatalog").mockResolvedValue(page(1, 1, []));
    for (const tab of TABS) await catalogQueryFn(tab.id, 2);
    const asked = list.mock.calls.map(([q]) => q);
    expect(asked[0]).toMatchObject({ categories: ["top", "bottom", "dress"], page: 2 }); // Clothing is three categories
    expect(asked[1]).toMatchObject({ categories: ["accessory"] });
    expect(asked[2]).toMatchObject({ categories: ["shoes"] });
    expect(asked[3]).toMatchObject({ categories: ["bag"] });
    expect(asked[4]).toMatchObject({ minDiscountPct: FLAT_OFF_PCT });
    expect(asked[4]?.categories).toBeUndefined(); // the sale tab spans every category
    expect(asked[5]).toMatchObject({ newWithinDays: NEW_ARRIVAL_DAYS });
  });

  it("fall back to the first tab for an unknown id", () => {
    expect(tabById("nope" as never).id).toBe("clothing");
  });
});

describe("paging", () => {
  it("keeps a product that appears on two pages once", () => {
    const flat = flattenPages([page(1, 2, ["a", "b", "c"]), page(2, 2, ["c", "d"])]);
    expect(flat.map((p) => p.id)).toEqual(["a", "b", "c", "d"]);
    expect(flattenPages(undefined)).toEqual([]);
  });
});

describe("the query client and keys", () => {
  it("retries once and does not refetch on focus", () => {
    const opts = makeQueryClient().getDefaultOptions().queries;
    expect(opts).toMatchObject({ retry: 1, refetchOnWindowFocus: false });
    expect(makeQueryClient()).toBeInstanceOf(QueryClient);
  });

  it("keys recommendations by the set of items, not the order they were picked in", () => {
    expect(queryKeys.recommend(["b", "a"])).toEqual(queryKeys.recommend(["a", "b"]));
    expect(queryKeys.recommend(["a"])).not.toEqual(queryKeys.recommend(["a", "b"]));
    expect(queryKeys.catalog("shoes")).not.toEqual(queryKeys.catalog("bags"));
  });

  it("can fetch pages through a real client", async () => {
    vi.spyOn(api, "listCatalog").mockImplementation(async ({ page: p = 1 } = {}) => page(p, 2, [`p${p}`]));
    const client = makeQueryClient();
    const result = await client.fetchInfiniteQuery({
      queryKey: queryKeys.catalog("shoes"),
      queryFn: ({ pageParam }) => catalogQueryFn("shoes", pageParam),
      initialPageParam: 1,
      getNextPageParam: (last) => (last.page < last.pages ? last.page + 1 : undefined),
      pages: 2,
    });
    expect(flattenPages(result.pages).map((p) => p.id)).toEqual(["p1", "p2"]);
  });
});
