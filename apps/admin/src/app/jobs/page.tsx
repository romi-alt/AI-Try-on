"use client";

import { useEffect, useMemo, useState } from "react";
import { Banner } from "@/components/Banner";
import { StatusPill } from "@/components/StatusPill";
import { api, ApiError } from "@/lib/api";
import { config } from "@/lib/config";
import { formatDuration, linkExpired, productNames, shortId } from "@/lib/jobs";
import type { Job, JobStatus } from "@/lib/types";

const STATUSES: (JobStatus | "all")[] = ["all", "queued", "processing", "done", "failed"];

export default function JobsPage() {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [names, setNames] = useState<Map<string, string>>(new Map());
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<JobStatus | "all">("all");

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .listJobs()
        .then((j) => !cancelled && (setJobs(j), setError(null)))
        .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Couldn't load the jobs."));
    void load();
    const id = setInterval(load, config.jobsPollMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  // Product names, so a job reads "Linen Camp Shirt, Wide-Leg Trouser" rather than two ids. Not essential.
  useEffect(() => {
    let cancelled = false;
    api
      .listAllProducts()
      .then((all) => !cancelled && setNames(new Map(all.map((p) => [p.id, p.name]))))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const shown = useMemo(() => (jobs ?? []).filter((j) => status === "all" || j.status === status), [jobs, status]);
  const now = Date.now();

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Try-on jobs</h1>
        <select aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value as JobStatus | "all")} className="rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm">
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s === "all" ? "All statuses" : s}
            </option>
          ))}
        </select>
      </div>
      {error && <Banner>{error}</Banner>}
      <p className="mb-3 text-sm text-neutral-500">The latest {config.listLimit}, refreshed every few seconds.</p>
      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="p-3">Job</th>
              <th className="p-3">Status</th>
              <th className="p-3">Products</th>
              <th className="p-3">Session</th>
              <th className="p-3">Created</th>
              <th className="p-3">Took</th>
              <th className="p-3">Result</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((j) => (
              <tr key={j.id} className="border-t border-neutral-100 align-top">
                <td className="p-3 font-mono text-xs" title={j.id}>
                  {shortId(j.id)}
                </td>
                <td className="p-3">
                  <StatusPill status={j.status} />
                  {(j.status === "processing" || j.status === "queued") && (
                    <div className="mt-1 h-1.5 w-20 overflow-hidden rounded-full bg-neutral-200" aria-label={`${j.progress}%`}>
                      <div className="h-full bg-blue-500" style={{ width: `${j.progress}%` }} />
                    </div>
                  )}
                </td>
                <td className="p-3">{productNames(j.product_ids, names).join(", ")}</td>
                <td className="p-3 font-mono text-xs" title={j.session_id}>
                  {shortId(j.session_id)}
                </td>
                <td className="p-3 whitespace-nowrap">{new Date(j.created_at).toLocaleString()}</td>
                <td className="p-3 tabular-nums">{j.status === "done" || j.status === "failed" ? formatDuration(j.created_at, j.updated_at) : ""}</td>
                <td className="p-3">
                  {j.status === "done" && j.result_url ? (
                    linkExpired(j.result_url, now) ? (
                      <span className="text-xs text-neutral-500">Link expired</span>
                    ) : (
                      <a href={j.result_url} target="_blank" rel="noreferrer" className="text-neutral-900 underline">
                        View result
                      </a>
                    )
                  ) : j.status === "failed" ? (
                    <span className="text-xs text-red-700">{j.error}</span>
                  ) : null}
                </td>
              </tr>
            ))}
            {jobs && shown.length === 0 && (
              <tr>
                <td colSpan={7} className="p-8 text-center text-neutral-500">
                  {jobs.length === 0 ? "No try-ons yet." : `No ${status} jobs in the latest ${jobs.length}.`}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
