"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Banner } from "@/components/Banner";
import { api, ApiError } from "@/lib/api";
import { config } from "@/lib/config";
import type { Stats } from "@/lib/types";

function Stat({ label, value, hint, tone, href }: { label: string; value: string; hint?: string; tone?: "bad"; href?: string }) {
  const body = (
    <div className="h-full rounded-lg border border-neutral-200 bg-white p-4">
      <p className="text-xs uppercase tracking-wide text-neutral-500">{label}</p>
      <p className={`mt-1 text-3xl font-semibold tabular-nums ${tone === "bad" ? "text-red-600" : ""}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-neutral-500">{hint}</p>}
    </div>
  );
  return href ? (
    <Link href={href} className="block transition hover:shadow-sm">
      {body}
    </Link>
  ) : (
    body
  );
}

export default function OverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      api
        .stats()
        .then((s) => !cancelled && (setStats(s), setError(null)))
        .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Couldn't load the stats."));
    void load();
    const id = setInterval(load, config.statsPollMs);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  const queue = stats?.queue_depth;
  return (
    <div>
      <h1 className="mb-6 text-2xl font-semibold">Overview</h1>
      {error && <Banner>{error}</Banner>}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <Stat label="Products in stock" value={stats ? String(stats.products_in_stock) : "-"} href="/products" />
        <Stat label="Sessions today" value={stats ? String(stats.sessions_today) : "-"} href="/sessions" />
        <Stat label="Try-ons today" value={stats ? String(stats.jobs_today) : "-"} href="/jobs" />
        <Stat
          label="Failed today"
          value={stats ? String(stats.jobs_failed_today) : "-"}
          tone={stats && stats.jobs_failed_today > 0 ? "bad" : undefined}
          href="/jobs"
        />
        <Stat
          label="Queue depth"
          value={queue === undefined ? "-" : queue < 0 ? "n/a" : String(queue)}
          hint={queue !== undefined && queue < 0 ? "Redis is unreachable" : "jobs waiting for the worker"}
        />
      </div>
    </div>
  );
}
