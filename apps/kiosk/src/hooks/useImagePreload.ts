"use client";

import { useEffect, useState } from "react";

export type PreloadState = "loading" | "loaded" | "error";

/**
 * Loads `url` in the background and says when it has fully arrived (decoded, so showing it does not flash or
 * paint in stripes). The screen keeps the blurred photo up and fades the image in only once this says "loaded".
 */
export function useImagePreload(url: string | null | undefined): PreloadState {
  const [state, setState] = useState<PreloadState>("loading");
  useEffect(() => {
    if (!url) return setState("loading");
    let cancelled = false;
    setState("loading");
    const img = new Image();
    img.onload = () => {
      // decode() resolves once the pixels are ready to paint; where it is missing, onload is good enough
      const ready = typeof img.decode === "function" ? img.decode().catch(() => undefined) : Promise.resolve();
      void ready.then(() => !cancelled && setState("loaded"));
    };
    img.onerror = () => !cancelled && setState("error");
    img.src = url;
    return () => {
      cancelled = true;
      img.onload = null;
      img.onerror = null;
    };
  }, [url]);
  return state;
}
