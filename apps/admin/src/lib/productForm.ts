import type { Category, ColorOption, Product, ProductInput } from "./types";

export const CLOTHING_SIZES = ["XS", "S", "M", "L", "XL"];
export const SHOE_SIZES = ["36", "37", "38", "39", "40", "41"];
export const ONE_SIZE = ["One Size"];

export const MAX_NAME = 200;
export const MAX_SKU = 64;
export const MAX_SIZE_LEN = 20; // the cart stores sizes in a 20 character column
export const MAX_COLOR_LEN = 40;
export const MAX_SIZES = 20;
export const MAX_COLORS = 12;
/** price and stock are 32-bit integers in the database; larger values would fail on the server. */
export const MAX_AMOUNT = 2_000_000_000;

/** A sensible starting set of sizes for a category, as the seed data uses. */
export function defaultSizes(category: Category): string[] {
  if (category === "shoes") return [...SHOE_SIZES];
  if (category === "bag" || category === "accessory") return [...ONE_SIZE];
  return [...CLOTHING_SIZES];
}

/** Text fields hold what was typed; `toProductInput` turns them into numbers once validated. */
export type ProductFormValues = {
  sku: string;
  name: string;
  category: Category;
  price: string;
  salePrice: string;
  stock: string;
  sizes: string[];
  colors: ColorOption[];
};

export const emptyForm = (): ProductFormValues => ({
  sku: "",
  name: "",
  category: "top",
  price: "",
  salePrice: "",
  stock: "0",
  sizes: defaultSizes("top"),
  colors: [],
});

export const formFromProduct = (p: Product): ProductFormValues => ({
  sku: p.sku ?? "",
  name: p.name,
  category: p.category,
  price: String(p.price_pkr),
  salePrice: p.sale_price_pkr === null ? "" : String(p.sale_price_pkr),
  stock: String(p.stock),
  sizes: [...p.sizes],
  colors: p.colors.map((c) => ({ ...c })),
});

/** A whole number from what was typed, or null if it is empty or not a plain non-negative integer. */
export function parseWholeNumber(text: string): number | null {
  const t = text.trim();
  if (!/^\d+$/.test(t)) return null;
  const n = Number(t);
  return Number.isSafeInteger(n) ? n : null;
}

/** Adds sizes typed as a comma separated list. Case-insensitive duplicates are ignored. */
export function addSizes(existing: string[], text: string): { sizes: string[]; error: string | null } {
  const sizes = [...existing];
  for (const raw of text.split(/[,\n]/)) {
    const size = raw.trim();
    if (!size) continue;
    if (size.length > MAX_SIZE_LEN) return { sizes: existing, error: `Sizes can be at most ${MAX_SIZE_LEN} characters.` };
    if (sizes.some((s) => s.toLowerCase() === size.toLowerCase())) continue;
    sizes.push(size);
  }
  if (sizes.length > MAX_SIZES) return { sizes: existing, error: `At most ${MAX_SIZES} sizes.` };
  return { sizes, error: null };
}

export type FormErrors = Partial<Record<"sku" | "name" | "price" | "salePrice" | "stock" | "sizes" | "colors" | "image", string>>;

export function validateForm(v: ProductFormValues, opts: { hasImage: boolean }): FormErrors {
  const errors: FormErrors = {};

  if (v.sku.trim().length > MAX_SKU) errors.sku = `Keep the SKU under ${MAX_SKU} characters.`;

  const name = v.name.trim();
  if (!name) errors.name = "Enter a name.";
  else if (name.length > MAX_NAME) errors.name = `Keep the name under ${MAX_NAME} characters.`;

  const price = parseWholeNumber(v.price);
  if (price === null) errors.price = "Enter the price in whole rupees.";
  else if (price > MAX_AMOUNT) errors.price = "That price is too large.";

  if (v.salePrice.trim() !== "") {
    const sale = parseWholeNumber(v.salePrice);
    if (sale === null) errors.salePrice = "Enter the sale price in whole rupees, or leave it blank.";
    else if (price !== null && sale >= price) {
      errors.salePrice = "The sale price must be below the regular price. Leave it blank if the item isn't on sale.";
    }
  }

  const stock = parseWholeNumber(v.stock);
  if (stock === null) errors.stock = "Enter the stock as a whole number (0 if sold out).";
  else if (stock > MAX_AMOUNT) errors.stock = "That stock level is too large.";

  if (v.colors.length > MAX_COLORS) errors.colors = `At most ${MAX_COLORS} colours.`;
  const seen = new Set<string>();
  for (const c of v.colors) {
    const n = c.name.trim();
    if (!n) errors.colors = "Give every colour a name.";
    else if (n.length > MAX_COLOR_LEN) errors.colors = `Colour names can be at most ${MAX_COLOR_LEN} characters.`;
    else if (!/^#[0-9a-fA-F]{6}$/.test(c.hex)) errors.colors = `"${n}" needs a valid colour.`;
    else if (seen.has(n.toLowerCase())) errors.colors = `The colour "${n}" is listed twice.`;
    seen.add(n.toLowerCase());
    if (errors.colors) break;
  }

  if (!opts.hasImage) errors.image = "Choose a garment image.";
  return errors;
}

/** Turns validated form values into the API's payload. Call `validateForm` first. */
export function toProductInput(
  v: ProductFormValues,
  urls: { image: string; mask: string | null },
): ProductInput {
  return {
    sku: v.sku.trim() === "" ? null : v.sku.trim(),
    name: v.name.trim(),
    category: v.category,
    price_pkr: parseWholeNumber(v.price) ?? 0,
    sale_price_pkr: v.salePrice.trim() === "" ? null : parseWholeNumber(v.salePrice),
    sizes: v.sizes,
    colors: v.colors.map((c) => ({ name: c.name.trim(), hex: c.hex.toLowerCase() })),
    stock: parseWholeNumber(v.stock) ?? 0,
    garment_image_url: urls.image,
    garment_mask_url: urls.mask,
  };
}

const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Only the fields that differ from the stored product, for PATCH. A cleared optional field is sent as null. */
export function changedFields(original: Product, next: ProductInput): Partial<ProductInput> {
  const patch: Partial<ProductInput> = {};
  const keys = Object.keys(next) as (keyof ProductInput)[];
  for (const key of keys) {
    if (!same(original[key], next[key])) (patch as Record<string, unknown>)[key] = next[key];
  }
  return patch;
}
