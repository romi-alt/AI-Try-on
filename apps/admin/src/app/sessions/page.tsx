"use client";

import { useEffect, useState } from "react";
import { api, type Session } from "@/lib/api";

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listSessions().then(setSessions).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">Sessions</h1>
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}
      <table className="w-full overflow-hidden rounded-lg border border-neutral-200 bg-white text-sm">
        <thead className="bg-neutral-100 text-left text-xs uppercase tracking-wide text-neutral-500">
          <tr>
            <th className="p-3">Session</th>
            <th className="p-3">Kiosk</th>
            <th className="p-3">Started</th>
            <th className="p-3">Ended</th>
            <th className="p-3">Try-ons</th>
          </tr>
        </thead>
        <tbody>
          {sessions.map((s) => (
            <tr key={s.id} className="border-t border-neutral-100">
              <td className="p-3 font-mono text-xs">{s.id.slice(0, 8)}</td>
              <td className="p-3">{s.kiosk_id}</td>
              <td className="p-3">{new Date(s.started_at).toLocaleString()}</td>
              <td className="p-3">{s.ended_at ? new Date(s.ended_at).toLocaleString() : <em>open</em>}</td>
              <td className="p-3 tabular-nums">{s.job_count}</td>
            </tr>
          ))}
          {sessions.length === 0 && (
            <tr>
              <td colSpan={5} className="p-6 text-center text-neutral-500">
                No sessions yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
