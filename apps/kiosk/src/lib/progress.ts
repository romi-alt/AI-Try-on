/** A percentage as a whole number from 0 to 100, whatever it was given. */
export function clampPct(pct: number | null | undefined): number {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return 0;
  return Math.max(0, Math.min(100, Math.round(pct)));
}

/** The stroke-dasharray of a progress ring whose full circle is `circumference` long. */
export function ringDash(pct: number, circumference: number): string {
  const filled = (clampPct(pct) / 100) * circumference;
  return `${filled} ${circumference}`;
}

/** What is happening, in a few words, for the line under "Almost there...". */
export function stageLabel(phase: string, pct: number): string {
  if (phase === "uploading") return "Sending your photo";
  const p = clampPct(pct);
  if (p < 10) return "Getting ready";
  if (p < 90) return "Dressing you up";
  return "Adding the finishing touches";
}
