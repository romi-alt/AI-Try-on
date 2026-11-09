const pkr = new Intl.NumberFormat("en-PK", { maximumFractionDigits: 0 });

/** Whole rupees, e.g. 4390 -> "Rs 4,390". */
export function formatPkr(amount: number): string {
  return `Rs ${pkr.format(amount)}`;
}
