"use client";

/* eslint-disable @next/next/no-img-element */
import { useEffect, useState } from "react";
import { api, type TryOnJob } from "@/lib/api";

const statusColor: Record<TryOnJob["status"], string> = {
  queued: "bg-neutral-200 text-neutral-700",
  processing: "bg-blue-100 text-blue-800",
  done: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
};

export default function JobsPage() {
  const [jobs, setJobs] = useState<TryOnJob[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.listJobs().then(setJobs).catch((e: Error) => setError(e.message));
    void load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">Try-on jobs</h1>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      <table className="w-full overflow-hidden rounded-lg border border-neutral-200 bg-white text-sm">
        <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
          <tr>
            <th className="p-3">Job</th>
            <th className="p-3">Status</th>
            <th className="p-3">Created</th>
            <th className="p-3">Result</th>
            <th className="p-3">Error</th>
          </tr>
        </thead>
        <tbody>
          {jobs.map((j) => (
            <tr key={j.id} className="border-t border-neutral-100">
              <td className="p-3 font-mono text-xs">{j.id.slice(0, 8)}</td>
              <td className="p-3">
                <span className={`rounded-full px-2 py-0.5 text-xs ${statusColor[j.status]}`}>{j.status}</span>
              </td>
              <td className="p-3">{new Date(j.created_at).toLocaleString()}</td>
              <td className="p-3">
                {j.result_url ? (
                  <a href={j.result_url} target="_blank" rel="noreferrer">
                    <img src={j.result_url} alt="" className="h-14 w-12 rounded object-cover" />
                  </a>
                ) : (
                  "–"
                )}
              </td>
              <td className="max-w-xs truncate p-3 text-xs text-red-700">{j.error ?? ""}</td>
            </tr>
          ))}
          {jobs.length === 0 && (
            <tr>
              <td colSpan={5} className="p-6 text-center text-neutral-500">
                No jobs yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
