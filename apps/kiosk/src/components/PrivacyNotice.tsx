"use client";

import { privacySections, privacySummary, retentionText } from "@/lib/privacy";

/** The privacy notice as a pop-up. Large, readable, and with a 64 px close button, like everything on the mirror. */
export function PrivacyNotice({ onClose }: { onClose: () => void }) {
  return (
    <div role="dialog" aria-modal="true" aria-labelledby="privacy-title" className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-8 backdrop-blur-md">
      <div className="glass-strong flex max-h-[85vh] w-full max-w-3xl flex-col rounded-[2rem]">
        <div className="flex items-start justify-between gap-6 p-8 pb-4">
          <div>
            <p className="text-lg uppercase tracking-[0.3em] text-accent">Privacy</p>
            <h2 id="privacy-title" className="mt-2 text-4xl font-semibold">
              Your photo is deleted within {retentionText()}
            </h2>
          </div>
          <button type="button" onClick={onClose} className="btn-ghost flex-none" aria-label="Close privacy notice">
            Close
          </button>
        </div>
        <div className="scroll-y space-y-8 px-8 pb-8">
          <ul className="space-y-3 text-2xl text-mist/90">
            {privacySummary().map((line) => (
              <li key={line} className="flex gap-3">
                <span aria-hidden className="text-accent">
                  ✓
                </span>
                {line}
              </li>
            ))}
          </ul>
          {privacySections().map((s) => (
            <section key={s.heading} className="space-y-3">
              <h3 className="text-2xl font-semibold">{s.heading}</h3>
              {s.body.map((p) => (
                <p key={p.slice(0, 40)} className="text-xl leading-relaxed text-mist/75">
                  {p}
                </p>
              ))}
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
