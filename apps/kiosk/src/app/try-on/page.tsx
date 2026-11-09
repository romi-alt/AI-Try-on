"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect } from "react";
import { AppShell } from "@/components/AppShell";
import { CaptureScreen } from "@/components/CaptureScreen";
import { ConsentScreen } from "@/components/ConsentScreen";
import { ErrorScreen } from "@/components/ErrorScreen";
import { IdleWarning } from "@/components/IdleWarning";
import { ProgressScreen } from "@/components/ProgressScreen";
import { ResultScreen } from "@/components/ResultScreen";
import { ShareModal } from "@/components/ShareModal";
import { useIdleReset } from "@/hooks/useIdleReset";
import { useKioskStore } from "@/store/useKioskStore";

export default function TryOnPage() {
  const phase = useKioskStore((s) => s.phase);
  const reset = useKioskStore((s) => s.reset);
  const router = useRouter();

  // Leaving the page ends the session: closes the live connection and forgets the shopper.
  useEffect(() => () => reset(), [reset]);

  // A shopper who walks away: clear the screen first (so the next person never sees their look), then show the
  // attract screen.
  const endAbandonedSession = useCallback(() => {
    reset();
    router.push("/");
  }, [reset, router]);
  const { secondsLeft, stay } = useIdleReset(phase, endAbandonedSession);
  const warning = secondsLeft !== null && <IdleWarning secondsLeft={secondsLeft} onStay={stay} />;

  if (phase === "consent" || phase === "starting") {
    return (
      <>
        <ConsentScreen />
        {warning}
      </>
    );
  }

  return (
    <>
      {phase === "browsing" && <AppShell />}
      {(phase === "capturing" || phase === "countdown") && <CaptureScreen />}
      {(phase === "uploading" || phase === "working") && <ProgressScreen />}
      {phase === "result" && <ResultScreen />}
      {phase === "error" && <ErrorScreen />}
      <ShareModal />
      {warning}
    </>
  );
}
