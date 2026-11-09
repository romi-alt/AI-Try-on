"use client";

import { useRouter } from "next/navigation";
import { config } from "@/lib/config";
import { useKioskStore } from "@/store/useKioskStore";

/** Things a shopper can do about their own session. Nothing here changes the kiosk for the next person. */
export function SettingsView() {
  const reset = useKioskStore((s) => s.reset);
  const router = useRouter();
  const total = config.idleWarnSeconds + config.idleGraceSeconds;

  return (
    <div className="scroll-y min-h-0 flex-1 space-y-6 p-10">
      <h1 className="text-5xl font-semibold">Settings</h1>

      <section className="glass space-y-4 rounded-3xl p-8">
        <h2 className="text-3xl font-semibold">Your privacy</h2>
        <ul className="list-disc space-y-2 pl-8 text-2xl text-mist/80">
          <li>The photo of you is deleted within an hour.</li>
          <li>Your outfit and cart are cleared when you finish or the screen goes idle.</li>
          <li>The scanner reads codes without saving any picture.</li>
        </ul>
      </section>

      <section className="glass space-y-4 rounded-3xl p-8">
        <h2 className="text-3xl font-semibold">End my session</h2>
        <p className="text-2xl text-mist/70">Clears your photo, outfit and cart from this screen and returns to the start.</p>
        <button
          type="button"
          className="btn-primary h-20 text-2xl"
          onClick={() => {
            reset();
            router.push("/");
          }}
        >
          End session now
        </button>
      </section>

      <p className="text-xl text-mist/50">
        {total > 0 ? `This screen clears itself after ${total} seconds without a touch.` : "Automatic clearing is off."}
      </p>
    </div>
  );
}
