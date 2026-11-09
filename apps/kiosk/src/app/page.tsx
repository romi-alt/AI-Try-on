import Link from "next/link";

export default function AttractPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-10 p-8 text-center">
      <div className="space-y-3">
        <p className="text-sm uppercase tracking-[0.4em] text-accent">AI Try-On Mirror</p>
        <h1 className="text-5xl font-semibold leading-tight md:text-7xl">
          See it on you.
          <br />
          Before you try it on.
        </h1>
        <p className="mx-auto max-w-xl text-lg text-mist/70">
          Step in front of the mirror, pick a garment, and we&apos;ll render it on you in seconds.
        </p>
      </div>
      <Link
        href="/try-on"
        className="rounded-full bg-mist px-10 py-5 text-xl font-medium text-ink transition hover:scale-[1.02] active:scale-[0.98]"
      >
        Tap to start
      </Link>
    </main>
  );
}
