"use client";

import { useKioskStore } from "@/store/useKioskStore";

export function ErrorScreen() {
  const error = useKioskStore((s) => s.error);
  const retry = useKioskStore((s) => s.retryTryOn);
  const backToShop = useKioskStore((s) => s.backToShop);
  return (
    <div className="fixed inset-0 flex items-center justify-center p-10" role="alert">
      <div className="glass-strong w-full max-w-3xl space-y-8 rounded-[2.5rem] p-12 text-center">
        <h1 className="text-5xl font-semibold">Something went wrong</h1>
        <p className="text-3xl text-mist/80">{error ?? "Please try again."}</p>
        <div className="flex justify-center gap-4">
          <button type="button" className="btn-primary h-24 px-14 text-3xl" onClick={() => void retry()}>
            Try again
          </button>
          <button type="button" className="btn-ghost h-24 px-14 text-3xl" onClick={backToShop}>
            Back to shop
          </button>
        </div>
      </div>
    </div>
  );
}
