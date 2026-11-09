"use client";

import { useCallback, useEffect, useState } from "react";
import { Banner } from "@/components/Banner";
import { api, ApiError } from "@/lib/api";
import { config } from "@/lib/config";
import { shortId } from "@/lib/jobs";
import type { AdminSession } from "@/lib/types";

export default function SessionsPage() {
  const [sessions, setSessions] = useState<AdminSession[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    api
      .listSessions()
      .then((s) => (setSessions(s), setError(null)))
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Couldn't load the sessions."))
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Sessions</h1>
        <button type="button" onClick={load} disabled={loading} className="rounded-md border border-neutral-300 px-4 py-2 text-sm hover:bg-neutral-100 disabled:opacity-50">
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>
      {error && <Banner>{error}</Banner>}
      <p className="mb-3 text-sm text-neutral-500">The latest {config.listLimit}. Every session starts with the shopper&apos;s consent.</p>
      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
            <tr>
              <th className="p-3">Session</th>
              <th className="p-3">Started</th>
              <th className="p-3">Consent</th>
              <th className="p-3 text-right">Try-ons</th>
            </tr>
          </thead>
          <tbody>
            {(sessions ?? []).map((s) => (
              <tr key={s.id} className="border-t border-neutral-100">
                <td className="p-3 font-mono text-xs" title={s.id}>
                  {shortId(s.id)}
                </td>
                <td className="p-3">{new Date(s.started_at).toLocaleString()}</td>
                <td className="p-3">{s.consent_given ? "Given" : "No"}</td>
                <td className="p-3 text-right tabular-nums">{s.job_count}</td>
              </tr>
            ))}
            {sessions && sessions.length === 0 && (
              <tr>
                <td colSpan={4} className="p-8 text-center text-neutral-500">
                  No sessions yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
