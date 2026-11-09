"use client";

import * as Sentry from "@sentry/nextjs";
import { useEffect } from "react";

/** The last line of defence: a render error that nothing else caught. Reported (scrubbed), then a way back. */
export default function GlobalError({ error }: { error: Error & { digest?: string } }) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);
  return (
    <html lang="en">
      <body style={{ background: "#0b0b0f", color: "#f5f3ee", fontFamily: "system-ui, sans-serif", display: "grid", placeItems: "center", minHeight: "100vh", margin: 0 }}>
        <div style={{ textAlign: "center", maxWidth: 480, padding: 24 }}>
          <h1 style={{ fontSize: 28 }}>Something went wrong</h1>
          <p style={{ opacity: 0.7 }}>The page hit a problem. Reloading usually fixes it.</p>
          <button type="button" onClick={() => window.location.assign("/")} style={{ minHeight: 64, minWidth: 200, fontSize: 20, borderRadius: 16, border: 0 }}>
            Start again
          </button>
        </div>
      </body>
    </html>
  );
}
