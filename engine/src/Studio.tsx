import React from 'react';
import { AbsoluteFill, Img, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';

/** A fixed artboard makes optical spacing independent of output resolution. */
const ART_W = 1920;
const ART_H = 1080;
const clamp = (value: number, lo = 0, hi = 1) => Math.max(lo, Math.min(hi, value));
const settle = (value: number) => 1 - Math.pow(1 - clamp(value), 5);

export interface StudioTheme {
  bg: string; ink: string; sub: string; accent: string; accentDeep: string;
  onAccent: string; line: string; font: string; grad: string;
  logo?: string | null;
}

export interface StudioSegment {
  kind: string;
  title?: string; eyebrow?: string; subtitle?: string;
  brand?: string; brandAccent?: string; score?: number; scoreMax?: number;
  titleLines?: string[]; emphasis?: string;
  direction?: {
    intent?: 'establish' | 'demonstrate' | 'focus' | 'payoff' | 'resolve';
    layout?: 'fullbleed' | 'stage';
    align?: 'left' | 'center';
    energy?: number;
  };
}

export interface StudioAnnotation {
  atSec: number; endSec: number;
  x: number; y: number; width: number; height: number;
  label?: string; kind?: 'box' | 'spotlight';
}

// Every entrance finishes within the first 30% of its shot. Short inserts hold
// their content immediately instead of spending their entire lifetime entering.
function entrance(frame: number, durF: number, fps: number, order = 0, count = 1, energy = 0.5): number {
  if (durF <= Math.max(3, fps * 0.35)) return 1;
  const pace = clamp(energy);
  // Higher energy tightens the arrival, then holds. The same composition has a
  // different cadence without adding oscillation or taking away reading time.
  const window = Math.max(1, Math.min(fps * (1.02 - pace * 0.48), (durF - 1) * (0.3 - pace * 0.08)));
  const stagger = Math.min(fps * (0.08 - pace * 0.025), window * 0.3 / Math.max(1, count - 1));
  const delay = order * stagger;
  return settle((frame - delay) / Math.max(1, window - (count - 1) * stagger));
}

// Optical width, rather than character count, keeps "ill" and "WOW" from being
// treated as equally wide. Fitting remains deterministic during parallel renders.
function textWidth(text: string): number {
  return [...text].reduce((width, char) => width + (
    /[\s]/u.test(char) ? 0.27 : /[ilI1|.,'!:;]/u.test(char) ? 0.29 :
      /[MW@%&]/u.test(char) ? 0.9 : /[A-Z0-9]/u.test(char) ? 0.67 :
        /[^\u0000-\u024f]/u.test(char) ? 1 : 0.55
  ), 0);
}

/** Find balanced editorial line breaks without dropping or manufacturing copy. */
export function studioTitleLines(title: string, explicit?: string[]): string[] {
  const authored = explicit?.map((line) => line.trim()).filter(Boolean);
  if (authored?.length) return authored;
  const hardLines = title.split('\n').map((line) => line.trim()).filter(Boolean);
  if (hardLines.length > 1) return hardLines;
  const clean = title.replace(/\s+/g, ' ').trim();
  if (!clean) return [];
  const words = clean.split(' ');
  const width = textWidth(clean);
  if (width < 13 || words.length < 3) return [clean];
  const count = width > 35 && words.length >= 6 ? 3 : 2;
  // Evaluate every legal break for two/three lines. Titles are small; this avoids
  // a ragged last word and allows punctuation to determine the natural cadence.
  let best: string[] = [clean];
  let bestCost = Infinity;
  const score = (lines: string[]) => {
    const widths = lines.map(textWidth);
    const target = widths.reduce((a, b) => a + b, 0) / widths.length;
    let cost = widths.reduce((sum, w) => sum + (w - target) ** 2, 0);
    lines.slice(0, -1).forEach((line) => {
      if (/[,:;.!?]$/u.test(line)) cost -= 0.9;
      if (/\b(a|an|the|and|or|of|to|in|with|for)$/iu.test(line)) cost += 3;
    });
    if (widths[widths.length - 1] < target * 0.48) cost += 12;
    return cost;
  };
  for (let first = 1; first < words.length; first++) {
    if (count === 2) {
      const lines = [words.slice(0, first).join(' '), words.slice(first).join(' ')];
      const cost = score(lines);
      if (cost < bestCost) { best = lines; bestCost = cost; }
    } else {
      for (let second = first + 1; second < words.length; second++) {
        const lines = [words.slice(0, first).join(' '), words.slice(first, second).join(' '), words.slice(second).join(' ')];
        const cost = score(lines);
        if (cost < bestCost) { best = lines; bestCost = cost; }
      }
    }
  }
  return best;
}

function titleSize(lines: string[], maxWidth: number, ceiling: number, maxHeight: number): number {
  const longest = Math.max(1, ...lines.map(textWidth));
  // The margin accommodates differences between the project's chosen font and
  // the optical-width model. Explicit long lines shrink; they never get clipped.
  return Math.min(ceiling, maxWidth / (longest * 1.1), maxHeight / Math.max(1, lines.length * 1.04));
}

function emphasisParts(text: string, emphasis: string | undefined, color: string): React.ReactNode {
  if (!emphasis?.trim()) return text;
  const index = text.toLocaleLowerCase().indexOf(emphasis.toLocaleLowerCase());
  if (index < 0) return text;
  return <>{text.slice(0, index)}<span style={{ color }}>{text.slice(index, index + emphasis.length)}</span>{text.slice(index + emphasis.length)}</>;
}

const normalize = (value: string) => value.replace(/[^\p{L}\p{N}]/gu, '').toLocaleLowerCase();
const assetUrl = (src: string) => /^(https?:|data:|blob:)/u.test(src) ? src : staticFile(src);

const Artboard: React.FC<{ children: React.ReactNode; theme: StudioTheme }> = ({ children, theme }) => {
  const { width, height } = useVideoConfig();
  const scale = Math.min(width / ART_W, height / ART_H);
  return <AbsoluteFill style={{ background: theme.bg, overflow: 'hidden' }}>
    <div style={{ width: ART_W, height: ART_H, position: 'absolute', left: '50%', top: '50%',
      marginLeft: -ART_W / 2, marginTop: -ART_H / 2, transform: `scale(${scale})`,
      fontFamily: theme.font, color: theme.ink, WebkitFontSmoothing: 'antialiased' }}>
      {children}
    </div>
  </AbsoluteFill>;
};

/** Typography is the composition: a generous grid, strong scale, one accent. */
export const StudioCard: React.FC<{ seg: StudioSegment; theme: StudioTheme; durF: number }> = ({ seg, theme, durF }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const isCTA = seg.kind === 'cta';
  const isScore = seg.kind === 'score' && typeof seg.score === 'number' && Number.isFinite(seg.score);
  const brand = `${seg.brand ?? ''}${seg.brandAccent ?? ''}`.trim();
  const title = seg.title?.trim() || (isCTA && !theme.logo ? brand : '');
  const sameAsBrand = !!brand && normalize(title) === normalize(brand);
  const logo = isCTA ? theme.logo : null;
  const logoIsHero = !!logo && (!title || sameAsBrand);
  const showWordmark = isCTA && !logo && !!brand && !sameAsBrand;
  const hasBrand = !!logo || showWordmark;
  const lines = studioTitleLines(logoIsHero ? '' : title, logoIsHero ? undefined : seg.titleLines);
  const size = titleSize(lines, 1600, isCTA ? 148 : seg.kind === 'stat' ? 174 : 166, hasBrand ? 420 : 540);
  const energy = clamp(seg.direction?.energy ?? 0.5);
  const centered = seg.direction?.align === 'center';
  const reveal = entrance(frame, durF, fps, 0, 1, energy);
  const supportReveal = entrance(frame, durF, fps, 1, 2, energy);
  const progress = clamp(frame / Math.max(1, durF - 1));
  // A broad light field, with no perpetual oscillation or random noise. The
  // slight translation follows the same direction as the type entrance.
  const lightX = 84 - 3 * settle(progress);

  return <Artboard theme={theme}>
    <AbsoluteFill style={{ background: `radial-gradient(ellipse 92% 130% at ${lightX}% 115%, ${theme.grad} 0%, ${theme.bg} 70%)` }} />
    <div style={{ position: 'absolute', left: 132, right: 132, top: 104, height: 1, background: theme.line,
      transformOrigin: 'left center', transform: `scaleX(${reveal})` }} />
    <div style={{ position: 'absolute', left: centered ? (ART_W - 76 - energy * 28) / 2 : 132,
      top: 104, height: 3, width: 76 + energy * 28,
      background: theme.accent, transformOrigin: centered ? 'center center' : 'left center', transform: `scaleX(${reveal})` }} />

    <div style={{ position: 'absolute', left: 132, right: 132, top: 166, bottom: 142,
      display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: centered ? 'center' : 'flex-start',
      textAlign: centered ? 'center' : 'left' }}>
      {seg.eyebrow && <div style={{ overflow: 'hidden', marginBottom: isScore ? 36 : 32, paddingBottom: 2 }}>
        <div style={{ fontSize: 23, lineHeight: 1.25, fontWeight: 600, letterSpacing: 4.2, textTransform: 'uppercase',
          color: theme.accent, transform: `translateY(${(1 - reveal) * 115}%)` }}>{seg.eyebrow}</div>
      </div>}

      {logo && <Img src={assetUrl(logo)} style={{ objectFit: 'contain', objectPosition: centered ? 'center center' : 'left center',
        maxWidth: logoIsHero ? 1190 : 570, maxHeight: logoIsHero ? 290 : 110,
        marginBottom: logoIsHero ? 26 : 38, opacity: reveal,
        transform: `translateY(${(1 - reveal) * 24}px)` }} />}
      {showWordmark && <div style={{ fontWeight: 700, fontSize: 38, letterSpacing: -1.1, marginBottom: 42,
        opacity: reveal, transform: `translateY(${(1 - reveal) * 18}px)` }}>
        {seg.brand}<span style={{ color: theme.accent }}>{seg.brandAccent}</span>
      </div>}

      {isScore ? <>
        <div style={{ overflow: 'hidden', paddingBottom: 24 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 28, justifyContent: centered ? 'center' : 'flex-start',
            transform: `translateY(${(1 - reveal) * 110}%)` }}>
            {/* Reveal the actual result. Counting through invented intermediate
                scores makes a static receipt look like a live measurement. */}
            <span style={{ fontSize: Math.min(300, 1100 / Math.max(1, textWidth(String(seg.score)))), fontWeight: 600,
              fontVariantNumeric: 'tabular-nums', lineHeight: 0.98, letterSpacing: -13, color: theme.accent }}>{seg.score}</span>
            {typeof seg.scoreMax === 'number' && Number.isFinite(seg.scoreMax) && seg.scoreMax > 0 &&
              <span style={{ fontSize: 80, fontWeight: 500, color: theme.sub, letterSpacing: -3 }}>/ {seg.scoreMax}</span>}
          </div>
        </div>
        {lines.length > 0 && <div style={{ maxWidth: 1540, fontSize: titleSize(lines, 1540, 65, 200), fontWeight: 600,
          letterSpacing: -1.8, lineHeight: 1.12, opacity: supportReveal,
          transform: `translateY(${(1 - supportReveal) * 22}px)` }}>
          {lines.map((line, index) => <div key={index}>{emphasisParts(line, seg.emphasis, theme.accent)}</div>)}
        </div>}
      </> : <div style={{ width: '100%', fontSize: size, fontWeight: 600, lineHeight: 1.02,
        letterSpacing: '-0.055em' }}>
        {lines.map((line, index) => {
          const lineReveal = entrance(frame, durF, fps, index, lines.length, energy);
          return <div key={index} style={{ overflow: 'hidden', paddingBottom: '0.14em', marginBottom: '-0.14em' }}>
            <div style={{ whiteSpace: 'nowrap', transform: `translateY(${(1 - lineReveal) * 115}%)`,
              transformOrigin: '0 100%' }}>{emphasisParts(line, seg.emphasis, theme.accent)}</div>
          </div>;
        })}
      </div>}

      {seg.subtitle && <div style={{ marginTop: isCTA ? 48 : 36, display: 'flex', alignItems: 'center', gap: 26,
        maxWidth: 1450, color: isCTA ? theme.ink : theme.sub,
        fontSize: isCTA ? 36 : 31, fontWeight: 500, letterSpacing: -0.45, lineHeight: 1.4,
        opacity: supportReveal, transform: `translateY(${(1 - supportReveal) * 24}px)` }}>
        {isCTA && <span style={{ display: 'block', width: (centered ? 36 : 44) * supportReveal, height: 2, background: theme.accent, flexShrink: 0 }} />}
        <span>{seg.subtitle}</span>
        {isCTA && <svg width="36" height="36" viewBox="0 0 36 36" style={{ flexShrink: 0, color: theme.accent }}>
          <path d="M6 18H29M20 9L29 18L20 27" fill="none" stroke="currentColor" strokeWidth="2" />
        </svg>}
      </div>}
    </div>
  </Artboard>;
};

/** A physical presentation surface; the source stays a complete 16:9 plane. */
export const StudioStage: React.FC<{ children: React.ReactNode; theme: StudioTheme; durF: number; enabled?: boolean; energy?: number }> = ({ children, theme, durF, enabled = true, energy = 0.5 }) => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  if (!enabled) return <>{children}</>;
  const pace = clamp(energy);
  const arrival = entrance(frame, durF, fps, 0, 1, pace);
  const scale = Math.min(width / ART_W, height / ART_H) * (0.9 - (1 - arrival) * (0.013 + pace * 0.012));
  return <AbsoluteFill style={{ background: theme.bg, overflow: 'hidden',
    backgroundImage: `radial-gradient(ellipse 95% 100% at 50% 110%, ${theme.grad} 0%, ${theme.bg} 80%)` }}>
    <div style={{ position: 'absolute', width: ART_W, height: ART_H, left: '50%', top: '50%',
      marginLeft: -ART_W / 2, marginTop: -ART_H / 2,
      transform: `translateY(${(1 - arrival) * (14 + pace * 20) * scale}px) scale(${scale})`,
      transformOrigin: 'center center', borderRadius: 8,
      boxShadow: `0 0 0 1px ${theme.line}, 0 2px 0 1px rgba(255,255,255,0.09), 0 36px 96px -20px rgba(0,0,0,0.56), 0 6px 16px rgba(0,0,0,0.24)` }}>
      <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', borderRadius: 8, background: theme.bg }}>{children}</div>
      <div style={{ position: 'absolute', inset: 0, borderRadius: 8, pointerEvents: 'none',
        boxShadow: 'inset 0 0 0 1px rgba(255,255,255,0.12)' }} />
    </div>
  </AbsoluteFill>;
};

/** Source-space annotations move with the source when the camera reframes it. */
export const StudioAnnotations: React.FC<{
  annotations?: StudioAnnotation[]; width: number; height: number; fps: number; frame: number; theme?: StudioTheme;
}> = ({ annotations = [], width, height, fps, frame, theme }) => {
  const accent = theme?.accent ?? '#46b07c';
  const bg = theme?.bg ?? '#0c1310';
  const ink = theme?.ink ?? '#f4f6f3';
  const font = theme?.font ?? 'Inter, sans-serif';
  return <AbsoluteFill style={{ pointerEvents: 'none' }}>
    {annotations.map((annotation, index) => {
      if (![annotation.atSec, annotation.endSec, annotation.x, annotation.y, annotation.width, annotation.height].every(Number.isFinite)) return null;
      const start = annotation.atSec * fps;
      const end = annotation.endSec * fps;
      if (frame < start || frame >= end || end <= start) return null;
      const duration = end - start;
      const local = frame - start;
      const reveal = settle(local / Math.max(1, Math.min(fps * 0.3, duration * 0.2)));
      const opacity = Math.min(1, local / Math.max(1, Math.min(fps * 0.12, duration * 0.1)), (end - frame) / Math.max(1, Math.min(fps * 0.14, duration * 0.1)));
      const x = clamp(annotation.x / 100) * width;
      const y = clamp(annotation.y / 100) * height;
      const w = Math.min(width - x, Math.max(1, annotation.width / 100 * width));
      const h = Math.min(height - y, Math.max(1, annotation.height / 100 * height));
      if (w <= 0 || h <= 0 || annotation.width <= 0 || annotation.height <= 0) return null;
      const perimeter = Math.max(1, 2 * (w + h));
      const label = annotation.label?.trim();
      const labelWidth = Math.min(640, Math.max(120, textWidth(label ?? '') * 25 + 36));
      const labelHeight = Math.ceil(textWidth(label ?? '') * 25 / Math.max(1, labelWidth - 32)) * 30 + 20;
      const labelX = clamp(x, 12, Math.max(12, width - labelWidth - 12));
      const labelAbove = y >= labelHeight + 28;
      const labelY = clamp(labelAbove ? y - labelHeight - 16 : y + h + 16, 12, Math.max(12, height - labelHeight - 12));
      return <React.Fragment key={index}>
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ position: 'absolute', inset: 0, overflow: 'visible', opacity }}>
          {annotation.kind === 'spotlight' && <path d={`M0 0H${width}V${height}H0Z M${x} ${y}V${y + h}H${x + w}V${y}Z`}
            fill="rgba(0,0,0,0.36)" fillRule="evenodd" />}
          <rect x={x} y={y} width={w} height={h} rx="6" fill="none" stroke={accent} strokeWidth="2.5"
            strokeDasharray={perimeter} strokeDashoffset={perimeter * (1 - reveal)} />
          {label && <path d={labelAbove ? `M${x + 16} ${y}V${labelY + labelHeight}` : `M${x + 16} ${y + h}V${labelY}`}
            fill="none" stroke={accent} strokeWidth="1.5" opacity={reveal} />}
        </svg>
        {label && <div style={{ position: 'absolute', left: labelX, top: labelY, maxWidth: labelWidth,
          padding: '10px 16px', background: bg, color: ink, border: `1px solid ${accent}`,
          borderRadius: 4, fontFamily: font, fontSize: 24, lineHeight: 1.25, fontWeight: 500,
          boxSizing: 'border-box', opacity: opacity * reveal,
          transform: `translateY(${(1 - reveal) * (labelAbove ? 6 : -6)}px)` }}>{label}</div>}
      </React.Fragment>;
    })}
  </AbsoluteFill>;
};
