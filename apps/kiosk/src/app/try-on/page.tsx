"use client";

import { useEffect } from "react";
import Link from "next/link";
import { WebcamMirror } from "@/components/WebcamMirror";
import { GarmentCarousel } from "@/components/GarmentCarousel";
import { ResultView } from "@/components/ResultView";
import { useSessionStore } from "@/store/useSessionStore";

export default function TryOnPage() {
  const status = useSessionStore((s) => s.status);
  const error = useSessionStore((s) => s.error);
  const startSession = useSessionStore((s) => s.startSession);
  const reset = useSessionStore((s) => s.reset);

  useEffect(() => {
    void startSession();
    return () => reset();
  }, [startSession, reset]);

  return (
    <main className="flex h-screen flex-col">
      <header className="flex items-center justify-between px-6 py-4">
        <Link href="/" className="text-sm uppercase tracking-[0.3em] text-mist/60">
          ← Exit
        </Link>
        <StatusPill status={status} />
      </header>

      <section className="relative flex-1 overflow-hidden">
        {status === "done" ? <ResultView /> : <WebcamMirror />}
      </section>

      {error && (
        <div className="mx-6 mb-3 rounded-lg border border-red-500/40 bg-red-500/10 px-4 py-2 text-sm text-red-200">
          {error}
        </div>
      )}

      <footer className="border-t border-white/10 bg-black/40 px-4 py-4 backdrop-blur">
        <GarmentCarousel />
      </footer>
    </main>
  );
}

function StatusPill({ status }: { status: string }) {
  const label: Record<string, string> = {
    idle: "Starting…",
    ready: "Pick a garment",
    capturing: "Hold still",
    uploading: "Uploading",
    processing: "Rendering your look",
    done: "Done",
    error: "Something went wrong",
  };
  return (
    <span className="rounded-full border border-white/15 px-3 py-1 text-xs uppercase tracking-widest text-mist/80">
      {label[status] ?? status}
    </span>
  );
}
