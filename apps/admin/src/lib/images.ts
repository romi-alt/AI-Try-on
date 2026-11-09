import { config } from "./config";

export const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"] as const;

/** A readable problem with a chosen image file, or null if it is fine to upload. */
export function validateImageFile(
  file: { type: string; size: number },
  maxBytes: number = config.maxImageBytes,
): string | null {
  if (!(IMAGE_TYPES as readonly string[]).includes(file.type)) return "Use a PNG, JPEG or WebP image.";
  if (file.size <= 0) return "That file is empty.";
  if (file.size > maxBytes) return `That image is larger than ${Math.round(maxBytes / (1024 * 1024))} MB.`;
  return null;
}
