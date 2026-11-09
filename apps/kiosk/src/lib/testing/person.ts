import { LM, type Landmark } from "../pose";

/** A standing person: head at `top`, ankles at `bottom`, body middle at `cx` (all as fractions of the frame). */
export function person(opts: { cx?: number; top?: number; bottom?: number; vis?: number; spread?: number } = {}): Landmark[] {
  const { cx = 0.5, top = 0.12, bottom = 0.92, vis = 0.99, spread = 0.05 } = opts;
  const lm: Landmark[] = Array.from({ length: 33 }, () => ({ x: cx, y: (top + bottom) / 2, visibility: vis }));
  const at = (i: number, x: number, y: number) => (lm[i] = { x, y, visibility: vis });
  const h = bottom - top;
  at(LM.NOSE, cx, top);
  at(LM.LEFT_EYE, cx - 0.01, top - 0.01);
  at(LM.RIGHT_EYE, cx + 0.01, top - 0.01);
  at(LM.LEFT_SHOULDER, cx - spread, top + h * 0.18);
  at(LM.RIGHT_SHOULDER, cx + spread, top + h * 0.18);
  at(LM.LEFT_HIP, cx - spread * 0.7, top + h * 0.5);
  at(LM.RIGHT_HIP, cx + spread * 0.7, top + h * 0.5);
  at(LM.LEFT_KNEE, cx - spread * 0.7, top + h * 0.74);
  at(LM.RIGHT_KNEE, cx + spread * 0.7, top + h * 0.74);
  at(LM.LEFT_ANKLE, cx - spread * 0.7, bottom);
  at(LM.RIGHT_ANKLE, cx + spread * 0.7, bottom);
  return lm;
}
