const pkr = new Intl.NumberFormat("en-PK", { maximumFractionDigits: 0 });

/** Whole rupees, e.g. 4390 -> "Rs 4,390". */
export function formatPkr(amount: number): string {
  return `Rs ${pkr.format(amount)}`;
}

/** Percentage off, rounded, e.g. (5490, 4390) -> 20. 0 when there is no discount. */
export function discountPercent(price: number, salePrice: number | null): number {
  if (salePrice === null || salePrice >= price || price <= 0) return 0;
  return Math.round(((price - salePrice) / price) * 100);
}
