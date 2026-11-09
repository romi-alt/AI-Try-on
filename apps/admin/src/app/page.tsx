"use client";

import { useEffect, useState } from "react";
import { api, type Stats } from "@/lib/api";

export default function OverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.stats().then(setStats).catch((e: Error) => setError(e.message));
    const id = setInterval(() => api.stats().then(setStats).catch(() => undefined), 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">Overview</h1>
      {error && <p className="mb-4 text-sm text-red-600">API error: {error}</p>}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <Stat label="Active garments" value={stats?.garments_active} />
        <Stat label="Sessions today" value={stats?.sessions_today} />
        <Stat label="Try-ons today" value={stats?.jobs_today} />
        <Stat label="Failed today" value={stats?.jobs_failed_today} />
        <Stat label="Queue depth" value={stats?.queue_depth} />
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number | undefined }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-neutral-500">{label}</p>
      <p className="mt-1 text-3xl font-semibold tabular-nums">{value ?? "–"}</p>
    </div>
  );
}
