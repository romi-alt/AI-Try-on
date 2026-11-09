/**
 * Guidance from pose landmarks: is the shopper fully in frame, centred and steady?
 *
 * Landmarks are MediaPipe Pose's 33 points, normalised to the camera frame (x, y in 0..1). Everything here is pure,
 * so the rules are unit tested without a camera. The camera frame is wider than the photo that gets taken (a 3:4
 * portrait cut from its middle), so "centred" and "in frame" are judged against that region, not the whole frame.
 */

export type Landmark = { x: number; y: number; z?: number; visibility?: number };

/** Indexes into MediaPipe Pose's landmark list. */
export const LM = {
  NOSE: 0,
  LEFT_EYE: 2,
  RIGHT_EYE: 5,
  LEFT_SHOULDER: 11,
  RIGHT_SHOULDER: 12,
  LEFT_HIP: 23,
  RIGHT_HIP: 24,
  LEFT_KNEE: 25,
  RIGHT_KNEE: 26,
  LEFT_ANKLE: 27,
  RIGHT_ANKLE: 28,
} as const;

export type GuidanceCode = "no_person" | "step_back" | "step_closer" | "center" | "hold_still" | "ready";

export const MESSAGES: Record<GuidanceCode, string> = {
  no_person: "Step in front of the mirror",
  step_back: "Step back",
  step_closer: "Step a little closer",
  center: "Center yourself",
  hold_still: "Hold still",
  ready: "Hold still", // the countdown is about to start
};

/** The part of the camera frame that becomes the photo, as fractions of the frame. */
export type Region = { left: number; right: number; top: number; bottom: number };

/** The centred portrait (`aspect` = width / height) cut from a frame of the given size, as fractions of the frame. */
export function captureRegion(frameWidth: number, frameHeight: number, aspect = 3 / 4): Region {
  const frameAspect = frameWidth / frameHeight;
  if (frameAspect > aspect) {
    const w = aspect / frameAspect; // keep the full height, trim the sides
    return { left: (1 - w) / 2, right: (1 + w) / 2, top: 0, bottom: 1 };
  }
  const h = frameAspect / aspect; // a frame taller than the photo: keep the full width, trim top and bottom
  return { left: 0, right: 1, top: (1 - h) / 2, bottom: (1 + h) / 2 };
}

export type Thresholds = {
  /** A landmark counts as seen at or above this confidence. */
  minVisibility: number;
  /** How close to the edge of the photo the head or ankles may be, as a fraction of its size. */
  edgeMargin: number;
  /**
   * Nose-to-ankle distance as a fraction of the photo's height; below this the shopper is too far away. Measured on
   * real detections: a person standing comfortably in frame spans about 0.5 to 0.8, so 0.4 only catches someone far back.
   */
  minBodyHeight: number;
  /** How far the body's middle may be from the photo's middle, as a fraction of its width. */
  centerTolerance: number;
  /** How far the head-to-toe line may sit beyond the photo's sides, as a fraction of its width. */
  sideMargin: number;
};

export const DEFAULTS: Thresholds = {
  minVisibility: 0.5,
  edgeMargin: 0.02,
  minBodyHeight: 0.4,
  centerTolerance: 0.14,
  sideMargin: 0.02,
};

const seen = (p: Landmark | undefined, t: Thresholds): p is Landmark =>
  !!p && (p.visibility ?? 1) >= t.minVisibility && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1;

const mean = (xs: number[]) => xs.reduce((a, b) => a + b, 0) / xs.length;

/**
 * What is wrong with the shopper's position right now, or `hold_still` when nothing is. (Whether they have then
 * actually been still is `PoseGuide`'s job.) Checked in order: nobody there, head or ankles missing, too far away,
 * off to one side.
 */
export function assess(landmarks: Landmark[] | null | undefined, region: Region, t: Thresholds = DEFAULTS): GuidanceCode {
  if (!landmarks || landmarks.length < 29) return "no_person";
  const torso = [LM.LEFT_SHOULDER, LM.RIGHT_SHOULDER, LM.LEFT_HIP, LM.RIGHT_HIP].map((i) => landmarks[i]);
  if (torso.filter((p) => seen(p, t)).length < 2) return "no_person"; // a face or a hand alone is not a person to fit

  const rw = region.right - region.left;
  const rh = region.bottom - region.top;
  const inside = (p: Landmark) => p.y >= region.top + rh * t.edgeMargin && p.y <= region.bottom - rh * t.edgeMargin;

  const head = landmarks[LM.NOSE];
  const ankles = [landmarks[LM.LEFT_ANKLE], landmarks[LM.RIGHT_ANKLE]];
  const headOk = seen(head, t) && inside(head);
  const anklesOk = ankles.every((a) => seen(a, t) && inside(a));
  if (!headOk || !anklesOk) return "step_back";

  const height = (mean(ankles.map((a) => a.y)) - head.y) / rh;
  if (height < t.minBodyHeight) return "step_closer";

  // The body's middle and its width from head to toe. Arms are left out: a pose with arms out must not read as "off-centre".
  const spine = [LM.LEFT_SHOULDER, LM.RIGHT_SHOULDER, LM.LEFT_HIP, LM.RIGHT_HIP, LM.LEFT_KNEE, LM.RIGHT_KNEE, LM.LEFT_ANKLE, LM.RIGHT_ANKLE]
    .map((i) => landmarks[i])
    .filter((p) => seen(p, t));
  const xs = spine.map((p) => p.x);
  const middle = (mean(torso.filter((p) => seen(p, t)).map((p) => p.x)) - region.left) / rw; // 0..1 across the photo
  if (Math.abs(middle - 0.5) > t.centerTolerance) return "center";
  if (Math.min(...xs) < region.left - rw * t.sideMargin || Math.max(...xs) > region.right + rw * t.sideMargin) return "center";
  return "hold_still";
}

export type Guidance = {
  code: GuidanceCode;
  message: string;
  /** How long the shopper has been steady and in position, in ms. */
  steadyMs: number;
  /** steadyMs as a share of the time needed, 0..1: drives the "hold still" ring. */
  progress: number;
};

export type GuideOptions = {
  /** How long the shopper must stay in position and still before `ready`. */
  steadyMs: number;
  /** The most any tracked point may wander (a fraction of the frame) while steady. */
  motionTolerance: number;
  /** Steadiness needs at least this many frames, so one lucky frame is not enough. */
  minSamples: number;
  thresholds: Thresholds;
};

export const GUIDE_DEFAULTS: GuideOptions = { steadyMs: 1000, motionTolerance: 0.02, minSamples: 5, thresholds: DEFAULTS };

const TRACKED = [LM.NOSE, LM.LEFT_SHOULDER, LM.RIGHT_SHOULDER, LM.LEFT_HIP, LM.RIGHT_HIP, LM.LEFT_ANKLE, LM.RIGHT_ANKLE];

type Sample = { t: number; pts: [number, number][] };

/** Feed it each frame's landmarks; it says what to tell the shopper and when they have been steady long enough. */
export class PoseGuide {
  private samples: Sample[] = [];
  private readonly opts: GuideOptions;

  constructor(opts: Partial<GuideOptions> = {}) {
    this.opts = { ...GUIDE_DEFAULTS, ...opts };
  }

  reset() {
    this.samples = [];
  }

  update(landmarks: Landmark[] | null | undefined, region: Region, nowMs: number): Guidance {
    const code = assess(landmarks, region, this.opts.thresholds);
    if (code !== "hold_still" || !landmarks) {
      this.samples = []; // out of position: the clock starts again from zero
      return { code, message: MESSAGES[code], steadyMs: 0, progress: 0 };
    }

    this.samples.push({ t: nowMs, pts: TRACKED.map((i) => [landmarks[i].x, landmarks[i].y]) });
    // Moved too much since the run began: keep only this frame and start counting again.
    while (this.samples.length > 1 && this.motion() > this.opts.motionTolerance) this.samples.shift();

    const steadyMs = nowMs - this.samples[0].t;
    const ready = steadyMs >= this.opts.steadyMs && this.samples.length >= this.opts.minSamples;
    const out: GuidanceCode = ready ? "ready" : "hold_still";
    return { code: out, message: MESSAGES[out], steadyMs, progress: Math.min(1, steadyMs / this.opts.steadyMs) };
  }

  /** The largest range any one tracked point has covered across the current run of frames. */
  private motion(): number {
    let worst = 0;
    for (let p = 0; p < TRACKED.length; p++) {
      const xs = this.samples.map((s) => s.pts[p][0]);
      const ys = this.samples.map((s) => s.pts[p][1]);
      worst = Math.max(worst, Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys));
    }
    return worst;
  }
}

/**
 * A perfectly placed standing person inside `region`, used when pose detection is unavailable and the shopper starts
 * the countdown themselves: it makes the guide report "ready" so the same countdown and sharpest-frame logic still runs.
 */
export function idealLandmarks(region: Region = { left: 0, right: 1, top: 0, bottom: 1 }): Landmark[] {
  const rw = region.right - region.left;
  const rh = region.bottom - region.top;
  const x = (f: number) => region.left + rw * f; // f: 0..1 across the photo
  const y = (f: number) => region.top + rh * f; // f: 0..1 down the photo
  const lm: Landmark[] = Array.from({ length: 33 }, () => ({ x: x(0.5), y: y(0.5), visibility: 1 }));
  const set = (i: number, fx: number, fy: number) => (lm[i] = { x: x(fx), y: y(fy), visibility: 1 });
  set(LM.NOSE, 0.5, 0.12);
  set(LM.LEFT_SHOULDER, 0.4, 0.28);
  set(LM.RIGHT_SHOULDER, 0.6, 0.28);
  set(LM.LEFT_HIP, 0.44, 0.5);
  set(LM.RIGHT_HIP, 0.56, 0.5);
  set(LM.LEFT_KNEE, 0.44, 0.72);
  set(LM.RIGHT_KNEE, 0.56, 0.72);
  set(LM.LEFT_ANKLE, 0.44, 0.9);
  set(LM.RIGHT_ANKLE, 0.56, 0.9);
  return lm;
}
