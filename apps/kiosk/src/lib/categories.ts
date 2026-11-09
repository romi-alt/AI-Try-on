import type { CatalogQuery } from "./api";

/** "New Arrivals" shows products added in the last this many days. */
export const NEW_ARRIVAL_DAYS = 30;
/** "Flat 50% Off" shows products marked down by at least this much. */
export const FLAT_OFF_PCT = 50;

export type TabId = "clothing" | "accessories" | "shoes" | "bags" | "sale" | "new";

export type Tab = { id: TabId; label: string; query: Pick<CatalogQuery, "categories" | "minDiscountPct" | "newWithinDays"> };

/** The shop's top tabs, in the order shown. */
export const TABS: readonly Tab[] = [
  { id: "clothing", label: "Clothing", query: { categories: ["top", "bottom", "dress"] } },
  { id: "accessories", label: "Accessories", query: { categories: ["accessory"] } },
  { id: "shoes", label: "Shoes", query: { categories: ["shoes"] } },
  { id: "bags", label: "Bags", query: { categories: ["bag"] } },
  { id: "sale", label: `Flat ${FLAT_OFF_PCT}% Off`, query: { minDiscountPct: FLAT_OFF_PCT } },
  { id: "new", label: "New Arrivals", query: { newWithinDays: NEW_ARRIVAL_DAYS } },
];

export const DEFAULT_TAB: TabId = "clothing";

export function tabById(id: TabId): Tab {
  return TABS.find((t) => t.id === id) ?? TABS[0];
}
