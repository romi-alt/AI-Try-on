import { describe, expect, it } from "vitest";
import { CSV_TEMPLATE, MAX_CSV_BYTES, validateCsvFile } from "./csvImport";

describe("validateCsvFile", () => {
  it("accepts a normal csv", () => {
    expect(validateCsvFile({ name: "stock.csv", size: 1200, type: "text/csv" })).toBeNull();
    expect(validateCsvFile({ name: "STOCK.CSV", size: 1200, type: "" })).toBeNull();
    expect(validateCsvFile({ name: "export", size: 1200, type: "application/vnd.ms-excel.csv" })).toBeNull();
  });
  it("refuses empty, huge and non-csv files", () => {
    expect(validateCsvFile({ name: "a.csv", size: 0 })).toMatch(/empty/);
    expect(validateCsvFile({ name: "a.csv", size: MAX_CSV_BYTES + 1 })).toMatch(/larger/);
    expect(validateCsvFile({ name: "a.xlsx", size: 10, type: "application/vnd.ms-excel" })).toMatch(/\.csv/);
  });
});

describe("CSV_TEMPLATE", () => {
  it("has the columns the API expects, and a row per example", () => {
    const [header, ...rows] = CSV_TEMPLATE.trim().split("\n");
    expect(header).toBe("sku,name,category,price_pkr,sale_price_pkr,sizes,colors,stock,image_url");
    expect(rows).toHaveLength(2);
    for (const r of rows) expect(r.split(",")).toHaveLength(header.split(",").length);
  });
});
