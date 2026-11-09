"use client";

/* eslint-disable @next/next/no-img-element */
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { validateImageFile } from "@/lib/images";
import {
  addSizes,
  changedFields,
  defaultSizes,
  emptyForm,
  formFromProduct,
  MAX_COLORS,
  toProductInput,
  validateForm,
  type FormErrors,
  type ProductFormValues,
} from "@/lib/productForm";
import { CATEGORIES, type Category, type Product } from "@/lib/types";

type Props = {
  /** The product being edited, or null to create one. */
  product: Product | null;
  onClose: () => void;
  onSaved: (product: Product | null, message: string) => void;
};

const input = "w-full rounded-md border border-neutral-300 px-3 py-2 text-sm focus:border-neutral-900 focus:outline-none";
const label = "mb-1 block text-sm font-medium text-neutral-700";
const FieldError = ({ children }: { children?: string }) =>
  children ? (
    <p role="alert" className="mt-1 text-xs text-red-600">
      {children}
    </p>
  ) : null;

function useObjectUrl(file: File | null): string | null {
  const url = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => (url ? URL.revokeObjectURL(url) : undefined), [url]);
  return url;
}

export function ProductForm({ product, onClose, onSaved }: Props) {
  const [values, setValues] = useState<ProductFormValues>(() => (product ? formFromProduct(product) : emptyForm()));
  const [errors, setErrors] = useState<FormErrors>({});
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [maskFile, setMaskFile] = useState<File | null>(null);
  const [clearMask, setClearMask] = useState(false);
  const [maskError, setMaskError] = useState<string | undefined>();
  const [sizeText, setSizeText] = useState("");
  const [sizeError, setSizeError] = useState<string | undefined>();
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // A save that fails after the images went up must not upload them again on the retry.
  const uploaded = useRef(new Map<File, string>());

  const imagePreview = useObjectUrl(imageFile);
  const maskPreview = useObjectUrl(maskFile);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && !submitting && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, submitting]);

  const set = <K extends keyof ProductFormValues>(key: K, value: ProductFormValues[K]) => {
    setValues((v) => ({ ...v, [key]: value }));
    // A problem is cleared as soon as the field is touched, not left on screen until the next submit.
    // The sale price is judged against the price, so editing either one clears the sale price's message.
    setErrors((e) => {
      const next: FormErrors = { ...e };
      delete next[key as keyof FormErrors];
      if (key === "price") delete next.salePrice;
      return next;
    });
  };

  function changeCategory(category: Category) {
    setValues((v) => {
      // Offer the new category's usual sizes, unless the admin has already customised them.
      const untouched = JSON.stringify(v.sizes) === JSON.stringify(defaultSizes(v.category));
      return { ...v, category, sizes: !product && untouched ? defaultSizes(category) : v.sizes };
    });
  }

  function addSizeFromText() {
    const r = addSizes(values.sizes, sizeText);
    setSizeError(r.error ?? undefined);
    if (!r.error) {
      set("sizes", r.sizes);
      setSizeText("");
    }
  }

  function pickImage(file: File | null) {
    if (!file) return setImageFile(null);
    const problem = validateImageFile(file);
    setErrors((e) => ({ ...e, image: problem ?? undefined }));
    setImageFile(problem ? null : file);
  }

  function pickMask(file: File | null) {
    if (!file) return setMaskFile(null);
    const problem = validateImageFile(file);
    setMaskError(problem ?? undefined);
    setMaskFile(problem ? null : file);
    if (!problem) setClearMask(false);
  }

  async function upload(file: File): Promise<string> {
    const known = uploaded.current.get(file);
    if (known) return known;
    const url = await api.uploadImage(file);
    uploaded.current.set(file, url);
    return url;
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const found = validateForm(values, { hasImage: !!imageFile || !!product });
    setErrors(found);
    if (Object.keys(found).length > 0 || maskError) return;

    setSubmitting(true);
    setSubmitError(null);
    try {
      const image = imageFile ? await upload(imageFile) : product!.garment_image_url;
      const mask = maskFile ? await upload(maskFile) : clearMask ? null : (product?.garment_mask_url ?? null);
      const body = toProductInput(values, { image, mask });

      if (!product) {
        const created = await api.createProduct(body);
        onSaved(created, `Added “${created.name}”.`);
      } else {
        const patch = changedFields(product, body);
        if (Object.keys(patch).length === 0) return onSaved(null, "Nothing to change.");
        const saved = await api.updateProduct(product.id, patch);
        onSaved(saved, `Saved “${saved.name}”.`);
      }
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Couldn't save the product.");
    } finally {
      setSubmitting(false);
    }
  }

  const shownImage = imagePreview ?? product?.garment_image_url ?? null;
  const shownMask = clearMask ? null : (maskPreview ?? product?.garment_mask_url ?? null);

  return (
    <div className="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true" aria-label={product ? "Edit product" : "New product"}>
      <button type="button" aria-label="Close" onClick={() => !submitting && onClose()} className="absolute inset-0 bg-black/40" />
      <form onSubmit={submit} noValidate className="relative flex h-full w-full max-w-xl flex-col bg-white shadow-2xl">
        <div className="flex items-center justify-between border-b border-neutral-200 px-6 py-4">
          <h2 className="text-lg font-semibold">{product ? "Edit product" : "New product"}</h2>
          <button type="button" onClick={onClose} disabled={submitting} className="rounded-md px-2 py-1 text-neutral-500 hover:bg-neutral-100">
            Close
          </button>
        </div>

        <div className="flex-1 space-y-5 overflow-y-auto px-6 py-5">
          {submitError && (
            <p role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
              {submitError}
            </p>
          )}

          <div>
            <label htmlFor="pf-name" className={label}>
              Name
            </label>
            <input id="pf-name" className={input} value={values.name} onChange={(e) => set("name", e.target.value)} />
            <FieldError>{errors.name}</FieldError>
          </div>

          <div>
            <label htmlFor="pf-category" className={label}>
              Category
            </label>
            <select id="pf-category" className={input} value={values.category} onChange={(e) => changeCategory(e.target.value as Category)}>
              {CATEGORIES.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label htmlFor="pf-price" className={label}>
                Price (Rs)
              </label>
              <input id="pf-price" inputMode="numeric" className={input} value={values.price} onChange={(e) => set("price", e.target.value)} />
              <FieldError>{errors.price}</FieldError>
            </div>
            <div>
              <label htmlFor="pf-sale" className={label}>
                Sale price (Rs)
              </label>
              <input
                id="pf-sale"
                inputMode="numeric"
                placeholder="Not on sale"
                className={input}
                value={values.salePrice}
                onChange={(e) => set("salePrice", e.target.value)}
              />
              <FieldError>{errors.salePrice}</FieldError>
            </div>
            <div>
              <label htmlFor="pf-stock" className={label}>
                Stock
              </label>
              <input id="pf-stock" inputMode="numeric" className={input} value={values.stock} onChange={(e) => set("stock", e.target.value)} />
              <FieldError>{errors.stock}</FieldError>
            </div>
          </div>

          <div>
            <span className={label}>Sizes</span>
            <div className="mb-2 flex flex-wrap gap-2">
              {values.sizes.length === 0 && <span className="text-sm text-neutral-500">No sizes: shoppers won&apos;t be asked to choose one.</span>}
              {values.sizes.map((s) => (
                <span key={s} className="flex items-center gap-1 rounded-full bg-neutral-100 py-1 pl-3 pr-1 text-sm">
                  {s}
                  <button
                    type="button"
                    aria-label={`Remove size ${s}`}
                    onClick={() => set("sizes", values.sizes.filter((x) => x !== s))}
                    className="flex h-5 w-5 items-center justify-center rounded-full text-neutral-500 hover:bg-neutral-300"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input
                aria-label="Add sizes"
                className={input}
                placeholder="Add sizes, separated by commas"
                value={sizeText}
                onChange={(e) => setSizeText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addSizeFromText();
                  }
                }}
              />
              <button type="button" onClick={addSizeFromText} className="rounded-md border border-neutral-300 px-3 text-sm hover:bg-neutral-100">
                Add
              </button>
              <button
                type="button"
                onClick={() => set("sizes", defaultSizes(values.category))}
                className="whitespace-nowrap rounded-md border border-neutral-300 px-3 text-sm hover:bg-neutral-100"
              >
                Usual sizes
              </button>
            </div>
            <FieldError>{sizeError ?? errors.sizes}</FieldError>
          </div>

          <div>
            <span className={label}>Colours</span>
            <div className="space-y-2">
              {values.colors.map((c, i) => (
                <div key={i} className="flex items-center gap-2">
                  <input
                    type="color"
                    aria-label={`Colour ${i + 1} swatch`}
                    value={c.hex}
                    onChange={(e) => set("colors", values.colors.map((x, j) => (j === i ? { ...x, hex: e.target.value } : x)))}
                    className="h-9 w-12 cursor-pointer rounded border border-neutral-300"
                  />
                  <input
                    aria-label={`Colour ${i + 1} name`}
                    className={input}
                    placeholder="Name, e.g. Ivory"
                    value={c.name}
                    onChange={(e) => set("colors", values.colors.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                  />
                  <button
                    type="button"
                    aria-label={`Remove colour ${i + 1}`}
                    onClick={() => set("colors", values.colors.filter((_, j) => j !== i))}
                    className="rounded-md px-2 py-1 text-neutral-500 hover:bg-neutral-100"
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
            {values.colors.length < MAX_COLORS && (
              <button
                type="button"
                onClick={() => set("colors", [...values.colors, { name: "", hex: "#cccccc" }])}
                className="mt-2 rounded-md border border-neutral-300 px-3 py-1.5 text-sm hover:bg-neutral-100"
              >
                Add colour
              </button>
            )}
            <FieldError>{errors.colors}</FieldError>
          </div>

          <div>
            <label htmlFor="pf-image" className={label}>
              Garment image {product ? "(leave empty to keep the current one)" : ""}
            </label>
            <p className="mb-2 text-xs text-neutral-500">A flat garment photo, ideally a PNG with a transparent background. Up to 10 MB.</p>
            <div className="flex items-start gap-4">
              <div className="flex h-32 w-24 flex-none items-center justify-center overflow-hidden rounded-md bg-neutral-100">
                {shownImage ? <img src={shownImage} alt="Garment preview" className="h-full w-full object-contain" /> : <span className="text-xs text-neutral-400">No image</span>}
              </div>
              <input id="pf-image" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => pickImage(e.target.files?.[0] ?? null)} className="text-sm" />
            </div>
            <FieldError>{errors.image}</FieldError>
          </div>

          <div>
            <label htmlFor="pf-mask" className={label}>
              Garment mask (optional)
            </label>
            <p className="mb-2 text-xs text-neutral-500">White where the garment is, black elsewhere. Used by the try-on model.</p>
            <div className="flex items-start gap-4">
              <div className="flex h-20 w-16 flex-none items-center justify-center overflow-hidden rounded-md bg-neutral-100">
                {shownMask ? <img src={shownMask} alt="Mask preview" className="h-full w-full object-contain" /> : <span className="text-xs text-neutral-400">None</span>}
              </div>
              <div className="space-y-2">
                <input id="pf-mask" type="file" accept="image/png,image/jpeg,image/webp" onChange={(e) => pickMask(e.target.files?.[0] ?? null)} className="text-sm" />
                {product?.garment_mask_url && !maskFile && (
                  <button type="button" onClick={() => setClearMask((v) => !v)} className="text-sm text-neutral-600 underline">
                    {clearMask ? "Keep the current mask" : "Remove the current mask"}
                  </button>
                )}
              </div>
            </div>
            <FieldError>{maskError}</FieldError>
          </div>
        </div>

        <div className="flex justify-end gap-3 border-t border-neutral-200 px-6 py-4">
          <button type="button" onClick={onClose} disabled={submitting} className="rounded-md border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-100">
            Cancel
          </button>
          <button type="submit" disabled={submitting} className="rounded-md bg-neutral-900 px-5 py-2 text-sm text-white hover:bg-neutral-700 disabled:opacity-50">
            {submitting ? "Saving…" : product ? "Save changes" : "Add product"}
          </button>
        </div>
      </form>
    </div>
  );
}
