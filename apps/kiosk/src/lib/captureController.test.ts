import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CaptureController, type CaptureEvents } from "./captureController";
import { captureRegion, type Landmark } from "./pose";
import { person } from "./testing/person";

type Frame = { id: number; score: number };

function setup(over: Partial<ConstructorParameters<typeof CaptureController>[2]> = {}) {
  const scene = { landmarks: person() as Landmark[] | null, scores: [] as number[], tick: 0, fail: false };
  const log: string[] = [];
  const released: Frame[] = [];
  const events: CaptureEvents = {
    onGuidance: (g) => log.push(`g:${g.code}`),
    onCountdown: (n) => log.push(`n:${n}`),
    onCountdownCancelled: () => log.push("cancelled"),
    onCaptured: () => log.push("captured"),
    onGiveUp: () => log.push("giveup"),
    onError: (e) => log.push(`error:${e.message}`),
  };
  const encoded: Frame[] = [];
  const controller = new CaptureController<Frame>(
    {
      detect: async () => {
        if (scene.fail) throw new Error("camera lost");
        return scene.landmarks;
      },
      grab: async () => {
        const id = scene.tick++;
        return { frame: { id, score: scene.scores[id] ?? 1 }, score: scene.scores[id] ?? 1 };
      },
      release: (f) => released.push(f),
      encode: async (f) => {
        encoded.push(f);
        return new Blob(["jpeg"]);
      },
      region: () => captureRegion(1920, 1080),
      now: () => Date.now(),
    },
    events,
    over,
  );
  return { scene, log, released, encoded, controller };
}

const run = (ms: number) => vi.advanceTimersByTimeAsync(ms);
const counts = (log: string[]) => log.filter((l) => l.startsWith("n:"));

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("CaptureController", () => {
  it("counts down only after a steady second, then takes the photo", async () => {
    const { controller, log } = setup();
    controller.start();

    await run(900);
    expect(counts(log)).toEqual([]); // still holding still
    expect(log).toContain("g:hold_still");

    await run(300); // steady for a second now
    expect(counts(log)).toEqual(["n:3"]);
    await run(1000);
    expect(counts(log)).toEqual(["n:3", "n:2"]);
    await run(1000);
    expect(counts(log)).toEqual(["n:3", "n:2", "n:1"]);
    expect(log).not.toContain("captured");
    await run(1100);
    expect(log.at(-1)).toBe("captured");
    expect(counts(log)).toEqual(["n:3", "n:2", "n:1"]); // and no "n:0"
  });

  it("picks the highest score within the last five frames", async () => {
    const { controller, scene, encoded } = setup({ countdownSeconds: 1, steadyMs: 500 });
    // ticks come every 100 ms; ready at ~600 ms, capture at ~1600 ms (tick 16). Make frames 12..16 mixed:
    scene.scores = Array.from({ length: 40 }, (_, i) => (i === 14 ? 500 : i === 5 ? 9999 : 20));
    controller.start();
    await run(1750);
    expect(encoded).toHaveLength(1);
    expect(encoded[0].id).toBe(14); // not the older 9999 frame, which is outside the last five
  });

  it("releases frames that fall out of the recent five", async () => {
    const { controller, released } = setup();
    controller.start();
    await run(1500);
    expect(released.length).toBeGreaterThan(5);
    expect(new Set(released.map((f) => f.id)).size).toBe(released.length); // each only once
  });

  it("cancels the countdown if the shopper walks out of frame for too long, and can start again", async () => {
    const { controller, scene, log } = setup();
    controller.start();
    await run(1300);
    expect(counts(log)).toEqual(["n:3"]);

    scene.landmarks = null; // they walk away
    await run(1500);
    expect(log).toContain("cancelled");
    expect(log).not.toContain("captured");
    const before = counts(log).length;

    scene.landmarks = person(); // and come back
    await run(2000);
    expect(counts(log).length).toBeGreaterThan(before); // a fresh countdown
  });

  it("does not cancel for a moment's wobble", async () => {
    const { controller, scene, log } = setup();
    controller.start();
    await run(1300);
    scene.landmarks = person({ bottom: 1.2 }); // ankles briefly out of the picture
    await run(400);
    scene.landmarks = person();
    await run(3500);
    expect(log).not.toContain("cancelled");
    expect(log).toContain("captured");
  });

  it("keeps counting while they shift about, as long as they stay in frame", async () => {
    const { controller, scene, log } = setup();
    controller.start();
    await run(1300);
    for (let i = 0; i < 20; i++) {
      scene.landmarks = person({ cx: 0.5 + (i % 2 ? 0.05 : -0.05) }); // swaying: not still, but in position
      await run(100);
    }
    expect(log).not.toContain("cancelled");
    await run(2500);
    expect(log).toContain("captured");
  });

  it("gives up if nobody ever steps in front of it", async () => {
    const { controller, scene, log } = setup({ noPersonTimeoutMs: 5000 });
    scene.landmarks = null;
    controller.start();
    await run(4500);
    expect(log).not.toContain("giveup");
    await run(1000);
    expect(log).toContain("giveup");
  });

  it("the give-up clock restarts when someone appears", async () => {
    const { controller, scene, log } = setup({ noPersonTimeoutMs: 5000 });
    scene.landmarks = null;
    controller.start();
    await run(4000);
    scene.landmarks = person({ cx: 0.9 }); // someone there, but off to the side
    await run(500);
    scene.landmarks = null;
    await run(4000);
    expect(log).not.toContain("giveup"); // 4 s since they left, not 8
    await run(1500);
    expect(log).toContain("giveup");
  });

  it("stops cleanly: no more events, and the five held frames are released", async () => {
    const { controller, log, released } = setup();
    controller.start();
    await run(1000);
    const releasedBefore = released.length;
    controller.stop();
    expect(released.length - releasedBefore).toBe(5); // the whole recent set, freed at once
    const seen = log.length;
    await run(5000);
    expect(log.length).toBe(seen);
    expect(released.length - releasedBefore).toBe(5); // and nothing more once stopped
  });

  it("reports an error from the camera or pose step and stops", async () => {
    const { controller, scene, log } = setup();
    controller.start();
    await run(300);
    scene.fail = true;
    await run(300);
    expect(log.some((l) => l.startsWith("error:camera lost"))).toBe(true);
    const seen = log.length;
    await run(1000);
    expect(log.length).toBe(seen);
  });

  it("starts a new countdown from three each time", async () => {
    const { controller, scene, log } = setup();
    controller.start();
    await run(1300);
    scene.landmarks = null;
    await run(1500);
    scene.landmarks = person();
    await run(1500);
    expect(counts(log).filter((l) => l === "n:3")).toHaveLength(2);
  });
});
