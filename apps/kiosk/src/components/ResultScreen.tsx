"use client";

/* eslint-disable @next/next/no-img-element */
import { useState } from "react";
import { CheckIcon } from "@/components/Icons";
import { Price } from "@/components/Price";
import { RecommendationsPanel } from "@/components/RecommendationsPanel";
import { useImagePreload } from "@/hooks/useImagePreload";
import { type Look, type Selection, useKioskStore } from "@/store/useKioskStore";

/** "Look 1 / Look 2 ...": every look made this visit. */
function LookSwitcher({ looks, index, onPick }: { looks: Look[]; index: number; onPick: (i: number) => void }) {
  return (
    <div role="tablist" aria-label="Your looks" className="glass absolute bottom-8 left-1/2 flex -translate-x-1/2 gap-2 rounded-full p-2">
      {looks.map((look, i) => (
        <button key={look.jobId} type="button" role="tab" aria-selected={i === index} onClick={() => onPick(i)} className="chip min-w-32 rounded-full text-2xl">
          Look {i + 1}
        </button>
      ))}
    </div>
  );
}

/** The "Add to cart?" panel for one look: tick the pieces, choose sizes, then add, ask staff, or go back. */
function LookPanel({ look }: { look: Look }) {
  const addSelectionToCart = useKioskStore((s) => s.addSelectionToCart);
  const requestOutfit = useKioskStore((s) => s.requestOutfit);
  const backToShop = useKioskStore((s) => s.backToShop);

  const [checked, setChecked] = useState<Record<string, boolean>>(() => Object.fromEntries(look.items.map((i) => [i.product.id, true])));
  const [sizes, setSizes] = useState<Record<string, string | null>>(() => Object.fromEntries(look.items.map((i) => [i.product.id, i.size])));
  const [busy, setBusy] = useState<"cart" | "request" | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const chosen: Selection[] = look.items.filter((i) => checked[i.product.id]).map((i) => ({ ...i, size: sizes[i.product.id] ?? null }));
  const missingSize = chosen.find((i) => i.product.sizes.length > 1 && !i.size);

  function guard(): boolean {
    if (chosen.length === 0) return setNotice({ kind: "error", text: "Tick at least one item first." }), false;
    if (missingSize) return setNotice({ kind: "error", text: `Choose a size for ${missingSize.product.name}.` }), false;
    return true;
  }

  async function addToCart() {
    if (!guard()) return;
    setBusy("cart");
    setNotice(null);
    const result = await addSelectionToCart(chosen, look.jobId);
    setBusy(null);
    if (!result.ok) setNotice({ kind: "error", text: result.message });
  }

  async function request() {
    if (!guard()) return;
    setBusy("request");
    setNotice(null);
    const result = await requestOutfit(chosen);
    setBusy(null);
    setNotice(
      result.ok
        ? { kind: "ok", text: `A team member is on the way with ${result.sent === 1 ? "that item" : `those ${result.sent} items`}.` }
        : { kind: "error", text: result.message ?? "We couldn't reach a team member." },
    );
  }

  return (
    <aside className="glass-strong flex w-[460px] flex-none flex-col" aria-label="Add to cart">
      <div className="scroll-y min-h-0 flex-1 space-y-7 p-6">
        <h2 className="text-4xl font-semibold">Add to cart?</h2>

        <ul className="space-y-4">
          {look.items.map(({ product }) => {
            const on = !!checked[product.id];
            return (
              <li key={product.id} className="glass rounded-3xl p-4">
                <div className="flex items-center gap-4">
                  <button
                    type="button"
                    role="checkbox"
                    aria-checked={on}
                    aria-label={`Include ${product.name}`}
                    onClick={() => setChecked((c) => ({ ...c, [product.id]: !c[product.id] }))}
                    className={`flex h-16 w-16 flex-none items-center justify-center rounded-2xl border-2 ${on ? "border-accent bg-accent text-ink" : "border-white/30"}`}
                  >
                    {on && <CheckIcon />}
                  </button>
                  <img src={product.garment_image_url} alt="" draggable={false} className="h-24 w-20 flex-none rounded-2xl bg-[#e9e5da] object-contain p-1" />
                  <div className="min-w-0">
                    <p className="truncate text-xl">{product.name}</p>
                    <Price product={product} />
                  </div>
                </div>
                {on && product.sizes.length > 0 && (
                  <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label={`Size for ${product.name}`}>
                    {product.sizes.map((s) => (
                      <button key={s} type="button" aria-pressed={sizes[product.id] === s} onClick={() => (setSizes((z) => ({ ...z, [product.id]: s })), setNotice(null))} className="chip">
                        {s}
                      </button>
                    ))}
                  </div>
                )}
              </li>
            );
          })}
        </ul>

        <RecommendationsPanel productIds={look.items.map((i) => i.product.id)} />
      </div>

      <div className="space-y-3 border-t border-white/10 p-6">
        {notice && (
          <p role={notice.kind === "error" ? "alert" : "status"} className={`rounded-2xl px-4 py-3 text-xl ${notice.kind === "error" ? "bg-red-500/15 text-red-200" : "bg-emerald-500/15 text-emerald-200"}`}>
            {notice.text}
          </p>
        )}
        <button type="button" className="btn-primary h-20 w-full text-2xl" disabled={busy !== null} onClick={() => void addToCart()}>
          {busy === "cart" ? "Adding…" : "Add Selected to Cart"}
        </button>
        <button type="button" className="btn-ghost h-20 w-full text-2xl" disabled={busy !== null} onClick={() => void request()}>
          {busy === "request" ? "Asking…" : "Request Outfit"}
        </button>
        <button type="button" className="btn-ghost h-20 w-full text-2xl" onClick={backToShop}>
          Back to Shop
        </button>
      </div>
    </aside>
  );
}

/** The finished look: full height, fading in once it has fully loaded, beside the "Add to cart?" panel. */
export function ResultScreen() {
  const looks = useKioskStore((s) => s.looks);
  const index = useKioskStore((s) => s.lookIndex);
  const showLook = useKioskStore((s) => s.showLook);
  const photoUrl = useKioskStore((s) => s.photoUrl);
  const look = looks[index];
  const loaded = useImagePreload(look?.url);
  if (!look) return null;

  return (
    <div className="fixed inset-0 flex">
      <div className="relative min-w-0 flex-1 overflow-hidden bg-black">
        {/* Until the look has fully loaded, the blurred photo stays up: no half-painted image, no blank flash. */}
        {photoUrl && <img src={photoUrl} alt="" aria-hidden className="absolute inset-0 h-full w-full scale-125 object-cover opacity-50 blur-3xl" />}
        {loaded === "loaded" && (
          <img
            key={look.url}
            src={look.url}
            alt={`Look ${index + 1}: you wearing ${look.items.map((i) => i.product.name).join(", ")}`}
            className="absolute inset-0 h-full w-full animate-[fadein_0.7s_ease-out_both] object-contain"
            data-testid="look-image"
          />
        )}
        {loaded === "error" && (
          <div className="absolute inset-0 flex items-center justify-center p-10 text-center text-3xl" role="alert">
            We couldn&apos;t load your look. Check the connection, then tap Back to Shop and try again.
          </div>
        )}
        {looks.length > 1 && <LookSwitcher looks={looks} index={index} onPick={showLook} />}
      </div>
      <LookPanel key={look.jobId} look={look} />
    </div>
  );
}
