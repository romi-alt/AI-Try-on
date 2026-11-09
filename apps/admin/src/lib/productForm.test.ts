import { describe, expect, it } from "vitest";
import {
  addSizes,
  changedFields,
  defaultSizes,
  emptyForm,
  formFromProduct,
  MAX_AMOUNT,
  parseWholeNumber,
  toProductInput,
  validateForm,
  type ProductFormValues,
} from "./productForm";
import type { Product } from "./types";

const valid = (over: Partial<ProductFormValues> = {}): ProductFormValues => ({
  ...emptyForm(),
  name: "Linen Camp Shirt",
  price: "3990",
  stock: "12",
  ...over,
});

const stored: Product = {
  id: "p1",
  name: "Linen Camp Shirt",
  category: "top",
  price_pkr: 3990,
  sale_price_pkr: null,
  sizes: ["S", "M"],
  colors: [{ name: "Sand", hex: "#cdb892" }],
  stock: 12,
  garment_image_url: "http://img/a.png",
  garment_mask_url: null,
  created_at: "2026-01-01T00:00:00Z",
  on_sale: false,
  current_price_pkr: 3990,
};

describe("parseWholeNumber", () => {
  it("accepts plain non-negative integers, ignoring surrounding spaces", () => {
    expect(parseWholeNumber("0")).toBe(0);
    expect(parseWholeNumber(" 4390 ")).toBe(4390);
  });
  it.each(["", " ", "-1", "12.5", "1e3", "1,000", "abc", "0x10", "٣"])("rejects %j", (text) => {
    expect(parseWholeNumber(text)).toBeNull();
  });
  it("rejects numbers too large to be exact", () => {
    expect(parseWholeNumber("9".repeat(20))).toBeNull();
  });
});

describe("defaultSizes", () => {
  it("matches what the catalog uses", () => {
    expect(defaultSizes("top")).toEqual(["XS", "S", "M", "L", "XL"]);
    expect(defaultSizes("shoes")).toEqual(["36", "37", "38", "39", "40", "41"]);
    expect(defaultSizes("bag")).toEqual(["One Size"]);
    expect(defaultSizes("accessory")).toEqual(["One Size"]);
  });
  it("returns a copy, so editing it cannot change the defaults", () => {
    defaultSizes("top").push("XXL");
    expect(defaultSizes("top")).toHaveLength(5);
  });
});

describe("addSizes", () => {
  it("adds a comma separated list, trimmed", () => {
    expect(addSizes(["S"], " M , L ,, XL ").sizes).toEqual(["S", "M", "L", "XL"]);
  });
  it("keeps spaces inside a size", () => {
    expect(addSizes([], "One Size").sizes).toEqual(["One Size"]);
  });
  it("ignores duplicates, whatever the case", () => {
    expect(addSizes(["M"], "m, M, L, l").sizes).toEqual(["M", "L"]);
  });
  it("refuses a size the cart could not store, and changes nothing", () => {
    const r = addSizes(["S"], "M, " + "x".repeat(21));
    expect(r.sizes).toEqual(["S"]);
    expect(r.error).toMatch(/at most 20/);
  });
  it("limits how many sizes there can be", () => {
    const r = addSizes([], Array.from({ length: 21 }, (_, i) => `S${i}`).join(","));
    expect(r.error).toMatch(/At most 20 sizes/);
    expect(r.sizes).toEqual([]);
  });
});

describe("validateForm", () => {
  it("accepts a good form", () => {
    expect(validateForm(valid(), { hasImage: true })).toEqual({});
  });

  it("needs a name", () => {
    expect(validateForm(valid({ name: "   " }), { hasImage: true }).name).toBeDefined();
    expect(validateForm(valid({ name: "x".repeat(201) }), { hasImage: true }).name).toMatch(/200/);
  });

  it("needs a price in whole rupees", () => {
    for (const price of ["", "abc", "-5", "12.5"]) {
      expect(validateForm(valid({ price }), { hasImage: true }).price, price).toBeDefined();
    }
    expect(validateForm(valid({ price: "0" }), { hasImage: true }).price).toBeUndefined();
  });

  it("keeps price and stock inside what the database can hold", () => {
    expect(validateForm(valid({ price: String(MAX_AMOUNT) }), { hasImage: true }).price).toBeUndefined();
    expect(validateForm(valid({ price: String(MAX_AMOUNT + 1) }), { hasImage: true }).price).toMatch(/too large/);
    expect(validateForm(valid({ stock: "2147483648" }), { hasImage: true }).stock).toMatch(/too large/);
  });

  it("treats the sale price as optional but, if given, below the price", () => {
    expect(validateForm(valid({ salePrice: "" }), { hasImage: true }).salePrice).toBeUndefined();
    expect(validateForm(valid({ salePrice: "3000" }), { hasImage: true }).salePrice).toBeUndefined();
    expect(validateForm(valid({ salePrice: "3990" }), { hasImage: true }).salePrice).toMatch(/below/);
    expect(validateForm(valid({ salePrice: "5000" }), { hasImage: true }).salePrice).toMatch(/below/);
    expect(validateForm(valid({ salePrice: "x" }), { hasImage: true }).salePrice).toBeDefined();
  });

  it("does not pile a sale-price error onto an invalid price", () => {
    const e = validateForm(valid({ price: "", salePrice: "100" }), { hasImage: true });
    expect(e.price).toBeDefined();
    expect(e.salePrice).toBeUndefined();
  });

  it("needs stock as a whole number, zero allowed", () => {
    expect(validateForm(valid({ stock: "0" }), { hasImage: true }).stock).toBeUndefined();
    expect(validateForm(valid({ stock: "-1" }), { hasImage: true }).stock).toBeDefined();
    expect(validateForm(valid({ stock: "" }), { hasImage: true }).stock).toBeDefined();
  });

  it("checks colours: named, valid, unique", () => {
    const colors = (...cs: [string, string][]) => cs.map(([name, hex]) => ({ name, hex }));
    expect(validateForm(valid({ colors: colors(["Sand", "#cdb892"], ["Sky", "#a9c4dc"]) }), { hasImage: true }).colors).toBeUndefined();
    expect(validateForm(valid({ colors: colors(["", "#cdb892"]) }), { hasImage: true }).colors).toMatch(/name/);
    expect(validateForm(valid({ colors: colors(["Sand", "red"]) }), { hasImage: true }).colors).toMatch(/valid colour/);
    expect(validateForm(valid({ colors: colors(["Sand", "#cdb892"], [" sand ", "#000000"]) }), { hasImage: true }).colors).toMatch(/twice/);
    expect(validateForm(valid({ colors: colors(["x".repeat(41), "#000000"]) }), { hasImage: true }).colors).toMatch(/40/);
  });

  it("needs an image when there is none yet", () => {
    expect(validateForm(valid(), { hasImage: false }).image).toBeDefined();
  });

  it("reports every problem at once", () => {
    const e = validateForm(valid({ name: "", price: "", stock: "-1" }), { hasImage: false });
    expect(Object.keys(e).sort()).toEqual(["image", "name", "price", "stock"]);
  });
});

describe("toProductInput", () => {
  it("builds the API payload, cleaning up what was typed", () => {
    const input = toProductInput(
      valid({ name: "  Linen Camp Shirt ", salePrice: "2990", colors: [{ name: " Sand ", hex: "#CDB892" }], sizes: ["M"] }),
      { image: "http://img/a.png", mask: "http://img/a-mask.png" },
    );
    expect(input).toEqual({
      name: "Linen Camp Shirt",
      category: "top",
      price_pkr: 3990,
      sale_price_pkr: 2990,
      sizes: ["M"],
      colors: [{ name: "Sand", hex: "#cdb892" }],
      stock: 12,
      garment_image_url: "http://img/a.png",
      garment_mask_url: "http://img/a-mask.png",
    });
  });

  it("sends null for no sale price and no mask", () => {
    const input = toProductInput(valid(), { image: "u", mask: null });
    expect(input.sale_price_pkr).toBeNull();
    expect(input.garment_mask_url).toBeNull();
  });
});

describe("editing", () => {
  it("round-trips a stored product through the form unchanged", () => {
    const input = toProductInput(formFromProduct(stored), { image: stored.garment_image_url, mask: null });
    expect(changedFields(stored, input)).toEqual({});
  });

  it("sends only what changed", () => {
    const form = { ...formFromProduct(stored), price: "4500", stock: "3" };
    const patch = changedFields(stored, toProductInput(form, { image: stored.garment_image_url, mask: null }));
    expect(patch).toEqual({ price_pkr: 4500, stock: 3 });
  });

  it("clears the sale price by sending an explicit null", () => {
    const onSale = { ...stored, sale_price_pkr: 2990, on_sale: true };
    const form = { ...formFromProduct(onSale), salePrice: "" };
    const patch = changedFields(onSale, toProductInput(form, { image: onSale.garment_image_url, mask: null }));
    expect(patch).toEqual({ sale_price_pkr: null });
    expect("sale_price_pkr" in patch).toBe(true);
  });

  it("replaces the image and mask when new ones are uploaded", () => {
    const patch = changedFields(stored, toProductInput(formFromProduct(stored), { image: "http://img/new.png", mask: "http://img/m.png" }));
    expect(patch).toEqual({ garment_image_url: "http://img/new.png", garment_mask_url: "http://img/m.png" });
  });

  it("notices a changed list even when its length is the same", () => {
    const form = { ...formFromProduct(stored), sizes: ["S", "L"], colors: [{ name: "Sand", hex: "#000000" }] };
    const patch = changedFields(stored, toProductInput(form, { image: stored.garment_image_url, mask: null }));
    expect(Object.keys(patch).sort()).toEqual(["colors", "sizes"]);
  });

  it("copies colours so editing the form cannot alter the stored product", () => {
    const form = formFromProduct(stored);
    form.colors[0].name = "Changed";
    expect(stored.colors[0].name).toBe("Sand");
  });
});
