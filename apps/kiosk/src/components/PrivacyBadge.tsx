"use client";

import { usePathname } from "next/navigation";
import { useState } from "react";
import { PrivacyNotice } from "@/components/PrivacyNotice";
import { retentionText } from "@/lib/privacy";
import { useKioskStore } from "@/store/useKioskStore";

/** While the camera is on, the capture screen shows the retention promise itself and the badge would cover its guidance. */
const STEPS_ASIDE = new Set(["capturing", "countdown"]);

/** Pages with their own privacy wording or no shopper: the staff page. */
const HIDDEN_ON = ["/staff", "/privacy"];

/**
 * A small, always-visible privacy note at the bottom of every mirror screen. It states the one fact shoppers care
 * about (how long their photo lives) and opens the full notice. It sits above the screens but below pop-ups, and
 * never covers the camera's guidance text or the main buttons (bottom-left corner, 64 px tall).
 */
export function PrivacyBadge() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const phase = useKioskStore((s) => s.phase);
  if (STEPS_ASIDE.has(phase) && path === "/try-on") return null;
  if (HIDDEN_ON.some((p) => path.startsWith(p))) return null;
  const onPhone = path.startsWith("/m");
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        data-testid="privacy-badge"
        aria-label={`Privacy: photos are deleted within ${retentionText()}. Tap to read more.`}
        className={`glass fixed bottom-4 left-4 z-40 flex min-h-16 items-center gap-3 rounded-full px-6 text-lg text-mist/80 hover:bg-white/10 ${onPhone ? "min-h-12 px-4 text-sm" : ""}`}
      >
        <span aria-hidden>🔒</span>
        Privacy: photos deleted within {retentionText()}
      </button>
      {open && <PrivacyNotice onClose={() => setOpen(false)} />}
    </>
  );
}
