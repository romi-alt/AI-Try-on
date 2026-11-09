"use client";

import { CartIcon, HelpIcon, MirrorIcon, ScannerIcon, SettingsIcon, ShopIcon } from "@/components/Icons";
import { type View, useKioskStore } from "@/store/useKioskStore";

const ITEMS: { view: View; label: string; Icon: (props: { className?: string }) => React.JSX.Element }[] = [
  { view: "shop", label: "Shop", Icon: ShopIcon },
  { view: "scanner", label: "Scanner", Icon: ScannerIcon },
  { view: "cart", label: "Cart", Icon: CartIcon },
  { view: "help", label: "Help", Icon: HelpIcon },
  { view: "settings", label: "Settings", Icon: SettingsIcon },
];

/** The left navigation: Shop, Scanner, Cart, Help, Settings. Every button is at least 64px, and these are 112px tall. */
export function Sidebar() {
  const view = useKioskStore((s) => s.view);
  const setView = useKioskStore((s) => s.setView);
  const openCart = useKioskStore((s) => s.openCart);
  const cartCount = useKioskStore((s) => s.cart?.item_count ?? 0);

  return (
    <nav aria-label="Main" className="glass m-4 mr-0 flex w-32 flex-none flex-col items-stretch gap-3 rounded-[2rem] p-3">
      <div className="flex h-24 items-center justify-center text-accent">
        <MirrorIcon className="h-12 w-12" />
      </div>
      {ITEMS.map(({ view: target, label, Icon }) => {
        const active = view === target;
        return (
          <button
            key={target}
            type="button"
            aria-current={active ? "page" : undefined}
            onClick={() => (target === "cart" ? openCart() : setView(target))}
            className={`relative flex min-h-28 flex-col items-center justify-center gap-2 rounded-3xl text-lg transition active:scale-[0.97] ${
              active ? "bg-mist text-ink" : "text-mist/80 hover:bg-white/10"
            }`}
          >
            <Icon />
            <span>{label}</span>
            {target === "cart" && cartCount > 0 && (
              <span
                aria-label={`${cartCount} ${cartCount === 1 ? "item" : "items"} in cart`}
                className="absolute right-2 top-2 flex h-9 min-w-9 items-center justify-center rounded-full bg-accent px-2 text-base font-semibold text-ink"
              >
                {cartCount}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
