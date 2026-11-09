import { formatPkr } from "@/lib/money";
import type { Product } from "@/lib/types";

/** Rupee prices. A discounted item shows its sale price with the regular price struck through. */
export function Price({ product, size = "md" }: { product: Pick<Product, "price_pkr" | "current_price_pkr" | "on_sale">; size?: "md" | "lg" }) {
  const big = size === "lg";
  return (
    <p className={`flex flex-wrap items-baseline gap-x-3 ${big ? "text-3xl" : "text-xl"}`}>
      <span className={`font-semibold ${product.on_sale ? "text-accent" : ""}`}>{formatPkr(product.current_price_pkr)}</span>
      {product.on_sale && (
        <s className={`${big ? "text-2xl" : "text-lg"} text-mist/50`} aria-label={`was ${formatPkr(product.price_pkr)}`}>
          {formatPkr(product.price_pkr)}
        </s>
      )}
    </p>
  );
}
