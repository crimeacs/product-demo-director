import {
  AbsoluteFill, Sequence, Audio, OffthreadVideo, staticFile,
  useCurrentFrame, useVideoConfig, interpolate, spring, Easing,
} from 'remotion';
import { loadFont as loadInter } from '@remotion/google-fonts/Inter';
import { loadFont as loadIBMPlexSans } from '@remotion/google-fonts/IBMPlexSans';
import React from 'react';

// Load only the Latin weights the engine paints. This keeps renders deterministic without
// issuing hundreds of font requests for unused scripts, italics, and weight variants.
loadInter('normal', { weights: ['500', '600', '700', '800', '900'], subsets: ['latin'] });
loadIBMPlexSans('normal', { weights: ['500', '600', '700'], subsets: ['latin'] });

// Screen-Studio-style zoom region: percent focus coords are resolution-independent
// (sources may be UHD 3840x2160 while the comp stays 1920x1080).
export type ZoomSpec = {
  atSec: number; durSec: number;
  scale?: number;               // default 1.6
  focusX?: number; focusY?: number;  // percent of frame (0-100)
};

export type Segment = {
  n?: number;
  kind: 'clip' | 'split' | 'title' | 'stat' | 'cta' | 'score' | 'strip' | 'bars';
  durSec: number;
  durFrames?: number;           // build-plan v2: canonical integer duration
  transition?: 'cut' | 'xfade'; // optional incoming transition override
  storyBeat?: string; storyBeats?: string[]; continuityId?: string; stateId?: string; transitionReason?: string;
  sourceType?: 'product' | 'human' | 'slide' | 'external' | 'generated'; liveState?: boolean;
  actor?: 'agent' | 'human' | 'system'; actionRisk?: 'low-friction' | 'consequential';
  claimIds?: string[]; preserveFraming?: boolean; editorialIntent?: string;
  chapter?: 'BEFORE' | 'AFTER' | '';
  showChapter?: boolean;        // chapter pills render ONLY when explicitly requested
  src?: string; inSec?: number; scale?: number; flash?: boolean; sound?: boolean;
  startScale?: number; endScale?: number; focusX?: number; focusY?: number; panX?: number; panY?: number;
  objectFit?: 'cover' | 'contain'; vignette?: boolean;
  zooms?: ZoomSpec[];           // zoom regions with spring-chase (build.py derives one from click* too)
  clickX?: number; clickY?: number; clickAtSec?: number;   // legacy; build.py converts these to zooms
  srcL?: string; inL?: number; srcR?: string; inR?: number; labelL?: string; labelR?: string;
  title?: string; eyebrow?: string; subtitle?: string; score?: number; scoreMax?: number;
  takes?: number[]; passLine?: number; takeLabels?: string[];   // bars: real take scores + pass bar
  caption?: string; captionStyle?: 'quote' | 'label';
  captionTop?: number; captionBottom?: number;
  voSec?: number;               // spoken length of the VO file; caption chunks spread over it
  brand?: string; brandAccent?: string;   // CTA wordmark: brand + accent-colored tail (e.g. "Demo" + "Director")
  vo?: string; accent?: string; accentAtSec?: number;            // accent = an sfx key to fire on this beat (e.g. "success_chime")
};
export type Sfx = { [k: string]: string | undefined };
// per-cue mix levels: payoff stingers punch through; texture stays low under the VO
const ACCENT_VOL: Record<string, number> = {
  success_chime: 0.72, confirm_cash: 0.78, data_tick: 0.36, click: 0.44,
  pivot_boom: 0.8, riser: 0.56, whoosh: 0.18, impact: 0.55,
};
// Brand theme — every color/font the engine paints with. A project's brand.json flows in here
// via build.py -> props.theme. When absent, DEFAULT_THEME reproduces the original palette exactly.
export type Theme = {
  bg: string; ink: string; sub: string;
  accent: string; accentDeep: string; onAccent: string;
  warn: string; line: string; font: string;
  grad: string;       // elevated corner of the card/score/bars radial gradient
  gradFilm: string;   // filmstrip gradient corner
  scrim: string;      // caption panel background
  scrimDim: string;   // dimmed split-label background
  logo?: string | null;  // optional staticFile path to a brand logo for the CTA
};
// EXACT original values -> a project with no brand.json renders byte-identically.
export const DEFAULT_THEME: Theme = {
  bg: '#0c1310', ink: '#f4f6f3', sub: 'rgba(244,246,243,0.66)',
  accent: '#46b07c', accentDeep: '#2f6f4f', onAccent: '#06120c',
  warn: '#e0a24a', line: 'rgba(255,255,255,0.10)',
  font: 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
  grad: '#18261e', gradFilm: '#141f19',
  scrim: 'rgba(6,10,8,0.90)', scrimDim: 'rgba(8,10,9,.72)', logo: null,
};
// merge caller theme over defaults; accept green/greenDeep aliases for back-compat
function resolveTheme(t?: (Partial<Theme> & { green?: string; greenDeep?: string }) | null): Theme {
  if (!t) return DEFAULT_THEME;
  return {
    ...DEFAULT_THEME, ...t,
    accent: t.accent ?? t.green ?? DEFAULT_THEME.accent,
    accentDeep: t.accentDeep ?? t.greenDeep ?? DEFAULT_THEME.accentDeep,
  };
}
// hex -> rgba(); reproduces the original accent glows exactly (#46b07c == 70,176,124)
function hexA(hex: string, a: number): string {
  const h = hex.replace('#', '');
  const n = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const r = parseInt(n.slice(0, 2), 16), g = parseInt(n.slice(2, 4), 16), b = parseInt(n.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}
export type TimelineProps = {
  fps: number; totalSec: number; totalFrames?: number; buildId?: string; profile?: string | null;
  music?: string | null; musicVolume?: number; musicFadeOutSec?: number; sfx?: Sfx;
  narration?: { src: string; startAtSec?: number; durationSec?: number; volume?: number } | null;
  segments: Segment[]; theme?: Partial<Theme>;
};

// module-level, mutable: set as the FIRST statement of <Timeline> each render, before any child paints.
let THEME: Theme = DEFAULT_THEME;

/* ================================================================================================
 * Zoom system — adapted from OpenScreen (siddharthvaddem/openscreen, videoPlayback/),
 * pinned at f57e36e25448b5af6c7b1b271066fe5beb9b8a49. OpenScreen is MIT licensed;
 * retain the upstream notice in ../../THIRD_PARTY_NOTICES.md when redistributing:
 * https://github.com/siddharthvaddem/openscreen
 * zoom REGIONS with an eased time-driven target (computeRegionStrength) chased by a per-axis
 * spring (zoomSpring stepAxis) so rendered motion stays velocity-continuous. Remotion renders
 * frames independently, so the spring trajectory is precomputed deterministically for the whole
 * segment and indexed by frame. Focus clamping (getFocusBoundsForScale) guarantees the zoomed
 * viewport NEVER exposes outside the source frame — no more cut-off sidebars.
 * ============================================================================================== */

const TRANSITION_WINDOW_MS = 1015;                              // zoom-out ease window
const ZOOM_IN_TRANSITION_WINDOW_MS = TRANSITION_WINDOW_MS * 1.5; // ~1.5s lead-in window
const ZOOM_IN_OVERLAP_MS = 500;                                  // portion of the window past atSec
const CHAINED_ZOOM_PAN_GAP_MS = 1500;   // regions closer than this pan between, not out-and-in
const CONNECTED_ZOOM_PAN_DURATION_MS = 1000;

function clamp01(v: number): number { return Math.max(0, Math.min(1, v)); }

// cubic-bezier solver (Newton + bisection) — port of OpenScreen mathUtils.cubicBezier
function sampleCB(a1: number, a2: number, t: number): number {
  const m = 1 - t;
  return 3 * a1 * m * m * t + 3 * a2 * m * t * t + t * t * t;
}
function sampleCBDeriv(a1: number, a2: number, t: number): number {
  const m = 1 - t;
  return 3 * a1 * m * m + 6 * (a2 - a1) * m * t + 3 * (1 - a2) * t * t;
}
function cubicBezier(x1: number, y1: number, x2: number, y2: number, t: number): number {
  const targetX = clamp01(t);
  let solvedT = targetX;
  for (let i = 0; i < 8; i += 1) {
    const currentX = sampleCB(x1, x2, solvedT) - targetX;
    const d = sampleCBDeriv(x1, x2, solvedT);
    if (Math.abs(currentX) < 1e-6 || Math.abs(d) < 1e-6) break;
    solvedT -= currentX / d;
  }
  let lower = 0, upper = 1;
  solvedT = clamp01(solvedT);
  for (let i = 0; i < 10; i += 1) {
    const currentX = sampleCB(x1, x2, solvedT);
    if (Math.abs(currentX - targetX) < 1e-6) break;
    if (currentX < targetX) lower = solvedT; else upper = solvedT;
    solvedT = (lower + upper) / 2;
  }
  return sampleCB(y1, y2, solvedT);
}
const easeOutScreenStudio = (t: number) => cubicBezier(0.16, 1, 0.3, 1, t);
const easeConnectedPan = (t: number) => cubicBezier(0.1, 0, 0.2, 1, t);

// per-axis damped spring (OpenScreen getZoomSpringConfig), integrated deterministically
const ZOOM_SPRING = { stiffness: 320, damping: 40, mass: 0.92, restDelta: 0.0005, restSpeed: 0.015 };
type SpringAxis = { v: number; vel: number; init: boolean };
const mkAxis = (): SpringAxis => ({ v: 0, vel: 0, init: false });
function stepSpringValue(ax: SpringAxis, target: number, deltaMs: number): number {
  if (!ax.init || !Number.isFinite(ax.v)) { ax.v = target; ax.vel = 0; ax.init = true; return ax.v; }
  if (Math.abs(target - ax.v) <= ZOOM_SPRING.restDelta && Math.abs(ax.vel) <= ZOOM_SPRING.restSpeed) {
    ax.v = target; ax.vel = 0; return ax.v;
  }
  // semi-implicit Euler with ~4ms substeps: stable + deterministic at any comp fps
  const steps = Math.max(1, Math.ceil(deltaMs / 4));
  const dt = (deltaMs / steps) / 1000;
  for (let i = 0; i < steps; i += 1) {
    const a = (-ZOOM_SPRING.stiffness * (ax.v - target) - ZOOM_SPRING.damping * ax.vel) / ZOOM_SPRING.mass;
    ax.vel += a * dt;
    ax.v += ax.vel * dt;
  }
  return ax.v;
}
// moving-target overshoot clamp (OpenScreen zoomSpring.stepAxis): if the step crosses the
// target, snap to it and zero the velocity — quick without jelly-wobble
function stepAxis(ax: SpringAxis, target: number, deltaMs: number): number {
  const before = ax.init ? ax.v : target;
  const after = stepSpringValue(ax, target, deltaMs);
  const crossed = (before <= target && after > target) || (before >= target && after < target);
  if (crossed) { ax.v = target; ax.vel = 0; return target; }
  return after;
}

type Region = { startMs: number; endMs: number; scale: number; cx: number; cy: number };

// OpenScreen zoomRegionUtils.computeRegionStrength: lead-in starts BEFORE atSec, full strength
// during the region, easeOutScreenStudio out over ~1s after endMs
function regionStrength(r: Region, tMs: number): number {
  const zoomInEnd = r.startMs + ZOOM_IN_OVERLAP_MS;
  const leadInStart = zoomInEnd - ZOOM_IN_TRANSITION_WINDOW_MS;
  const leadOutEnd = r.endMs + TRANSITION_WINDOW_MS;
  if (tMs < leadInStart || tMs > leadOutEnd) return 0;
  if (tMs < zoomInEnd) return easeOutScreenStudio((tMs - leadInStart) / ZOOM_IN_TRANSITION_WINDOW_MS);
  if (tMs <= r.endMs) return 1;
  return 1 - easeOutScreenStudio(clamp01((tMs - r.endMs) / TRANSITION_WINDOW_MS));
}

// OpenScreen focusUtils.getFocusBoundsForScale: at scale S the viewport half-width is 1/(2S) of
// the source, so focus is limited to [1/(2S), 1-1/(2S)] — translation can never expose an edge.
function clampFocus(c: number, scale: number): number {
  const margin = Math.min(0.5, 1 / (2 * Math.max(scale, 1.0001)));
  return Math.max(margin, Math.min(1 - margin, clamp01(c)));
}

type ZoomTarget = { scale: number; x: number; y: number };
const IDENTITY_TARGET: ZoomTarget = { scale: 1, x: 0, y: 0 };

// eased time-driven target — port of computeZoomTransform + findDominantRegion (connected pans)
function zoomTargetAt(regions: Region[], tMs: number, W: number, H: number): ZoomTarget {
  if (regions.length === 0) return IDENTITY_TARGET;
  // connected pairs: gap <= 1.5s -> pan between regions instead of zooming out and back in
  const pairs: { a: Region; b: Region; t0: number; t1: number }[] = [];
  for (let i = 0; i < regions.length - 1; i += 1) {
    const a = regions[i], b = regions[i + 1];
    if (b.startMs - a.endMs <= CHAINED_ZOOM_PAN_GAP_MS) {
      pairs.push({ a, b, t0: a.endMs, t1: a.endMs + CONNECTED_ZOOM_PAN_DURATION_MS });
    }
  }
  const transformFor = (S: number, cx: number, cy: number, strength: number): ZoomTarget => ({
    scale: 1 + (S - 1) * strength,
    x: (W / 2 - cx * W * S) * strength,
    y: (H / 2 - cy * H * S) * strength,
  });
  // 1) connected pan transition: lerp focus + scale between the two regions
  for (const p of pairs) {
    if (tMs >= p.t0 && tMs <= p.t1) {
      const prog = easeConnectedPan(clamp01((tMs - p.t0) / Math.max(1, p.t1 - p.t0)));
      const S = p.a.scale + (p.b.scale - p.a.scale) * prog;
      const ax = clampFocus(p.a.cx, p.a.scale), ay = clampFocus(p.a.cy, p.a.scale);
      const bx = clampFocus(p.b.cx, p.b.scale), by = clampFocus(p.b.cy, p.b.scale);
      return transformFor(S, ax + (bx - ax) * prog, ay + (by - ay) * prog, 1);
    }
  }
  // 2) connected hold: pan finished, next region not started yet — hold its framing
  for (const p of pairs) {
    if (tMs > p.t1 && tMs < p.b.startMs) {
      return transformFor(p.b.scale, clampFocus(p.b.cx, p.b.scale), clampFocus(p.b.cy, p.b.scale), 1);
    }
  }
  // 3) dominant region by strength (pair-consumed edges are suppressed)
  let best: Region | null = null; let bestStrength = 0;
  for (const r of regions) {
    if (pairs.some((p) => p.a === r) && tMs > r.endMs) continue;
    const inPair = pairs.find((p) => p.b === r);
    if (inPair && tMs < inPair.t1) continue;
    const s = regionStrength(r, tMs);
    if (s > bestStrength || (s > 0 && s === bestStrength && best !== null && r.startMs > best.startMs)) {
      best = r; bestStrength = s;
    }
  }
  if (!best || bestStrength <= 0) return IDENTITY_TARGET;
  return transformFor(best.scale, clampFocus(best.cx, best.scale), clampFocus(best.cy, best.scale), bestStrength);
}

type ZoomFrame = { s: number; x: number; y: number };
// precompute the whole spring-chase trajectory for a segment; index by current frame
function computeZoomTrajectory(zooms: ZoomSpec[] | undefined, durF: number, fps: number, W: number, H: number): ZoomFrame[] | null {
  const regions: Region[] = (zooms ?? [])
    .filter((z) => z && Number.isFinite(z.atSec) && Number.isFinite(z.durSec) && z.durSec > 0)
    .map((z) => ({
      startMs: z.atSec * 1000, endMs: (z.atSec + z.durSec) * 1000,
      scale: Math.max(1.05, z.scale ?? 1.6),
      cx: (z.focusX ?? 50) / 100, cy: (z.focusY ?? 50) / 100,
    }))
    .sort((a, b) => a.startMs - b.startMs);
  if (regions.length === 0) return null;
  const sc = mkAxis(), x = mkAxis(), y = mkAxis();
  const dtMs = 1000 / fps;
  const frames: ZoomFrame[] = new Array(durF + 1);
  for (let i = 0; i <= durF; i += 1) {
    const t = zoomTargetAt(regions, (i / fps) * 1000, W, H);
    frames[i] = { s: stepAxis(sc, t.scale, dtMs), x: stepAxis(x, t.x, dtMs), y: stepAxis(y, t.y, dtMs) };
  }
  return frames;
}

// ---- clip: base scale 1.0 (NO default push-in). Zoom happens only inside authored/derived
// zoom regions. Explicit startScale/endScale ken-burns is still honored, clamped >= 1.0. ----
const ClipView: React.FC<{ seg: Segment; durF: number }> = ({ seg, durF }) => {
  const { fps, width: W, height: H } = useVideoConfig();
  const f = useCurrentFrame();
  const traj = React.useMemo(
    () => computeZoomTrajectory(seg.zooms, durF, fps, W, H),
    [seg, durF, fps, W, H],
  );
  const z = traj ? traj[Math.min(Math.max(f, 0), durF)] : null;
  // legacy explicit ken-burns: honored only when authored, never below 1.0
  let k = 1, bx = 0, by = 0;
  if (seg.startScale != null || seg.endScale != null) {
    const s0 = Math.max(1, seg.startScale ?? 1);
    const s1 = Math.max(1, seg.endScale ?? s0);
    k = interpolate(f, [0, durF], [s0, s1], { extrapolateRight: 'clamp', easing: Easing.inOut(Easing.quad) });
    bx = (W * (1 - k)) / 2;
    by = (H * (1 - k)) / 2;
  }
  if (seg.panX != null || seg.panY != null) {
    const tx = interpolate(f, [0, durF], [seg.panX ?? 0, (seg.panX ?? 0) * 0.45], { extrapolateRight: 'clamp' });
    const py = seg.panY ?? 0;
    const ty = interpolate(f, [0, durF], [py, -py], { extrapolateRight: 'clamp' });
    bx += (tx / 100) * W;
    by += (ty / 100) * H;
  }
  const zs = z?.s ?? 1, zx = z?.x ?? 0, zy = z?.y ?? 0;
  // compose base ken-burns then region zoom (top-left-origin affine): p -> zs*(k*p + b) + zt
  let S = Math.max(1, k * zs);
  let X = zs * bx + zx;
  let Y = zs * by + zy;
  // hard guarantee: the viewport never exposes outside the source frame (the "cut sidebar" fix)
  X = Math.min(0, Math.max(W * (1 - S), X));
  Y = Math.min(0, Math.max(H * (1 - S), Y));
  return (
    <AbsoluteFill style={{ background: '#000', overflow: 'hidden' }}>
      {/* sound: a UGC talking-head plays its own audio (the creator's voice); screen clips stay muted */}
      <OffthreadVideo src={staticFile(seg.src!)} startFrom={Math.round((seg.inSec ?? 0) * fps)} muted={!seg.sound}
        style={{ position: 'absolute', left: 0, top: 0, width: W, height: H, objectFit: seg.objectFit ?? 'cover',
          transform: `translate(${X}px, ${Y}px) scale(${S})`, transformOrigin: '0 0' }} />
      {seg.vignette === true && <AbsoluteFill style={{ boxShadow: 'inset 0 0 220px rgba(0,0,0,0.34)', pointerEvents: 'none' }} />}
    </AbsoluteFill>
  );
};

const SplitView: React.FC<{ seg: Segment; durF: number }> = ({ seg, durF }) => {
  const { fps } = useVideoConfig();
  const f = useCurrentFrame();
  // the "directed" side wipes in from the divider — a literal before->after *change* in the first beat
  const reveal = interpolate(f, [Math.round(0.07 * fps), Math.round(0.53 * fps)], [0, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic) });
  const Pane = (src?: string, inS = 0, label?: string, dim = false, wipe = false) => (
    <div style={{ position: 'relative', flex: 1, overflow: 'hidden', background: '#000',
      clipPath: wipe ? `inset(0 ${(1 - reveal) * 100}% 0 0)` : undefined }}>
      {src && <OffthreadVideo src={staticFile(src)} startFrom={Math.round(inS * fps)} muted
        style={{ width: '100%', height: '100%', objectFit: 'contain',
          filter: dim ? 'grayscale(.45) brightness(.82) contrast(1.02)' : 'saturate(1.05)' }} />}
      {label && <div style={{ position: 'absolute', top: 30, left: 30, padding: '7px 15px', borderRadius: 8,
        background: dim ? THEME.scrimDim : THEME.accent, color: dim ? THEME.ink : THEME.onAccent,
        fontFamily: THEME.font, fontWeight: 800, fontSize: 23, letterSpacing: 1, opacity: wipe ? reveal : 1 }}>{label}</div>}
    </div>
  );
  return (
    <AbsoluteFill style={{ display: 'flex', flexDirection: 'row', gap: 4, background: THEME.bg }}>
      {Pane(seg.srcL, seg.inL, seg.labelL, true)}
      <div style={{ width: 4, background: THEME.accent }} />
      {Pane(seg.srcR, seg.inR, seg.labelR, false, true)}
    </AbsoluteFill>
  );
};

const ChapterPill: React.FC<{ label?: string }> = ({ label }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  if (!label) return null;
  const after = label === 'AFTER';
  const s = spring({ frame: f, fps, config: { damping: 16, mass: 0.6 } });
  return (
    <div style={{
      position: 'absolute', top: 52, left: 60, zIndex: 5, transform: `translateX(${interpolate(s, [0, 1], [-30, 0])}px)`,
      opacity: s, padding: '9px 20px', borderRadius: 999,
      background: after ? THEME.accent : 'rgba(255,255,255,0.10)', color: after ? THEME.onAccent : THEME.ink,
      fontWeight: 800, fontSize: 22, letterSpacing: 3, fontFamily: THEME.font,
      border: `1px solid ${after ? THEME.accent : THEME.line}`, boxShadow: after ? `0 8px 30px ${hexA(THEME.accent, 0.35)}` : 'none',
    }}>{label}</div>
  );
};

// ---- single-line captions: the text auto-chunks at clause boundaries into <=~46-char pieces,
// each shown for its proportional share of the VO window. Never wraps to two rows. ----
const CAPTION_MAX_CHARS = 46;
export function chunkCaption(text: string, maxLen = CAPTION_MAX_CHARS): string[] {
  const clean = (text || '').replace(/\s+/g, ' ').trim();
  if (!clean) return [];
  // clause units: break after sentence enders / commas / clause punctuation
  const units = clean.split(/(?<=[.!?;:,])\s+|\s+—\s+/g).flatMap((u) => {
    const unit = u.trim();
    if (!unit) return [];
    if (unit.length <= maxLen) return [unit];
    // still too long: split at word boundaries
    const words = unit.split(' ');
    const out: string[] = [];
    let cur = '';
    for (const w of words) {
      if (cur && (cur.length + 1 + w.length) > maxLen) { out.push(cur); cur = w; }
      else cur = cur ? `${cur} ${w}` : w;
    }
    if (cur) out.push(cur);
    return out;
  });
  // merge tiny neighbors back together while staying inside the budget
  const merged: string[] = [];
  for (const u of units) {
    const prev = merged[merged.length - 1];
    if (prev && (prev.length + 1 + u.length) <= maxLen) merged[merged.length - 1] = `${prev} ${u}`;
    else merged.push(u);
  }
  return merged;
}

const Caption: React.FC<{ seg: Segment; durF: number }> = ({ seg, durF }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const text = seg.caption ?? '';
  const chunks = React.useMemo(() => chunkCaption(text), [text]);
  if (chunks.length === 0) return null;
  const quote = seg.captionStyle === 'quote';
  // chunks spread across the VO window (falls back to the whole shot when no VO length known)
  const winF = Math.max(1, Math.min(durF, seg.voSec ? Math.round((seg.voSec + 0.35) * fps) : durF));
  const totalLen = chunks.reduce((a, c) => a + c.length, 0);
  let accLen = 0;
  const bounds = chunks.map((c) => {
    const a = Math.round((accLen / totalLen) * winF);
    accLen += c.length;
    const b = Math.round((accLen / totalLen) * winF);
    return [a, Math.max(a + 1, b)] as const;
  });
  if (f >= winF) return null;
  let idx = bounds.findIndex(([a, b]) => f >= a && f < b);
  if (idx < 0) idx = f < bounds[0][0] ? 0 : chunks.length - 1;
  const fadeIn = interpolate(f, [0, Math.round(0.12 * fps)], [0, 1], { extrapolateRight: 'clamp' });
  const fadeOut = interpolate(f, [winF - Math.round(0.2 * fps), winF], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  return (
    <div style={{ position: 'absolute', left: 60, right: 60, top: seg.captionTop,
      bottom: seg.captionTop == null ? (seg.captionBottom ?? 108) : undefined, zIndex: 6,
      display: 'flex', justifyContent: 'center', opacity: Math.min(fadeIn, fadeOut) }}>
      <div style={{ background: 'rgba(12,14,16,0.55)', backdropFilter: 'blur(6px)', borderRadius: 10,
        padding: '10px 22px', color: 'rgba(255,255,255,0.96)', fontFamily: THEME.font,
        fontSize: quote ? 25 : 23, lineHeight: 1.3, fontWeight: 500, letterSpacing: 0.2,
        fontStyle: quote ? 'italic' : 'normal', whiteSpace: 'nowrap',
        textShadow: '0 1px 2px rgba(0,0,0,0.45)' }}>
        {chunks[idx]}
      </div>
    </div>
  );
};

const Card: React.FC<{ seg: Segment; durF: number; cta?: boolean }> = ({ seg, durF, cta }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const drift = interpolate(f, [0, durF], [0, 1]);
  const s = spring({ frame: f, fps, config: { damping: 20, mass: 0.8 } });
  const out = interpolate(f, [durF - Math.round(0.27 * fps), durF], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const words = (seg.title || '').split(' ');
  return (
    <AbsoluteFill style={{
      background: `radial-gradient(130% 130% at ${30 + drift * 12}% ${0 + drift * 10}%, ${THEME.grad} 0%, ${THEME.bg} 62%)`,
      alignItems: 'center', justifyContent: 'center', fontFamily: THEME.font, padding: 130, opacity: out,
    }}>
      {cta && seg.eyebrow && <div style={{ marginBottom: 24, padding: '9px 17px', borderRadius: 999,
        border: `1px solid ${hexA(THEME.accent, 0.46)}`, background: hexA(THEME.accent, 0.10), color: THEME.accent,
        fontSize: 21, fontWeight: 800, letterSpacing: 3, lineHeight: 1, textTransform: 'uppercase',
        opacity: Math.min(s, out), transform: `translateY(${interpolate(s, [0, 1], [12, 0])}px)` }}>
        {seg.eyebrow}</div>}
      {/* real brand logo (brand.json "logo") replaces the text wordmark on the CTA card */}
      {cta && THEME.logo && <img src={staticFile(THEME.logo)} style={{ maxHeight: 120, maxWidth: 760,
        objectFit: 'contain', marginBottom: 30, opacity: s,
        transform: `scale(${interpolate(s, [0, 1], [0.86, 1])})` }} />}
      {cta && !THEME.logo && (seg.brand || seg.title) && <div style={{ fontSize: 70, fontWeight: 900, letterSpacing: 0.5, color: THEME.ink, marginBottom: 26,
        transform: `scale(${interpolate(s, [0, 1], [0.86, 1])})`, opacity: s }}>
        {seg.brand ?? seg.title}{seg.brandAccent && <span style={{ color: THEME.accent }}>{seg.brandAccent}</span>}</div>}
      {!cta && seg.eyebrow && <div style={{ marginBottom: 28, padding: '10px 18px', borderRadius: 999,
        border: `1px solid ${hexA(THEME.accent, 0.46)}`, background: hexA(THEME.accent, 0.10), color: THEME.accent,
        fontSize: 22, fontWeight: 800, letterSpacing: 3.2, lineHeight: 1, textTransform: 'uppercase',
        opacity: Math.min(s, out), transform: `translateY(${interpolate(s, [0, 1], [12, 0])}px)` }}>
        {seg.eyebrow}</div>}
      <div style={{ color: THEME.ink, textAlign: 'center', fontSize: seg.kind === 'stat' ? 58 : 52, fontWeight: 800, lineHeight: 1.18, maxWidth: 1460 }}>
        {words.map((w, i) => {
          const ws = spring({ frame: f - i * 1.1, fps, config: { damping: 200 } });
          return <span key={i} style={{ display: 'inline-block', marginRight: '0.28em', opacity: ws,
            transform: `translateY(${interpolate(ws, [0, 1], [22, 0])}px)` }}>{w}</span>;
        })}
      </div>
      {cta && seg.subtitle && <div style={{ marginTop: 30, padding: '14px 30px', borderRadius: 999,
        border: `1.5px solid ${THEME.accent}`, background: hexA(THEME.accent, 0.12), color: THEME.accent, fontSize: 36, fontWeight: 750,
        letterSpacing: 0.3, fontFamily: THEME.font, opacity: Math.min(s, out), transform: `translateY(${interpolate(s, [0, 1], [14, 0])}px)` }}>
        {seg.subtitle} →</div>}
      {!cta && seg.subtitle && <div style={{ marginTop: 34, maxWidth: 1320, color: THEME.sub, textAlign: 'center',
        fontSize: 30, fontWeight: 600, lineHeight: 1.35, letterSpacing: 0.15, opacity: Math.min(s, out),
        transform: `translateY(${interpolate(s, [0, 1], [16, 0])}px)` }}>
        {seg.subtitle}</div>}
    </AbsoluteFill>
  );
};

// ---- the wow beat: a score that counts up while a bar fills, then a tick lands ----
const ScoreCard: React.FC<{ seg: Segment; durF: number }> = ({ seg, durF }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const target = seg.score ?? 72;
  const max = seg.scoreMax ?? 100;
  const s = spring({ frame: f, fps, config: { damping: 14, mass: 0.7 } });
  // count ticks up over the first ~60% of the beat and decelerates into the target — the motion IS the wow
  const countEnd = Math.max(Math.round(0.6 * durF), Math.round(0.8 * fps));
  const count = Math.round(interpolate(f, [Math.round(0.1 * fps), countEnd], [0, target], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic) }));
  const fill = interpolate(f, [Math.round(0.1 * fps), countEnd], [0, target / max], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.out(Easing.cubic) });
  const tick = spring({ frame: f - countEnd - Math.round(0.07 * fps), fps, config: { damping: 12, mass: 0.5 } });
  const out = interpolate(f, [durF - Math.round(0.27 * fps), durF], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const drift = interpolate(f, [0, durF], [0, 1]);
  return (
    <AbsoluteFill style={{
      background: `radial-gradient(130% 130% at ${30 + drift * 12}% ${drift * 10}%, ${THEME.grad} 0%, ${THEME.bg} 62%)`,
      alignItems: 'center', justifyContent: 'center', fontFamily: THEME.font, opacity: out,
    }}>
      {seg.eyebrow && <div style={{
        position: 'absolute', top: 104, padding: '10px 18px', borderRadius: 999,
        border: `1px solid ${hexA(THEME.accent, 0.46)}`, background: hexA(THEME.accent, 0.10),
        color: THEME.accent, fontSize: 22, fontWeight: 800, letterSpacing: 3.2,
        lineHeight: 1, textTransform: 'uppercase', opacity: Math.min(s, out),
        transform: `translateY(${interpolate(s, [0, 1], [12, 0])}px)`,
      }}>{seg.eyebrow}</div>}
      <div style={{ position: 'relative', display: 'flex', alignItems: 'baseline', gap: 14 }}>
        {/* one soft radial glow behind the whole number group (per-glyph text shadows read lumpy) */}
        <div style={{ position: 'absolute', inset: '-60px -80px', background: `radial-gradient(50% 50% at 40% 55%, ${hexA(THEME.accent, 0.22)} 0%, transparent 70%)`, pointerEvents: 'none' }} />
        <span style={{ fontSize: 224, fontWeight: 900, color: THEME.accent, lineHeight: 0.9, fontVariantNumeric: 'tabular-nums',
          letterSpacing: -4, transform: `scale(${interpolate(s, [0, 1], [0.78, 1])})` }}>{count}</span>
        <span style={{ fontSize: 92, fontWeight: 800, color: THEME.ink, opacity: 0.5 }}>/ {max}</span>
        <span style={{ marginLeft: 18, width: 70, height: 70, borderRadius: 999, background: THEME.accent, color: THEME.onAccent,
          display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 44, fontWeight: 900,
          transform: `scale(${interpolate(tick, [0, 1], [0, 1])})`, opacity: tick, alignSelf: 'center' }}>✓</span>
      </div>
      <div style={{ width: 820, height: 14, borderRadius: 999, background: 'rgba(255,255,255,0.08)', marginTop: 46, overflow: 'hidden',
        border: `1px solid ${THEME.line}` }}>
        <div style={{ width: `${fill * 100}%`, height: '100%', background: `linear-gradient(90deg, ${THEME.accentDeep}, ${THEME.accent})`, borderRadius: 999 }} />
      </div>
      {seg.title && <div style={{ marginTop: 38, color: THEME.ink, opacity: Math.min(s, 0.92), fontSize: 40, fontWeight: 700,
        letterSpacing: 0.3, transform: `translateY(${interpolate(s, [0, 1], [16, 0])}px)` }}>{seg.title}</div>}
    </AbsoluteFill>
  );
};

// ---- the iterate beat: rejected cuts climb past a PASS line until one clears it ----
const IterBars: React.FC<{ seg: Segment; durF: number }> = ({ seg, durF }) => {
  const f = useCurrentFrame();
  const { fps } = useVideoConfig();
  const out = interpolate(f, [durF - Math.round(0.23 * fps), durF], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  const drift = interpolate(f, [0, durF], [0, 1]);
  const H = 430;
  const LABEL_BAND = 56;
  const PLOT_H = H - LABEL_BAND;
  // real take scores flow in from the script (seg.takes / seg.passLine); defaults keep old cuts rendering
  const takes = seg.takes && seg.takes.length ? seg.takes : [46, 58, 67, 80];
  const denom = Math.max(seg.scoreMax ?? 100, ...takes);
  const heights = takes.map((t) => t / denom);
  const labels = seg.takeLabels && seg.takeLabels.length === takes.length
    ? seg.takeLabels : takes.map((_, i) => `take ${i + 1}`);
  const passLine = seg.passLine ?? 74;
  const pass = passLine / denom;      // the bar to clear
  const cleared = takes[takes.length - 1] >= passLine;
  const lastBarF = Math.round(0.13 * fps) + (takes.length - 1) * Math.round(0.23 * fps);
  const stamp = cleared
    ? spring({ frame: f - lastBarF - Math.round(0.55 * fps), fps, config: { damping: 11, mass: 0.6 } })
    : 0;   // a rejected final bar must never receive a false PASSED stamp
  const glow = 0.5 + 0.5 * Math.sin((f / fps) * 6);                                    // gentle pulse keeps the win alive
  return (
    <AbsoluteFill style={{
      background: `radial-gradient(130% 130% at ${30 + drift * 12}% ${drift * 10}%, ${THEME.grad} 0%, ${THEME.bg} 62%)`,
      alignItems: 'center', justifyContent: 'center', fontFamily: THEME.font, opacity: out,
    }}>
      <div style={{ position: 'relative', display: 'flex', alignItems: 'flex-end', gap: 52, height: H, padding: '0 30px' }}>
        <div style={{ position: 'absolute', left: -28, right: -150, bottom: LABEL_BAND + pass * PLOT_H, borderTop: `2px dashed ${THEME.accent}`, opacity: 0.55 }} />
        <div style={{ position: 'absolute', right: -150, bottom: LABEL_BAND + pass * PLOT_H + 10, color: THEME.accent, fontWeight: 800, fontSize: 26, letterSpacing: 1 }}>PASS</div>
        <div style={{ position: 'absolute', left: '50%', top: -26, transform: `translateX(-50%) scale(${interpolate(stamp, [0, 1], [0.4, 1])}) rotate(-4deg)`,
          opacity: stamp, padding: '10px 24px', borderRadius: 12, background: THEME.accent, color: THEME.onAccent,
          fontWeight: 900, fontSize: 30, letterSpacing: 1, boxShadow: `0 10px 40px ${hexA(THEME.accent, 0.4 + 0.3 * glow)}` }}>PASSED ✓</div>
        {heights.map((h, i) => {
          const s = spring({ frame: f - Math.round(0.13 * fps) - i * Math.round(0.23 * fps), fps, config: { damping: 15, mass: 0.7 } });
          const passed = cleared && i === heights.length - 1;
          return (
            <div key={i} style={{ width: 128, height: H, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'flex-end' }}>
              <div style={{ position: 'relative', width: 128, height: h * PLOT_H * s, borderRadius: '14px 14px 0 0',
                background: passed ? `linear-gradient(180deg, ${THEME.accent}, ${THEME.accentDeep})` : hexA(THEME.warn, 0.5),
                boxShadow: passed ? `0 0 46px ${hexA(THEME.accent, 0.55)}` : 'none' }}>
                <div style={{ position: 'absolute', top: -38, left: 0, right: 0, textAlign: 'center', fontVariantNumeric: 'tabular-nums',
                  color: passed ? THEME.accent : THEME.sub, fontWeight: 800, fontSize: 26, opacity: s }}>{takes[i]}</div>
              </div>
              <div style={{ marginTop: 16, color: passed ? THEME.accent : THEME.sub, fontWeight: 750, fontSize: 24 }}>{labels[i]}{passed ? ' ✓' : ''}</div>
            </div>
          );
        })}
      </div>
      {seg.title && <div style={{ marginTop: 46, color: THEME.ink, fontSize: 40, fontWeight: 750, letterSpacing: 0.2 }}>{seg.title}</div>}
    </AbsoluteFill>
  );
};

// ---- the meta beat: a strip of the promo's own shots pans by ("it cut this video too") ----
const STRIP_AR = 3984 / 302; // baked filmstrip aspect (8 tiles)
const Filmstrip: React.FC<{ src: string; durF: number }> = ({ src, durF }) => {
  const f = useCurrentFrame();
  const { width: W, height: H } = useVideoConfig();
  const p = interpolate(f, [0, durF], [0, 1], { extrapolateRight: 'clamp', easing: Easing.inOut(Easing.quad) });
  const stripH = H * 0.5;
  const stripW = stripH * STRIP_AR;
  const x = interpolate(p, [0, 1], [40, -(stripW - W) - 40]); // pan left edge -> right edge
  const tilt = interpolate(f, [0, durF], [1.5, -1.5]);
  return (
    <AbsoluteFill style={{ background: `radial-gradient(120% 120% at 50% 30%, ${THEME.gradFilm} 0%, ${THEME.bg} 70%)`, overflow: 'hidden' }}>
      <img src={staticFile(src)} style={{
        position: 'absolute', top: (H - stripH) / 2, left: 0, height: stripH, width: stripW,
        transform: `translateX(${x}px) rotate(${tilt * 0.18}deg)`, filter: 'saturate(1.06)',
        boxShadow: '0 36px 110px rgba(0,0,0,0.55)' }} />
      <AbsoluteFill style={{ boxShadow: 'inset 0 0 240px rgba(0,0,0,0.5)', pointerEvents: 'none' }} />
    </AbsoluteFill>
  );
};

const Seg: React.FC<{ seg: Segment; durF: number }> = ({ seg, durF }) => {
  let body: React.ReactNode;
  if (seg.kind === 'clip') body = <ClipView seg={seg} durF={durF} />;
  else if (seg.kind === 'split') body = <SplitView seg={seg} durF={durF} />;
  else if (seg.kind === 'score') body = <ScoreCard seg={seg} durF={durF} />;
  else if (seg.kind === 'strip') body = <Filmstrip src={seg.src!} durF={durF} />;
  else if (seg.kind === 'bars') body = <IterBars seg={seg} durF={durF} />;
  else body = <Card seg={seg} durF={durF} cta={seg.kind === 'cta'} />;
  return (
    <AbsoluteFill style={{ background: THEME.bg }}>
      {body}
      {/* chapter pills only on explicit request; the chapter FIELD still drives flash/riser timing */}
      {seg.showChapter === true && <ChapterPill label={seg.chapter} />}
      <Caption seg={seg} durF={durF} />
      {seg.vo && <Audio src={staticFile(seg.vo)} />}
    </AbsoluteFill>
  );
};

// white-flash match-cut at the BEFORE->AFTER pivot
const PivotFlash: React.FC<{ pivotFrame: number }> = ({ pivotFrame }) => {
  const f = useCurrentFrame();
  const o = interpolate(f, [pivotFrame - 3, pivotFrame, pivotFrame + 7], [0, 0.82, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
  if (o <= 0) return null;
  return <AbsoluteFill style={{ background: '#fff', opacity: o, zIndex: 20 }} />;
};

// incoming-shot crossfade wrapper: opacity only — no translate, no zoom on the incoming shot
const SegFade: React.FC<{ fadeInF: number; children: React.ReactNode }> = ({ fadeInF, children }) => {
  const f = useCurrentFrame();
  const o = fadeInF > 0 ? interpolate(f, [0, fadeInF], [0, 1], { extrapolateRight: 'clamp' }) : 1;
  return <AbsoluteFill style={{ opacity: o }}>{children}</AbsoluteFill>;
};

type TransKind = 'none' | 'cut' | 'xfade';

export const Timeline: React.FC<TimelineProps> = ({ fps, music, musicVolume = 0.1, musicFadeOutSec = 1.5, narration, sfx, segments, theme }) => {
  THEME = resolveTheme(theme);   // set module theme BEFORE any child paints this frame (see DEFAULT_THEME note)
  const df = segments.map((s) => Math.max(1, s.durFrames ?? Math.round(s.durSec * fps)));
  const starts: number[] = []; let acc = 0; for (const d of df) { starts.push(acc); acc += d; }
  const pivotIdx = segments.findIndex((s) => s.chapter === 'AFTER' || s.flash);
  const pivotFrame = pivotIdx > 0 ? starts[pivotIdx] : -999;

  // scene transitions: same-src clip->clip = pure hard cut; flash beats = hard cut (+ white flash);
  // everything else = 300ms opacity-only crossfade
  const XF = Math.max(1, Math.round(0.3 * fps));
  const transIn: TransKind[] = segments.map((seg, i) => {
    if (i === 0) return 'none';
    const prev = segments[i - 1];
    if (seg.transition === 'cut' || seg.transition === 'xfade') return seg.transition;
    if (seg.flash) return 'cut';
    if (seg.kind === 'clip' && prev.kind === 'clip' && seg.src && seg.src === prev.src) return 'cut';
    return 'xfade';
  });
  return (
    <AbsoluteFill style={{ background: THEME.bg }}>
      {segments.map((seg, i) => {
        // the OUTGOING shot holds a bit longer under an incoming crossfade (later JSX paints on top)
        const extend = i + 1 < segments.length && transIn[i + 1] === 'xfade' ? XF : 0;
        return (
          <Sequence key={i} from={starts[i]} durationInFrames={df[i] + extend}>
            <SegFade fadeInF={transIn[i] === 'xfade' ? XF : 0}>
              <Seg seg={seg} durF={df[i]} />
            </SegFade>
          </Sequence>
        );
      })}

      {/* sound design: soft whoosh connective tissue on each cut */}
      {sfx?.whoosh && starts.map((s, i) => i === 0 ? null : (
        <Sequence key={`w${i}`} from={Math.max(0, s - 3)} durationInFrames={fps}><Audio src={staticFile(sfx.whoosh!)} volume={ACCENT_VOL.whoosh} /></Sequence>
      ))}
      {/* per-beat accent: each key moment gets its own distinct sound, landing as the beat reads */}
      {sfx && segments.map((seg, i) => (seg.accent && sfx[seg.accent]) ? (
        <Sequence key={`ac${i}`} from={starts[i] + Math.round((seg.accentAtSec ?? 0.3) * fps)} durationInFrames={Math.round(1.6 * fps)}>
          <Audio src={staticFile(sfx[seg.accent]!)} volume={ACCENT_VOL[seg.accent] ?? 0.5} /></Sequence>
      ) : null)}
      {/* the before->after pivot: riser swelling in, deep boom on the reveal */}
      {sfx?.riser && pivotFrame > 0 && (
        <Sequence from={Math.max(0, pivotFrame - Math.round(1.4 * fps))} durationInFrames={Math.round(1.8 * fps)}>
          <Audio src={staticFile(sfx.riser)} volume={ACCENT_VOL.riser} /></Sequence>
      )}
      {(sfx?.pivot_boom || sfx?.impact) && pivotFrame > 0 && (
        <Sequence from={pivotFrame} durationInFrames={Math.round(1.8 * fps)}>
          <Audio src={staticFile((sfx.pivot_boom || sfx.impact)!)} volume={ACCENT_VOL.pivot_boom} /></Sequence>
      )}

      <PivotFlash pivotFrame={pivotFrame} />
      {/* One authoritative human narration master. Per-shot VO and this mode are mutually
          exclusive in contracts.py, so speech can never be accidentally doubled. */}
      {narration?.src && (() => {
        const from = Math.max(0, Math.round((narration.startAtSec ?? 0) * fps));
        return <Sequence from={from} durationInFrames={Math.max(1, acc - from)}>
          <Audio src={staticFile(narration.src)} volume={narration.volume ?? 1} />
        </Sequence>;
      })()}
      {/* music bed: ducked under every VO window (sidechain feel), eased edges, fade-out at the end */}
      {music && (() => {
        const voWins = segments.map((s, i) => (s.vo ? [starts[i], starts[i] + df[i]] : null)).filter(Boolean) as number[][];
        if (narration?.src) {
          const a = Math.max(0, Math.round((narration.startAtSec ?? 0) * fps));
          const declared = narration.durationSec && narration.durationSec > 0
            ? Math.round(narration.durationSec * fps) : acc - a;
          voWins.push([a, Math.min(acc, a + declared)]);
        }
        const ramp = Math.round(0.3 * fps);
        const DUCK = 0.45;
        const vol = (f: number) => {
          let duck = 1;
          for (const [a, b] of voWins) {
            const d = interpolate(f, [a - ramp, a, b, b + ramp], [1, DUCK, DUCK, 1], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
            duck = Math.min(duck, d);
          }
          const fadeIn = interpolate(f, [0, Math.round(0.5 * fps)], [0, 1], { extrapolateRight: 'clamp' });
          const fadeOutFrames = Math.max(1, Math.round(Math.max(0, musicFadeOutSec) * fps));
          const fadeEnd = Math.max(0, acc - 1);
          const fadeStart = Math.max(0, fadeEnd - fadeOutFrames + 1);
          const fadeOut = fadeOutFrames <= 1
            ? (f >= fadeEnd ? 0 : 1)
            : interpolate(f, [fadeStart, fadeEnd], [1, 0], { extrapolateLeft: 'clamp', extrapolateRight: 'clamp' });
          return musicVolume * duck * fadeIn * fadeOut;
        };
        return <Audio src={staticFile(music)} volume={vol} />;
      })()}
    </AbsoluteFill>
  );
};
