/** Authored, frame-addressable motion. This module has no renderer or browser dependencies. */
export type MotionEase = 'smooth' | 'drive' | 'settle' | 'linear';
export type CameraKeyframe = {
  atSec: number;
  scale: number;
  /** Source coordinates in percent, before cropping. */
  focusX: number;
  focusY: number;
  /** Easing of the move arriving at this keyframe. */
  ease?: MotionEase;
};
export type CameraTransform = { s: number; x: number; y: number };
export type CameraSourcePlane = { left: number; top: number; width: number; height: number };
/** Must agree with tools/framing.py. Explicit closeups are permitted; fit/readability is audited separately. */
export const MAX_CAMERA_SCALE = 8;

const finite = (value: number, fallback: number) => Number.isFinite(value) ? value : fallback;
const clamp = (value: number, low: number, high: number) => Math.max(low, Math.min(high, value));
const unit = (value: number) => clamp(finite(value, 0), 0, 1);
const mix = (from: number, to: number, progress: number) => from + (to - from) * progress;

/**
 * Monotone easing, without spring overshoot. All authored eases except explicit
 * linear have zero velocity AND acceleration at both ends, so a move joins a
 * reading hold (or another move) without a mechanical bump.
 *
 * drive/settle are the beta(4,3)/beta(3,4) cumulative polynomials: a later push
 * versus an earlier arrival. Both remain C2 where they join a hold.
 */
export function motionEase(progress: number, ease: MotionEase = 'smooth'): number {
  const t = unit(progress);
  if (t === 0 || t === 1 || ease === 'linear') return t;
  if (ease === 'drive') return unit(t ** 4 * (15 + t * (-24 + 10 * t)));
  if (ease === 'settle') return unit(t ** 3 * (20 + t * (-45 + t * (36 - 10 * t))));
  return unit(t ** 3 * (10 + t * (-15 + 6 * t)));
}

function boundAxis(position: number, scale: number, viewport: number, offset: number, extent: number): number {
  // A contained source can be narrower than the viewport. Keep that unavoidable
  // letterbox symmetric until there are enough source pixels to fill the axis.
  if (extent * scale < viewport) return viewport / 2 - (offset + extent / 2) * scale;
  const lower = extent === viewport ? viewport * (1 - scale) - offset * scale
    : viewport - (offset + extent) * scale;
  return clamp(position, lower, -offset * scale) + 0; // Normalize negative zero for stable poses.
}

function boundTransform(transform: CameraTransform, width: number, height: number,
  plane: CameraSourcePlane): CameraTransform {
  return { s: transform.s,
    x: boundAxis(transform.x, transform.s, width, plane.left, plane.width),
    y: boundAxis(transform.y, transform.s, height, plane.top, plane.height) };
}

function interpolateAxis(from: CameraTransform, to: CameraTransform, axis: 'x' | 'y',
  progress: number, scale: number, viewport: number, offset: number, extent: number): number {
  if (Math.min(from.s, to.s) * extent >= viewport) return mix(from[axis], to[axis], progress);
  const center = viewport / 2 - (offset + extent / 2) * scale;
  if (extent * scale <= viewport) return center;
  // When zoom crosses contain's fill threshold, begin panning with zero velocity
  // and acceleration. Cubing the available-overflow ratio remains inside the
  // source bounds while avoiding the kink of a per-frame edge clamp.
  const covered = from.s > to.s ? from : to;
  const available = (extent * scale - viewport) / (extent * covered.s - viewport);
  const coveredCenter = viewport / 2 - (offset + extent / 2) * covered.s;
  return center + (covered[axis] - coveredCenter) * available ** 3;
}

function keyframeTransform(keyframe: CameraKeyframe, width: number, height: number,
  plane: CameraSourcePlane): CameraTransform {
  const s = clamp(finite(keyframe.scale, 1), 1, MAX_CAMERA_SCALE);
  const focus = (value: number) => finite(value, 50) / 100;
  return boundTransform({
    s,
    x: width * (0.5 - focus(keyframe.focusX) * s),
    y: height * (0.5 - focus(keyframe.focusY) * s),
  }, width, height, plane);
}

/**
 * Sample a shot-local camera path at any frame, including subframes.
 *
 * Keyframe timestamps are seconds; focus coordinates are percentages. The first
 * and last poses hold indefinitely. Repeated poses create deliberate reading
 * holds. Input order does not matter; the last authored pose wins at a duplicate
 * timestamp. Empty paths return the uncropped source.
 *
 * Interpolate the already-clamped endpoint transforms, not a focus that gets
 * clamped each frame. Source-covering bounds are convex in (scale, translation),
 * so the whole move stays inside the source while preserving the authored ease.
 * Per-frame focus clipping would otherwise introduce a visible velocity kink.
 * Optional bounds describe the complete object-fit source, including pixels
 * outside a cover crop. Contain letterboxing stays centered until zoom fills it.
 */
export function cameraTransform(keyframes: readonly CameraKeyframe[] | undefined,
  frame: number, fps: number, width: number, height: number,
  sourcePlane?: CameraSourcePlane): CameraTransform {
  const sorted = (keyframes ?? []).filter((keyframe) => keyframe && Number.isFinite(keyframe.atSec))
    .slice().sort((a, b) => a.atSec - b.atSec);
  if (sorted.length === 0) return { s: 1, x: 0, y: 0 };

  const points: CameraKeyframe[] = [];
  for (const keyframe of sorted) {
    if (points.length && points[points.length - 1].atSec === keyframe.atSec) points[points.length - 1] = keyframe;
    else points.push(keyframe);
  }
  const w = Math.max(0, finite(width, 0));
  const h = Math.max(0, finite(height, 0));
  const plane = sourcePlane && [sourcePlane.left, sourcePlane.top, sourcePlane.width, sourcePlane.height].every(Number.isFinite)
    && sourcePlane.width > 0 && sourcePlane.height > 0 ? sourcePlane : { left: 0, top: 0, width: w, height: h };
  const time = finite(frame, 0) / (Number.isFinite(fps) && fps > 0 ? fps : 30);
  if (time <= points[0].atSec) return keyframeTransform(points[0], w, h, plane);
  for (let index = 1; index < points.length; index++) {
    const next = points[index];
    if (time > next.atSec) continue;
    const previous = points[index - 1];
    const eased = motionEase((time - previous.atSec) / (next.atSec - previous.atSec), next.ease);
    const from = keyframeTransform(previous, w, h, plane);
    const to = keyframeTransform(next, w, h, plane);
    if (eased === 0) return from;
    if (eased === 1) return to;
    const s = mix(from.s, to.s, eased);
    return boundTransform({
      s,
      // Source-covering endpoints remain covering throughout interpolation.
      // The bounds additionally center an axis while contain still letterboxes.
      x: interpolateAxis(from, to, 'x', eased, s, w, plane.left, plane.width),
      y: interpolateAxis(from, to, 'y', eased, s, h, plane.top, plane.height),
    }, w, h, plane);
  }
  return keyframeTransform(points[points.length - 1], w, h, plane);
}

/** Entry span measured from frame zero; reserve at least the final picture frame fully visible. */
export function boundedTransitionFrames(requestedFrames: number, shotFrames: number): number {
  return Math.min(Math.max(0, Math.round(finite(requestedFrames, 0))),
    Math.max(0, Math.floor(finite(shotFrames, 1)) - 1));
}

/** A zero-frame entry is a cut. For an N-frame entry, frame N is fully revealed. */
export function transitionProgress(frame: number, durationFrames: number): number {
  if (!Number.isFinite(durationFrames) || durationFrames <= 0) return 1;
  return unit(finite(frame, 0) / durationFrames);
}

export type StudioTransitionStyle = { clipPath: string; transform: string; opacity: number };

/**
 * Opaque masked entries over the outgoing shot's held final picture. The reveal
 * leaves incoming UI perfectly stationary; push adds a restrained, six-percent
 * horizontal glide. Neither blurs text nor fades through the background.
 * The containing composition should clip overflow, as it does for camera moves.
 */
export function transitionStyle(kind: 'reveal' | 'push', progress: number,
  width: number, _height: number): StudioTransitionStyle {
  const eased = motionEase(progress, 'settle');
  const hidden = (1 - eased) * 100;
  if (kind === 'push') {
    const x = Math.max(0, finite(width, 0)) * 0.06 * (1 - eased);
    return { clipPath: `inset(0 0 0 ${hidden}%)`, transform: `translate3d(${x}px, 0, 0)`, opacity: 1 };
  }
  return { clipPath: `inset(0 ${hidden}% 0 0)`, transform: 'translate3d(0, 0, 0)', opacity: 1 };
}
