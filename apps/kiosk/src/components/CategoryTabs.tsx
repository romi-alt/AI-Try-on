"use client";

import { TABS } from "@/lib/categories";
import { useKioskStore } from "@/store/useKioskStore";

/** Clothing, Accessories, Shoes, Bags, Flat 50% Off, New Arrivals. Scrolls sideways if the screen is narrower. */
export function CategoryTabs() {
  const tab = useKioskStore((s) => s.tab);
  const setTab = useKioskStore((s) => s.setTab);
  return (
    <div role="tablist" aria-label="Categories" className="scroll-x flex flex-none gap-2 px-6 pb-1">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={tab === t.id}
          onClick={() => setTab(t.id)}
          className="chip flex-1 whitespace-nowrap px-4 text-xl"
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}
