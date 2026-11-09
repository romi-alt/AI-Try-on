import Link from "next/link";
import { MirrorIcon } from "@/components/Icons";

/** The idle screen. Tapping anywhere starts a visit. It also marks the start of every new shopper's session. */
export function AttractScreen() {
  return (
    <Link
      href="/try-on"
      aria-label="Tap to start"
      className="relative flex h-screen w-full flex-col items-center justify-center gap-14 overflow-hidden p-12 text-center"
    >
      <div aria-hidden className="pointer-events-none absolute inset-0">
        <div className="absolute left-1/2 top-1/3 h-[900px] w-[900px] -translate-x-1/2 -translate-y-1/2 animate-pulse rounded-full bg-accent/10 blur-3xl" />
      </div>
      <div className="relative flex flex-col items-center gap-10">
        <span className="glass flex h-40 w-40 items-center justify-center rounded-full text-accent">
          <MirrorIcon className="h-20 w-20" />
        </span>
        <p className="text-2xl uppercase tracking-[0.5em] text-accent">AI Try-On Mirror</p>
        <h1 className="text-8xl font-semibold leading-[1.05]">
          See it on you.
          <br />
          Before you try it on.
        </h1>
        <p className="mx-auto max-w-2xl text-3xl text-mist/70">Step in front of the mirror, pick what you love, and we&apos;ll show you wearing it.</p>
      </div>
      <span className="btn-primary relative h-28 px-20 text-4xl">Tap to start</span>
    </Link>
  );
}
