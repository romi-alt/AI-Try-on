"use client";

import { CartView } from "@/components/CartView";
import { HelpView } from "@/components/HelpView";
import { ProductDetail } from "@/components/ProductDetail";
import { ScannerView } from "@/components/ScannerView";
import { SettingsView } from "@/components/SettingsView";
import { ShopView } from "@/components/ShopView";
import { Sidebar } from "@/components/Sidebar";
import { useKioskStore } from "@/store/useKioskStore";

/** The browsing layout: the sidebar on the left, and the current view (shop, scanner, cart, help, settings). */
export function AppShell() {
  const view = useKioskStore((s) => s.view);
  return (
    <div className="fixed inset-0 flex">
      <Sidebar />
      <main className="relative flex min-w-0 flex-1 flex-col overflow-hidden pt-0">
        {view === "shop" && <ShopView />}
        {view === "scanner" && <ScannerView />}
        {view === "cart" && <CartView />}
        {view === "help" && <HelpView />}
        {view === "settings" && <SettingsView />}
        <ProductDetail />
      </main>
    </div>
  );
}
