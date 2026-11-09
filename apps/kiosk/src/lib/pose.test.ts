import { describe, expect, it } from "vitest";
import { centeredCrop } from "./capture";
import { assess, captureRegion, DEFAULTS, idealLandmarks, LM, type Landmark, MESSAGES, PoseGuide, type Region } from "./pose";
import { person } from "./testing/person";

const LANDSCAPE = captureRegion(1920, 1080); // the middle 3:4 of a 16:9 webcam frame
const WHOLE: Region = { left: 0, right: 1, top: 0, bottom: 1 };

describe("captureRegion", () => {
  it("is the middle 3:4 slice of a landscape frame", () => {
    expect(LANDSCAPE.left).toBeCloseTo(0.2891, 3);
    expect(LANDSCAPE.right).toBeCloseTo(0.7109, 3);
    expect([LANDSCAPE.top, LANDSCAPE.bottom]).toEqual([0, 1]);
  });

  it("agrees with the crop the photo is actually cut with", () => {
    for (const [w, h] of [[1920, 1080], [1280, 720], [640, 480], [1080, 1920], [720, 1280], [864, 1152]] as const) {
      const r = captureRegion(w, h);
      const c = centeredCrop(w, h);
      expect(r.left * w).toBeCloseTo(c.sx, 0);
      expect((r.right - r.left) * w).toBeCloseTo(c.sw, 0);
      expect(r.top * h).toBeCloseTo(c.sy, 0);
      expect((r.bottom - r.top) * h).toBeCloseTo(c.sh, 0);
    }
  });

  it("trims the top and bottom of a frame that is taller than 3:4", () => {
    const r = captureRegion(1080, 1920);
    expect([r.left, r.right]).toEqual([0, 1]);
    expect(r.top).toBeGreaterThan(0.1);
  });
});

describe("assess", () => {
  it("is happy with someone fully in frame in the middle", () => {
    expect(assess(person(), LANDSCAPE)).toBe("hold_still");
  });

  it("sees no one when there are no landmarks, or only a face or a hand", () => {
    expect(assess(null, LANDSCAPE)).toBe("no_person");
    expect(assess(undefined, LANDSCAPE)).toBe("no_person");
    expect(assess([], LANDSCAPE)).toBe("no_person");
    const faceOnly = person().map((p, i) => (i === LM.NOSE ? p : { ...p, visibility: 0.05 }));
    expect(assess(faceOnly, LANDSCAPE)).toBe("no_person");
  });

  it("says step back until the ankles are in the picture", () => {
    expect(assess(person({ bottom: 1.2 }), LANDSCAPE)).toBe("step_back"); // ankles below the frame
    expect(assess(person({ bottom: 0.995 }), LANDSCAPE)).toBe("step_back"); // touching the bottom edge
    const hidden = person();
    hidden[LM.LEFT_ANKLE] = { ...hidden[LM.LEFT_ANKLE], visibility: 0.05 }; // one ankle not seen at all
    expect(assess(hidden, LANDSCAPE)).toBe("step_back");
  });

  it("accepts low-confidence ankles that are inside the picture: long garments hide the legs", () => {
    // Measured with MediaPipe on a woman in a sharara: knees 0.27, ankles 0.25 and 0.35, but placed correctly.
    const sharara = person();
    for (const i of [LM.LEFT_KNEE, LM.RIGHT_KNEE]) sharara[i] = { ...sharara[i], visibility: 0.27 };
    sharara[LM.LEFT_ANKLE] = { ...sharara[LM.LEFT_ANKLE], visibility: 0.25 };
    sharara[LM.RIGHT_ANKLE] = { ...sharara[LM.RIGHT_ANKLE], visibility: 0.35 };
    expect(assess(sharara, LANDSCAPE)).toBe("hold_still");
  });

  it("still says step back when low-confidence ankles are below the picture (cut off at the knees)", () => {
    const cut = person({ bottom: 1.2 }).map((p, i) => (i === LM.LEFT_ANKLE || i === LM.RIGHT_ANKLE ? { ...p, visibility: 0.3 } : p));
    expect(assess(cut, LANDSCAPE)).toBe("step_back");
  });

  it("says step back until the head is in the picture", () => {
    expect(assess(person({ top: -0.1 }), LANDSCAPE)).toBe("step_back");
    expect(assess(person({ top: 0.005 }), LANDSCAPE)).toBe("step_back");
  });

  it("says step closer when the shopper is far away", () => {
    expect(assess(person({ top: 0.5, bottom: 0.8 }), LANDSCAPE)).toBe("step_closer"); // 0.30 of the height
    expect(assess(person({ top: 0.5, bottom: 0.89 }), LANDSCAPE)).toBe("step_closer"); // 0.39: still too small
    expect(assess(person({ top: 0.42, bottom: 0.92 }), LANDSCAPE)).toBe("hold_still"); // 0.50
    expect(assess(person({ top: 0.45, bottom: 0.87 }), LANDSCAPE)).toBe("hold_still"); // 0.42: far back, but enough
  });

  it("classifies the real MediaPipe detections of the three test videos", () => {
    // Landmarks MediaPipe Pose (lite) actually returned for a person in a lunge: centred, off to the right, and zoomed in.
    const at = (pts: Record<number, [number, number, number]>): Landmark[] => {
      const lm: Landmark[] = Array.from({ length: 33 }, () => ({ x: 0.5, y: 0.5, visibility: 0 }));
      for (const [i, [x, y, v]] of Object.entries(pts)) lm[Number(i)] = { x, y, visibility: v };
      return lm;
    };
    const centred = at({ 0: [0.471, 0.419, 1], 11: [0.534, 0.481, 1], 12: [0.461, 0.491, 1], 23: [0.516, 0.709, 1], 24: [0.474, 0.706, 1], 25: [0.588, 0.818, 1], 26: [0.379, 0.732, 1], 27: [0.669, 0.915, 0.99], 28: [0.374, 0.909, 0.99] });
    const right = at({ 0: [0.72, 0.419, 1], 11: [0.778, 0.484, 1], 12: [0.707, 0.49, 1], 23: [0.762, 0.708, 1], 24: [0.72, 0.706, 1], 25: [0.832, 0.813, 1], 26: [0.625, 0.732, 1], 27: [0.911, 0.911, 0.99], 28: [0.618, 0.91, 0.99] });
    const close = at({ 0: [0.436, 0.197, 1], 11: [0.565, 0.318, 1], 12: [0.419, 0.331, 1], 23: [0.528, 0.771, 1], 24: [0.442, 0.764, 1], 25: [0.624, 0.948, 0.98], 26: [0.26, 0.823, 1], 27: [0.647, 0.963, 0.54], 28: [0.258, 1.126, 0.97] });
    expect(assess(centred, LANDSCAPE)).toBe("hold_still");
    expect(assess(right, LANDSCAPE)).toBe("center");
    expect(assess(close, LANDSCAPE)).toBe("step_back");
  });

  it("says centre yourself when off to either side", () => {
    expect(assess(person({ cx: 0.36 }), LANDSCAPE)).toBe("center");
    expect(assess(person({ cx: 0.64 }), LANDSCAPE)).toBe("center");
    expect(assess(person({ cx: 0.1 }), LANDSCAPE)).toBe("center");
  });

  it("allows a small drift from the middle", () => {
    expect(assess(person({ cx: 0.5 + 0.03 }), LANDSCAPE)).toBe("hold_still");
    expect(assess(person({ cx: 0.5 - 0.03 }), LANDSCAPE)).toBe("hold_still");
  });

  it("judges against the photo, not the whole frame", () => {
    // 0.3 is the middle of the left third of the frame: fine for the whole frame, but outside the photo's middle.
    expect(assess(person({ cx: 0.3 }), WHOLE)).toBe("center");
    expect(assess(person({ cx: 0.5 }), WHOLE)).toBe("hold_still");
    expect(assess(person({ cx: 0.3, spread: 0.01 }), LANDSCAPE)).toBe("center");
  });

  it("does not count outstretched arms as being off-centre", () => {
    const arms = person();
    arms[15] = { x: 0.1, y: 0.35, visibility: 0.99 }; // wrists far out to the sides
    arms[16] = { x: 0.9, y: 0.35, visibility: 0.99 };
    expect(assess(arms, LANDSCAPE)).toBe("hold_still");
  });

  it("reports the first problem when there are several", () => {
    expect(assess(person({ bottom: 1.3, cx: 0.1 }), LANDSCAPE)).toBe("step_back"); // not "center"
  });

  it("has a message for each state, and the three the design asks for", () => {
    expect(MESSAGES.step_back).toBe("Step back");
    expect(MESSAGES.center).toBe("Center yourself");
    expect(MESSAGES.hold_still).toBe("Hold still");
    expect(DEFAULTS.minVisibility).toBeGreaterThan(0);
  });
});

describe("idealLandmarks", () => {
  it("is in position for any camera shape, so the fallback countdown can start", () => {
    for (const [w, h] of [[1920, 1080], [1080, 1920], [640, 480]] as const) {
      const region = captureRegion(w, h);
      expect(assess(idealLandmarks(region), region)).toBe("hold_still");
    }
  });
});

describe("PoseGuide", () => {
  const feed = (guide: PoseGuide, frames: Landmark[][], startMs = 0, everyMs = 100) =>
    frames.map((f, i) => guide.update(f, LANDSCAPE, startMs + i * everyMs));

  it("is ready after the shopper has been steady for a full second", () => {
    const guide = new PoseGuide();
    const out = feed(guide, Array.from({ length: 12 }, () => person()));
    expect(out[0]).toMatchObject({ code: "hold_still", steadyMs: 0, progress: 0 });
    expect(out[9].code).toBe("hold_still"); // 900 ms: not yet
    expect(out[9].progress).toBeCloseTo(0.9);
    expect(out[10]).toMatchObject({ code: "ready", steadyMs: 1000, progress: 1 });
    expect(out[11].code).toBe("ready");
  });

  it("is not ready one millisecond early", () => {
    const guide = new PoseGuide();
    feed(guide, Array.from({ length: 10 }, () => person()));
    expect(guide.update(person(), LANDSCAPE, 999).code).toBe("hold_still");
    expect(guide.update(person(), LANDSCAPE, 1000).code).toBe("ready");
  });

  it("starts the second again when the shopper moves", () => {
    const guide = new PoseGuide();
    feed(guide, Array.from({ length: 8 }, () => person()));
    const moved = guide.update(person({ cx: 0.54 }), LANDSCAPE, 800); // a big step sideways, still inside the middle
    expect(moved).toMatchObject({ code: "hold_still", steadyMs: 0 });
    const out = feed(guide, Array.from({ length: 12 }, () => person({ cx: 0.54 })), 900);
    expect(out[8].code).toBe("hold_still"); // 900 ms after the move at t=800
    expect(out[9].code).toBe("ready"); // a fresh second counted from the new spot (t=800 to t=1800)
  });

  it("ignores the tiny jitter of a person standing still", () => {
    const guide = new PoseGuide();
    const frames = Array.from({ length: 14 }, (_, i) => person({ cx: 0.5 + (i % 2 ? 0.004 : -0.004), top: 0.12 + (i % 3) * 0.002 }));
    expect(feed(guide, frames).at(-1)?.code).toBe("ready");
  });

  it("is never ready while someone sways or walks about", () => {
    const guide = new PoseGuide();
    const frames = Array.from({ length: 30 }, (_, i) => person({ cx: 0.5 + Math.sin(i / 2) * 0.05 }));
    expect(feed(guide, frames).every((g) => g.code !== "ready")).toBe(true);
  });

  it("resets the moment they leave position, then needs a whole new second", () => {
    const guide = new PoseGuide();
    feed(guide, Array.from({ length: 11 }, () => person()));
    expect(guide.update(null, LANDSCAPE, 1100)).toMatchObject({ code: "no_person", steadyMs: 0, progress: 0 });
    expect(guide.update(person(), LANDSCAPE, 1200)).toMatchObject({ code: "hold_still", steadyMs: 0 });
    expect(guide.update(person({ bottom: 1.2 }), LANDSCAPE, 1300).code).toBe("step_back");
    expect(guide.update(person(), LANDSCAPE, 1400).steadyMs).toBe(0);
  });

  it("needs several frames, not one lucky one, even if time has passed", () => {
    const guide = new PoseGuide();
    guide.update(person(), LANDSCAPE, 0);
    expect(guide.update(person(), LANDSCAPE, 5000).code).toBe("hold_still"); // two frames five seconds apart
  });

  it("can be reset by the screen between attempts", () => {
    const guide = new PoseGuide();
    feed(guide, Array.from({ length: 12 }, () => person()));
    guide.reset();
    expect(guide.update(person(), LANDSCAPE, 2000)).toMatchObject({ code: "hold_still", steadyMs: 0 });
  });

  it("takes its timing from options", () => {
    const guide = new PoseGuide({ steadyMs: 500, minSamples: 3 });
    const out = feed(guide, Array.from({ length: 8 }, () => person()));
    expect(out.find((g) => g.code === "ready")?.steadyMs).toBe(500);
  });
});
