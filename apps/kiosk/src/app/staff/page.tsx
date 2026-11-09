"use client";

import { useEffect, useState } from "react";
import { useStaffFeed } from "@/hooks/useStaffFeed";
import { api } from "@/lib/api";
import type { StaffRequest } from "@/lib/types";

const KEY_STORAGE = "staff-key";

function readKey(): string | null {
  try {
    return sessionStorage.getItem(KEY_STORAGE);
  } catch {
    return null;
  }
}
function saveKey(key: string | null) {
  try {
    if (key) sessionStorage.setItem(KEY_STORAGE, key);
    else sessionStorage.removeItem(KEY_STORAGE);
  } catch {
    /* private mode: the key lasts until the page is closed */
  }
}

function waited(since: string, now: number): string {
  const mins = Math.max(0, Math.floor((now - new Date(since).getTime()) / 60_000));
  return mins < 1 ? "just now" : mins === 1 ? "1 min ago" : `${mins} min ago`;
}

function SignIn({ onKey, wrong }: { onKey: (k: string) => void; wrong: boolean }) {
  const [value, setValue] = useState("");
  return (
    <form
      className="glass-strong mx-auto mt-24 flex max-w-md flex-col gap-4 rounded-3xl p-8"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onKey(value.trim());
      }}
    >
      <h1 className="text-3xl font-semibold">Staff requests</h1>
      <label className="flex flex-col gap-2 text-lg text-mist/80">
        Staff key
        <input
          type="password"
          autoComplete="off"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="min-h-16 rounded-2xl border border-white/20 bg-white/5 px-4 text-xl text-mist outline-none focus:border-accent"
        />
      </label>
      {wrong && (
        <p role="alert" className="rounded-xl bg-red-500/15 px-4 py-3 text-red-200">
          That key was not accepted.
        </p>
      )}
      <button type="submit" className="btn-primary">
        Sign in
      </button>
    </form>
  );
}

function RequestCard({ request, onAct, now }: { request: StaffRequest; onAct: (id: string, s: "bringing" | "done") => Promise<void>; now: number }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function act(status: "bringing" | "done") {
    setBusy(true);
    setError(null);
    try {
      await onAct(request.id, status);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update this request");
    } finally {
      setBusy(false);
    }
  }
  const bringing = request.status === "bringing";
  return (
    <li className="glass rounded-3xl p-5" data-status={request.status} data-testid="request">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-2xl font-semibold">{request.product_name}</p>
          <p className="mt-1 text-lg text-mist/80">
            Size {request.size ?? "—"}
            {request.color ? ` · ${request.color}` : ""}
          </p>
          <p className="mt-1 text-base text-mist/60">
            Mirror session {request.session_id.slice(0, 8)} · asked {waited(request.created_at, now)}
          </p>
        </div>
        <span className={`rounded-full px-4 py-1 text-base ${bringing ? "bg-emerald-500/20 text-emerald-200" : "bg-amber-400/20 text-amber-100"}`}>
          {bringing ? "On the way" : "Waiting"}
        </span>
      </div>
      <div className="mt-4 flex gap-3">
        <button type="button" className="btn-ghost flex-1" disabled={busy || bringing} onClick={() => void act("bringing")}>
          Bringing it
        </button>
        <button type="button" className="btn-primary flex-1" disabled={busy} onClick={() => void act("done")}>
          Done
        </button>
      </div>
      {error && (
        <p role="alert" className="mt-3 text-red-200">
          {error}
        </p>
      )}
    </li>
  );
}

export default function StaffPage() {
  const [key, setKey] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setKey(readKey());
    setLoaded(true);
  }, []);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(t);
  }, []);

  const { status, requests } = useStaffFeed(key);
  useEffect(() => {
    if (status === "unauthorized") saveKey(null);
  }, [status]);

  if (!loaded) return null;
  if (!key || status === "unauthorized") {
    return (
      <main className="min-h-screen p-4">
        <SignIn
          wrong={status === "unauthorized"}
          onKey={(k) => {
            saveKey(k);
            setKey(k);
          }}
        />
      </main>
    );
  }

  async function act(id: string, to: "bringing" | "done") {
    // The change comes back over the socket for everyone, this screen included; nothing is applied locally.
    await api.updateStaffRequest(key as string, id, to);
  }

  const pill =
    status === "live"
      ? { text: "Live", cls: "bg-emerald-500/20 text-emerald-200" }
      : status === "offline"
        ? { text: "Reconnecting…", cls: "bg-amber-400/20 text-amber-100" }
        : { text: "Connecting…", cls: "bg-white/10 text-mist/70" };

  return (
    <main className="mx-auto min-h-screen max-w-2xl p-4">
      <header className="flex items-center justify-between py-4">
        <h1 className="text-3xl font-semibold">Requests</h1>
        <div className="flex items-center gap-3">
          <span role="status" className={`rounded-full px-4 py-1 text-base ${pill.cls}`}>
            {pill.text}
          </span>
          <button
            type="button"
            className="btn-ghost min-h-12 px-4 text-base"
            onClick={() => {
              saveKey(null);
              setKey(null);
            }}
          >
            Sign out
          </button>
        </div>
      </header>
      {requests.length === 0 ? (
        <p className="glass rounded-3xl p-8 text-center text-xl text-mist/70">
          {status === "live" ? "No one is waiting. New requests appear here the moment they are made." : "Loading requests…"}
        </p>
      ) : (
        <ul className="space-y-4">
          {requests.map((r) => (
            <RequestCard key={r.id} request={r} onAct={act} now={now} />
          ))}
        </ul>
      )}
    </main>
  );
}
