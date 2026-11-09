"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import { Banner } from "@/components/Banner";
import { api, ApiError } from "@/lib/api";
import { CSV_TEMPLATE, validateCsvFile } from "@/lib/csvImport";
import type { ImportReport } from "@/lib/types";

const ACTION_STYLE = { create: "bg-emerald-100 text-emerald-800", update: "bg-blue-100 text-blue-800", error: "bg-red-100 text-red-800" } as const;

export default function ImportPage() {
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [checkedOk, setCheckedOk] = useState(false); // the current file passed a dry run with no errors
  const [busy, setBusy] = useState<"check" | "import" | null>(null);
  const [error, setError] = useState<string | null>(null);

  function choose(f: File | null) {
    setFile(f);
    setReport(null);
    setCheckedOk(false);
    setError(null);
    setFileError(f ? validateCsvFile(f) : null);
  }

  async function run(dryRun: boolean) {
    if (!file) return;
    setBusy(dryRun ? "check" : "import");
    setError(null);
    try {
      const r = await api.importProducts(file, { dryRun });
      setReport(r);
      setCheckedOk(dryRun ? r.error_count === 0 && r.rows.length > 0 : false);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "The import failed.");
    } finally {
      setBusy(null);
    }
  }

  function downloadTemplate() {
    const url = URL.createObjectURL(new Blob([CSV_TEMPLATE], { type: "text/csv" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "products-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

  const imported = report && !report.dry_run && report.applied;
  return (
    <div className="max-w-4xl">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Import products from CSV</h1>
        <Link href="/products" className="text-sm text-neutral-600 hover:underline">
          Back to products
        </Link>
      </div>

      <div className="mb-6 space-y-2 rounded-lg border border-neutral-200 bg-white p-5 text-sm text-neutral-700">
        <p>
          One row per product. A row whose <code>sku</code> already exists <b>updates</b> that product (empty cells keep the current value; write <code>none</code> to remove a sale price); any other row{" "}
          <b>creates</b> one, and then needs <code>name</code>, <code>category</code>, <code>price_pkr</code> and <code>image_url</code>.
        </p>
        <p>
          Sizes are separated with <code>|</code> (<code>S|M|L</code>); colours are <code>Name:#hex</code> separated with <code>|</code>. Categories: top, bottom, dress, shoes, bag, accessory.
        </p>
        <p>The import is all or nothing: if any row has a problem nothing is saved, and every problem is listed so you can fix the file in one go.</p>
        <button type="button" onClick={downloadTemplate} className="text-neutral-900 underline">
          Download a template
        </button>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input ref={input} type="file" accept=".csv,text/csv" aria-label="CSV file" onChange={(e) => choose(e.target.files?.[0] ?? null)} className="text-sm" />
        <button type="button" disabled={!file || !!fileError || busy !== null} onClick={() => void run(true)} className="rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm hover:bg-neutral-100 disabled:opacity-50">
          {busy === "check" ? "Checking…" : "Check file"}
        </button>
        <button type="button" disabled={!checkedOk || busy !== null} onClick={() => void run(false)} className="rounded-md bg-neutral-900 px-4 py-2 text-sm text-white hover:bg-neutral-700 disabled:opacity-40">
          {busy === "import" ? "Importing…" : "Import"}
        </button>
      </div>
      {fileError && <Banner>{fileError}</Banner>}
      {error && <Banner>{error}</Banner>}

      {report && (
        <div className="space-y-3" data-testid="import-report">
          {imported ? (
            <Banner kind="success">
              Imported: {report.created} created, {report.updated} updated.
              {report.embedding_job_id ? " Embeddings are being updated in the background." : ""}{" "}
              <Link href="/products" className="underline">
                See the products
              </Link>
            </Banner>
          ) : report.error_count > 0 ? (
            <Banner>
              {report.error_count} {report.error_count === 1 ? "row has a problem" : "rows have problems"}. Nothing was saved. Fix the file and check it again.
            </Banner>
          ) : (
            <Banner kind="success">
              The file is fine: it would create {report.created} and update {report.updated} products. Press Import to save them.
            </Banner>
          )}

          <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
            <table className="w-full text-sm">
              <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
                <tr>
                  <th className="p-3">Line</th>
                  <th className="p-3">SKU</th>
                  <th className="p-3">Name</th>
                  <th className="p-3">Result</th>
                </tr>
              </thead>
              <tbody>
                {report.rows.map((r) => (
                  <tr key={r.line} className="border-t border-neutral-100 align-top">
                    <td className="p-3 tabular-nums text-neutral-500">{r.line}</td>
                    <td className="p-3">{r.sku ?? "—"}</td>
                    <td className="p-3">{r.name ?? "—"}</td>
                    <td className="p-3">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${ACTION_STYLE[r.action]}`}>{imported && r.action !== "error" ? (r.action === "create" ? "created" : "updated") : r.action}</span>
                      {r.errors.map((e) => (
                        <div key={e} className="mt-1 text-xs text-red-700">
                          {e}
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
