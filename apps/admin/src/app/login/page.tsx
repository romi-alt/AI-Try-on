"use client";

import { signIn } from "next-auth/react";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

const MESSAGES: Record<string, string> = {
  CredentialsSignin: "That email and password don't match.",
  TooManyAttempts: "Too many failed attempts. Wait a few minutes and try again.",
  NotConfigured: "No admin users are configured on the server (ADMIN_USERS).",
  SessionRequired: "Sign in to continue.",
};

function LoginForm() {
  const params = useSearchParams();
  const callbackUrl = params.get("callbackUrl") ?? "/";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(params.get("error") ? (MESSAGES[params.get("error") as string] ?? "Sign in failed.") : null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await signIn("credentials", { email, password, redirect: false, callbackUrl });
    setBusy(false);
    if (res?.ok && !res.error) {
      // Only ever go to a path on this site.
      const target = res.url ? new URL(res.url, window.location.origin) : null;
      window.location.href = target && target.origin === window.location.origin ? target.pathname + target.search : "/";
      return;
    }
    setError(MESSAGES[res?.error ?? ""] ?? "Sign in failed. Try again.");
  }

  return (
    <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl border border-neutral-200 bg-white p-8 shadow-sm">
      <h1 className="text-xl font-semibold">ELEVARIQ Admin</h1>
      <label className="block text-sm">
        <span className="mb-1 block text-neutral-600">Email</span>
        <input type="email" required autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} className="w-full rounded-md border border-neutral-300 px-3 py-2" />
      </label>
      <label className="block text-sm">
        <span className="mb-1 block text-neutral-600">Password</span>
        <input type="password" required autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} className="w-full rounded-md border border-neutral-300 px-3 py-2" />
      </label>
      {error && (
        <p role="alert" className="rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">
          {error}
        </p>
      )}
      <button type="submit" disabled={busy} className="w-full rounded-md bg-neutral-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50">
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="grid min-h-screen place-items-center bg-neutral-50 p-4">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
