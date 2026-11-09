"use client";

import { QRCodeSVG } from "qrcode.react";
import { useEffect, useState } from "react";
import { config } from "@/lib/config";
import { useKioskStore } from "@/store/useKioskStore";

/** The address a phone opens for a share code. The kiosk's own address unless NEXT_PUBLIC_PUBLIC_URL says otherwise. */
export function mobileUrl(code: string, base: string): string {
  return `${base.replace(/\/$/, "")}/m/${code}`;
}

/** Shown after "Add Selected to Cart": a QR code to carry the look and the cart to the shopper's phone. */
export function ShareModal() {
  const share = useKioskStore((s) => s.share);
  const dismiss = useKioskStore((s) => s.dismissShare);
  const [origin, setOrigin] = useState("");
  useEffect(() => setOrigin(window.location.origin), []);
  if (!share) return null;
  const base = config.publicUrl || origin;
  const url = mobileUrl(share.short_code, base);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-8 backdrop-blur-md" role="dialog" aria-modal="true" aria-label="Open on your phone">
      <div className="glass-strong w-full max-w-3xl space-y-8 rounded-[2.5rem] p-12 text-center">
        <h2 className="text-5xl font-semibold">Saved to your cart</h2>
        <p className="text-3xl text-mist/75">Scan with your phone to see your look and check out there.</p>
        <div className="mx-auto w-fit rounded-3xl bg-white p-6" data-testid="share-qr">
          <QRCodeSVG value={url} size={440} level="M" aria-label={`QR code for ${url}`} />
        </div>
        <p className="text-2xl text-mist/60">
          Or open <span className="break-all text-mist">{base ? `${base.replace(/^https?:\/\//, "")}/m` : "/m"}</span> and enter{" "}
          <span className="font-mono text-4xl tracking-[0.2em] text-accent">{share.short_code}</span>
        </p>
        <button type="button" className="btn-primary h-20 px-14 text-3xl" onClick={dismiss}>
          Done
        </button>
      </div>
    </div>
  );
}
