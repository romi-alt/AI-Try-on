import { privacyConfig, privacySections, privacySummary, retentionText } from "@/lib/privacy";

export const metadata = { title: "Privacy" };

/** The full notice as an ordinary page, for a phone or a printout. */
export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-2xl space-y-8 p-6 pb-24 select-text">
      <header>
        <p className="text-sm uppercase tracking-[0.3em] text-accent">{privacyConfig.shopName}</p>
        <h1 className="mt-2 text-3xl font-semibold">Privacy at the mirror</h1>
        <p className="mt-2 text-mist/70">Your photo is deleted within {retentionText()}.</p>
      </header>
      <ul className="space-y-2 text-lg">
        {privacySummary().map((l) => (
          <li key={l}>✓ {l}</li>
        ))}
      </ul>
      {privacySections().map((s) => (
        <section key={s.heading} className="space-y-2">
          <h2 className="text-xl font-semibold">{s.heading}</h2>
          {s.body.map((p) => (
            <p key={p.slice(0, 40)} className="leading-relaxed text-mist/80">
              {p}
            </p>
          ))}
        </section>
      ))}
    </main>
  );
}
