const UUID = /[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;

/**
 * The product id in a scanned code: a bare UUID, or a UUID inside a URL or text such as
 * `https://shop.example/p/<uuid>` or `tryon:product:<uuid>`. Null when there is none.
 */
export function parseProductCode(text: string): string | null {
  const match = UUID.exec(text.trim());
  return match ? match[0].toLowerCase() : null;
}

/** Whether this browser can read codes from the camera (Chrome and Edge can; Firefox and Safari cannot yet). */
export function canScan(): boolean {
  return typeof window !== "undefined" && "BarcodeDetector" in window;
}
