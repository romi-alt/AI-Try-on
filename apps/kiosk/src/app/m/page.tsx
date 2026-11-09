"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/** For a phone that cannot read the QR: type the code shown under it. */
export default function EnterCodePage() {
  const router = useRouter();
  const [code, setCode] = useState("");
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col justify-center gap-5 p-6">
      <h1 className="text-3xl font-semibold">Open your look</h1>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault();
          const c = code.trim().toUpperCase();
          if (c) router.push(`/m/${encodeURIComponent(c)}`);
        }}
      >
        <label className="flex flex-col gap-2 text-lg text-mist/80">
          The code under the QR on the mirror
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            autoCapitalize="characters"
            autoComplete="off"
            spellCheck={false}
            className="min-h-16 rounded-2xl border border-white/20 bg-white/5 px-4 text-center text-3xl uppercase tracking-[0.3em] text-mist outline-none focus:border-accent"
          />
        </label>
        <button type="submit" className="btn-primary">
          Open
        </button>
      </form>
    </main>
  );
}
