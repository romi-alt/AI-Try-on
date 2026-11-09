"use client";

import Link from "next/link";
import { privacySummary } from "@/lib/privacy";
import { useKioskStore } from "@/store/useKioskStore";

/** Shown before anything is captured. The API will not start a session without it. */
export function ConsentScreen() {
  const agree = useKioskStore((s) => s.agree);
  const starting = useKioskStore((s) => s.phase === "starting");
  const error = useKioskStore((s) => s.error);

  return (
    <main className="flex min-h-screen items-center justify-center p-8">
      <div className="w-full max-w-2xl space-y-8 rounded-3xl border border-white/10 bg-white/5 p-10">
        <div className="space-y-3">
          <p className="text-sm uppercase tracking-[0.35em] text-accent">Before we start</p>
          <h1 className="text-4xl font-semibold leading-tight">Use your camera to try things on?</h1>
        </div>

        <ul className="space-y-3 text-lg text-mist/80">
          <li>We&apos;ll take a photo of you and use it to show you wearing the items you choose.</li>
          {privacySummary().map((line) => (
            <li key={line}>{line}</li>
          ))}
          <li>You can stop at any time with Exit. Tap Privacy below for the full notice.</li>
        </ul>

        {error && (
          <p role="alert" className="rounded-xl border border-red-400/40 bg-red-500/10 px-4 py-3 text-red-100">
            {error}
          </p>
        )}

        <div className="flex flex-wrap gap-4">
          <button
            type="button"
            onClick={() => void agree()}
            disabled={starting}
            className="rounded-full bg-mist px-8 py-4 text-lg font-medium text-ink transition hover:scale-[1.02] active:scale-[0.98] disabled:opacity-60"
          >
            {starting ? "Starting…" : "I agree, start"}
          </button>
          <Link
            href="/"
            className="rounded-full border border-white/25 px-8 py-4 text-lg text-mist/90 transition hover:bg-white/10"
          >
            No thanks
          </Link>
        </div>
      </div>
    </main>
  );
}
