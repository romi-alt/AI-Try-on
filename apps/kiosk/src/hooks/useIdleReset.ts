"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { config } from "@/lib/config";
import { createIdleTimer, isIdleTrackedPhase, type IdleTimer } from "@/lib/idleTimer";

/**
 * Ends an abandoned session. While `phase` is one a shopper can walk away from, input on the page keeps it
 * alive; after `idleWarnSeconds` without any, `secondsLeft` becomes a number (show a "still there?" screen),
 * and when it runs out `onExpire` is called. Call `stay()` from the screen's button.
 *
 * The timer restarts, in full, whenever the phase changes, and is off while a try-on is in progress.
 */
export function useIdleReset(phase: string, onExpire: () => void) {
  const [secondsLeft, setSecondsLeft] = useState<number | null>(null);
  const timer = useRef<IdleTimer | null>(null);
  const tracked = isIdleTrackedPhase(phase);

  useEffect(() => {
    if (!tracked) return;
    const t = createIdleTimer({
      warnAfterMs: config.idleWarnSeconds * 1000,
      graceMs: config.idleGraceSeconds * 1000,
      onWarn: () => setSecondsLeft(config.idleGraceSeconds),
      onTick: setSecondsLeft,
      onResume: () => setSecondsLeft(null),
      onExpire: () => {
        setSecondsLeft(null);
        onExpire();
      },
    });
    timer.current = t;
    t.start();

    // A press or touch shows someone is there, but must not be what dismisses the warning: the warning would
    // vanish on press, and the release and click that follow would land on whatever is underneath. Only the
    // warning's own click (via `stay`) or a key press answers it.
    const presence = () => t.activity("presence");
    const confirm = () => t.activity("confirm");
    const presenceEvents = ["pointermove", "wheel", "pointerdown", "touchstart"];
    for (const type of presenceEvents) window.addEventListener(type, presence, { passive: true, capture: true });
    window.addEventListener("keydown", confirm, { passive: true, capture: true });
    return () => {
      for (const type of presenceEvents) window.removeEventListener(type, presence, { capture: true });
      window.removeEventListener("keydown", confirm, { capture: true });
      t.stop();
      timer.current = null;
      setSecondsLeft(null);
    };
    // `phase` is a dependency on purpose: a change of phase is activity, so the period starts again.
  }, [phase, tracked, onExpire]);

  const stay = useCallback(() => timer.current?.activity("confirm"), []);
  return { secondsLeft, stay };
}
