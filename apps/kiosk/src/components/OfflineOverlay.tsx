"use client";

import { useConnectivityStore } from "@/store/useConnectivityStore";
import { useKioskStore } from "@/store/useKioskStore";

/** While one of these is under way the shopper must not be interrupted: a banner tells them, nothing blocks. */
const KEEP_GOING = new Set(["capturing", "countdown", "uploading", "working"]);

/**
 * What the shopper sees when the mirror cannot reach its server.
 *
 * - Choosing, results, the attract screen: a full-screen "reconnecting" cover. It blocks touches, so no button can
 *   fire a request that is bound to fail, and it lifts by itself the moment the connection is back, with the
 *   shopper's outfit and cart exactly as they were.
 * - Taking a photo or waiting for a look: only a banner. The countdown must not be interrupted, and a look that is
 *   being made keeps being followed (the socket reconnects and polling resumes by themselves).
 */
export function OfflineOverlay() {
  const online = useConnectivityStore((s) => s.state === "online");
  const phase = useKioskStore((s) => s.phase);
  if (online) return null;

  if (KEEP_GOING.has(phase)) {
    return (
      <div role="status" aria-live="polite" data-testid="offline-banner" className="pointer-events-none fixed inset-x-0 top-0 z-[60] flex justify-center p-4">
        <p className="glass-strong rounded-full px-8 py-3 text-2xl">Connection lost. Reconnecting…</p>
      </div>
    );
  }

  return (
    <div role="alertdialog" aria-modal="true" aria-label="Reconnecting" data-testid="offline-overlay" className="fixed inset-0 z-[60] flex flex-col items-center justify-center gap-10 bg-ink/95 p-12 text-center backdrop-blur-xl">
      <span aria-hidden className="h-24 w-24 animate-spin rounded-full border-8 border-white/15 border-t-accent" />
      <h2 className="text-6xl font-semibold">We&apos;re reconnecting</h2>
      <p className="max-w-2xl text-3xl text-mist/70">The mirror lost its connection for a moment. This clears by itself; your outfit and cart are safe.</p>
      <p className="text-2xl text-mist/50">If it takes more than a minute, please ask a team member for help.</p>
    </div>
  );
}
