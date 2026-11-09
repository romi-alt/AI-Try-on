import { type Guidance, type Landmark, PoseGuide, type Region } from "./pose";
import { BestRecent } from "./sharpness";

export type CaptureOptions = {
  /** Time between frames analysed. */
  frameIntervalMs: number;
  /** The "Strike a pose" count: 3, 2, 1. */
  countdownSeconds: number;
  /** In position and still for this long starts the countdown. */
  steadyMs: number;
  /** How many of the latest frames the sharpest is chosen from. */
  recentFrames: number;
  /** If the shopper leaves position during the countdown for longer than this, it is cancelled. */
  lostGraceMs: number;
  /** Nobody in front of the camera this long and the screen gives up. */
  noPersonTimeoutMs: number;
};

export const CAPTURE_DEFAULTS: CaptureOptions = {
  frameIntervalMs: 100,
  countdownSeconds: 3,
  steadyMs: 1000,
  recentFrames: 5,
  lostGraceMs: 1200,
  noPersonTimeoutMs: 60_000,
};

export type CaptureDeps<Frame> = {
  /** Pose landmarks for the current camera frame (null: nobody). */
  detect: () => Promise<Landmark[] | null>;
  /** The current frame cut to the photo's shape, with its sharpness score. */
  grab: () => Promise<{ frame: Frame; score: number }>;
  /** Called for a frame that falls out of the recent few (release its memory). */
  release: (frame: Frame) => void;
  /** Turns the chosen frame into the photo. */
  encode: (frame: Frame) => Promise<Blob>;
  region: () => Region;
  now: () => number;
};

export type CaptureEvents = {
  onGuidance: (g: Guidance) => void;
  onCountdown: (n: number) => void;
  onCountdownCancelled: () => void;
  onCaptured: (photo: Blob) => void;
  onGiveUp: () => void;
  onError: (error: Error) => void;
};

/**
 * Drives the capture screen: each tick looks for the shopper's pose and keeps the latest few frames; once they have
 * been in position and still for a second it counts down 3-2-1, and at zero takes the sharpest of the last frames
 * as the photo. It owns no camera or screen, so the timing can be tested.
 */
export class CaptureController<Frame> {
  private readonly opts: CaptureOptions;
  private readonly guide: PoseGuide;
  private readonly recent: BestRecent<Frame>;
  private timer: ReturnType<typeof setTimeout> | undefined;
  private stopped = true;
  private counting = false;
  private countdownStart = 0;
  private lastCount = 0;
  private lostSince: number | null = null;
  private noPersonSince: number | null = null;

  constructor(
    private readonly deps: CaptureDeps<Frame>,
    private readonly events: CaptureEvents,
    opts: Partial<CaptureOptions> = {},
  ) {
    this.opts = { ...CAPTURE_DEFAULTS, ...opts };
    this.guide = new PoseGuide({ steadyMs: this.opts.steadyMs });
    this.recent = new BestRecent<Frame>(this.opts.recentFrames);
  }

  start() {
    this.stopped = false;
    this.noPersonSince = this.deps.now();
    void this.tick();
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.timer);
    for (const f of this.recent.clear()) this.deps.release(f);
  }

  private schedule(startedAt: number) {
    if (this.stopped) return;
    const wait = Math.max(0, this.opts.frameIntervalMs - (this.deps.now() - startedAt));
    this.timer = setTimeout(() => void this.tick(), wait);
  }

  private async tick() {
    if (this.stopped) return;
    const startedAt = this.deps.now();
    try {
      const landmarks = await this.deps.detect();
      if (this.stopped) return;
      const now = this.deps.now();
      const g = this.guide.update(landmarks, this.deps.region(), now);
      this.events.onGuidance(g);

      const grabbed = await this.deps.grab();
      if (this.stopped) {
        this.deps.release(grabbed.frame);
        return;
      }
      const dropped = this.recent.push(grabbed.frame, grabbed.score);
      if (dropped !== undefined) this.deps.release(dropped);

      if (g.code === "no_person") {
        this.noPersonSince ??= now;
        if (now - this.noPersonSince >= this.opts.noPersonTimeoutMs) {
          this.stop();
          return this.events.onGiveUp();
        }
      } else {
        this.noPersonSince = null;
      }

      if (this.counting) {
        if (await this.advanceCountdown(g, now)) return; // the photo was taken (or the screen was left)
      } else if (g.code === "ready") {
        this.counting = true;
        this.countdownStart = now;
        this.lastCount = 0;
        this.lostSince = null;
        this.events.onCountdown(this.opts.countdownSeconds);
        this.lastCount = this.opts.countdownSeconds;
      }
    } catch (e) {
      if (!this.stopped) this.events.onError(e instanceof Error ? e : new Error(String(e)));
      return;
    }
    this.schedule(startedAt);
  }

  /** Returns true when the loop should stop (the photo has been taken). */
  private async advanceCountdown(g: Guidance, now: number): Promise<boolean> {
    // Leaving position (or the frame) for too long cancels it, and the shopper is guided back in.
    const inPosition = g.code === "ready" || g.code === "hold_still";
    if (inPosition) this.lostSince = null;
    else {
      this.lostSince ??= now;
      if (now - this.lostSince > this.opts.lostGraceMs) {
        this.counting = false;
        this.guide.reset();
        this.events.onCountdownCancelled();
        return false;
      }
    }

    const elapsed = now - this.countdownStart;
    const total = this.opts.countdownSeconds * 1000;
    if (elapsed >= total) {
      const best = this.recent.best();
      if (best === undefined) throw new Error("No frame to take the photo from.");
      const photo = await this.deps.encode(best);
      if (this.stopped) return true;
      this.stop();
      this.events.onCaptured(photo);
      return true;
    }
    const remaining = Math.ceil((total - elapsed) / 1000);
    if (remaining !== this.lastCount) {
      this.lastCount = remaining;
      this.events.onCountdown(remaining);
    }
    return false;
  }
}
