const STEPS = [
  ["Choose", "Tap items in the shop, pick a size and colour, and add them to your outfit. Up to five at once."],
  ["Step in front of the mirror", "Tap Try it on. The screen guides you: step back until you're fully in view, and stand in the middle."],
  ["Hold still", "When you're steady for a moment, a 3-2-1 countdown starts and the photo is taken for you."],
  ["See your look", "Your outfit appears on you in about a minute. Switch between looks, or tap a suggestion to try more."],
  ["Take it home", "Add the pieces you like to your cart. Scan the QR code to check out on your phone, or ask us to bring a size to you."],
] as const;

export function HelpView() {
  return (
    <div className="scroll-y min-h-0 flex-1 p-10">
      <h1 className="mb-8 text-5xl font-semibold">How it works</h1>
      <ol className="space-y-5">
        {STEPS.map(([title, text], i) => (
          <li key={title} className="glass flex gap-6 rounded-3xl p-6">
            <span className="flex h-16 w-16 flex-none items-center justify-center rounded-full bg-accent text-3xl font-semibold text-ink">{i + 1}</span>
            <div>
              <h2 className="text-3xl font-semibold">{title}</h2>
              <p className="mt-1 text-2xl leading-snug text-mist/75">{text}</p>
            </div>
          </li>
        ))}
      </ol>
      <p className="mt-8 text-2xl text-mist/70">Need a hand? Choose an item and tap <b>Request Outfit</b> on your look, and a team member will bring it to you.</p>
    </div>
  );
}
