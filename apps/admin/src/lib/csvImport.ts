export const MAX_CSV_BYTES = 1024 * 1024;

export const CSV_TEMPLATE =
  "sku,name,category,price_pkr,sale_price_pkr,sizes,colors,stock,image_url\n" +
  "LCS-001,Linen Camp Shirt,top,3990,2990,S|M|L|XL,Sand:#cdb892|Black:#111111,25,https://example.com/images/lcs-001.png\n" +
  "LCS-002,Wide Leg Trousers,bottom,5490,,S|M|L,Ivory:#efe6d2,12,https://example.com/images/lcs-002.png\n";

/** A readable problem with a chosen file, or null if it is worth sending. The server checks the contents. */
export function validateCsvFile(file: { name: string; size: number; type?: string }): string | null {
  if (file.size <= 0) return "That file is empty.";
  if (file.size > MAX_CSV_BYTES) return `That file is larger than ${MAX_CSV_BYTES / 1024} KB. Split it into smaller files.`;
  if (!/\.csv$/i.test(file.name) && !(file.type ?? "").includes("csv")) return "Choose a .csv file (in Excel: Save As, CSV UTF-8).";
  return null;
}
