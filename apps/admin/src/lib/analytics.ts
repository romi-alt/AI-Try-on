/** 0.4286 -> "42.9%"; null (nothing to divide) -> an en dash. */
export function formatRate(rate: number | null): string {
  return rate === null ? "–" : `${(rate * 100).toFixed(1)}%`;
}

export const PERIODS = [
  { days: 7, label: "Last 7 days" },
  { days: 30, label: "Last 30 days" },
  { days: 90, label: "Last 90 days" },
] as const;
