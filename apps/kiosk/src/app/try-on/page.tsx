"use client";

import Link from "next/link";
import { useEffect } from "react";
import { CartDrawer } from "@/components/CartDrawer";
import { CatalogPanel } from "@/components/CatalogPanel";
import { ConsentScreen } from "@/components/ConsentScreen";
import { MirrorStage } from "@/components/MirrorStage";
import { OutfitPanel } from "@/components/OutfitPanel";
import { type Phase, useKioskStore } from "@/store/useKioskStore";

const PHASE_LABEL: Partial<Record<Phase, string>> = {
  browsing: "Choose your look",
  countdown: "Get ready",
  uploading: "Sending your photo",
  working: "Creating your look",
  result: "Your look",
  error: "Something went wrong",
};

export default function TryOnPage() {
  const phase = useKioskStore((s) => s.phase);
  const cartCount = useKioskStore((s) => s.cart?.item_count ?? 0);
  const openCart = useKioskStore((s) => s.openCart);
  const reset = useKioskStore((s) => s.reset);

  // Leaving the page ends the session: closes the live connection and forgets the shopper.
  useEffect(() => () => reset(), [reset]);

  if (phase === "consent" || phase === "starting") return <ConsentScreen />;

  // While a look is being made the outfit must not change underneath it.
  const busy = phase === "countdown" || phase === "uploading" || phase === "working" || phase === "error";

  return (
    <main className="flex h-screen flex-col">
      <header className="flex items-center justify-between px-6 py-4">
        <Link href="/" className="text-sm uppercase tracking-[0.3em] text-mist/60 hover:text-mist">
          ← Exit
        </Link>
        <span className="rounded-full border border-white/15 px-3 py-1 text-xs uppercase tracking-widest text-mist/80">
          {PHASE_LABEL[phase]}
        </span>
        <button
          type="button"
          onClick={openCart}
          className="rounded-full border border-white/25 px-5 py-2 text-sm hover:bg-white/10"
          aria-label={`Cart, ${cartCount} items`}
        >
          Cart{cartCount > 0 ? ` (${cartCount})` : ""}
        </button>
      </header>

      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <MirrorStage />
        <aside className={`flex min-h-0 flex-col ${busy ? "pointer-events-none opacity-50" : ""}`} aria-busy={busy}>
          {phase === "result" ? <OutfitPanel /> : <CatalogPanel />}
        </aside>
      </div>

      <CartDrawer />
    </main>
  );
}
