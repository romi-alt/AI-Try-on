"use client";

import { useEffect, useRef } from "react";

/**
 * "Still there?" Covers and blurs the screen so whatever was on it (a try-on photo) is not readable while
 * the shopper decides, and counts down to the reset.
 */
export function IdleWarning({ secondsLeft, onStay }: { secondsLeft: number; onStay: () => void }) {
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => button.current?.focus(), []);

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="idle-title"
      aria-describedby="idle-body"
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/85 p-8 backdrop-blur-2xl"
      onClick={onStay}
    >
      <div className="w-full max-w-lg space-y-6 rounded-3xl border border-white/15 bg-[#15151b] p-10 text-center">
        <h2 id="idle-title" className="text-3xl font-semibold">
          Are you still there?
        </h2>
        <p id="idle-body" className="text-lg text-mist/80">
          This screen will clear in <span className="font-semibold tabular-nums text-accent">{secondsLeft}</span>{" "}
          {secondsLeft === 1 ? "second" : "seconds"} to keep your photo private.
        </p>
        <button
          ref={button}
          type="button"
          onClick={onStay}
          className="rounded-full bg-mist px-10 py-4 text-lg font-medium text-ink transition hover:scale-[1.02] active:scale-[0.98]"
        >
          I&apos;m still here
        </button>
      </div>
    </div>
  );
}
