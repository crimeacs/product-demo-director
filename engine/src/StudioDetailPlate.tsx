import React from 'react';
import { AbsoluteFill, OffthreadVideo, cancelRender, continueRender, delayRender, staticFile, useCurrentFrame, useVideoConfig } from 'remotion';
import { detailCaptionLayout, detailPlateGeometry, detailTitleLayout, type SourceDetail } from './render-math';
import { boundedTransitionFrames, motionEase, transitionProgress } from './studio-motion';
import { SourceVideo, type SourceSpan } from './SourceVideo';
import type { StudioTheme } from './Studio';

/** Check the actual loaded font, rather than silently clipping a width-model miss. */
export const CheckedDetailText: React.FC<{ label: string; style: React.CSSProperties; children: React.ReactNode }> = ({ label, style, children }) => {
  const ref = React.useRef<HTMLDivElement>(null);
  const [handle] = React.useState(() => delayRender(`Fit ${label}`));
  React.useEffect(() => {
    let active = true, released = false;
    const release = () => { if (!released) { released = true; continueRender(handle); } };
    document.fonts.ready.then(() => {
      if (!active || !ref.current) return;
      const box = ref.current.getBoundingClientRect();
      for (const line of Array.from(ref.current.querySelectorAll('[data-detail-line]'))) {
        const range = document.createRange();
        range.selectNodeContents(line);
        const text = range.getBoundingClientRect();
        if (text.left < box.left - 1 || text.right > box.right + 1
          || text.top < box.top - 1 || text.bottom > box.bottom + 1) {
          throw new Error(`${label} does not fit its reserved band in the selected font; shorten the copy or adjust the detail layout`);
        }
      }
    }).catch(cancelRender).finally(release);
    return () => { active = false; release(); };
  }, [handle, label]);
  return <div ref={ref} style={style}>{children}</div>;
};

const DetailTitle: React.FC<{ title: string; detail: SourceDetail; theme: StudioTheme }> = ({ title, detail, theme }) => {
  const { width, height } = useVideoConfig();
  const layout = detailTitleLayout(title, detail, width, height);
  return <CheckedDetailText label="Detail title" style={{ position: 'absolute', left: layout.left,
    width: layout.width, top: layout.top, height: layout.height, color: theme.ink,
    fontFamily: theme.font, fontSize: layout.fontSize, fontWeight: 600, lineHeight: 1.3,
    textAlign: detail.titleAlign ?? 'left' }}>
    {layout.lines.map((line, index) => <div key={index} data-detail-line style={{ whiteSpace: 'nowrap' }}>{line}</div>)}
  </CheckedDetailText>;
};

/** Detail provenance has a reserved below-plate band; it cannot cover the UI. */
export const StudioDetailCaption: React.FC<{
  text: string; detail: SourceDetail; theme: StudioTheme; durF: number; voSec?: number;
  fontSize?: number; top?: number; bottom?: number; quote?: boolean; readout?: boolean;
}> = ({ text, detail, theme, durF, voSec, fontSize, top, bottom, quote, readout }) => {
  const { width, height, fps } = useVideoConfig();
  const frame = useCurrentFrame();
  const artScale = Math.min(width / 1920, height / 1080);
  const layout = detailCaptionLayout(text, detail, width, height, fontSize ?? (quote ? 25 : 23) * artScale, top, bottom);
  const window = Math.max(1, Math.min(durF, voSec ? Math.round((voSec + 0.35) * fps) : durF));
  const length = layout.chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  let consumed = 0;
  const index = layout.chunks.findIndex(chunk => {
    consumed += chunk.length;
    return frame < Math.round(consumed / length * window);
  });
  if (frame >= window) return null;
  // A settled detail cut includes its readout on the first and last picture.
  // Re-fading only the label would make an otherwise stationary stage restart.
  const opacity = detail.entranceSec === 0 ? 1 : Math.max(0, Math.min(1,
    frame / Math.max(1, Math.round(0.12 * fps)),
    (window - frame) / Math.max(1, Math.round(0.2 * fps))));
  return <CheckedDetailText key={index} label="Detail caption" style={{ position: 'absolute',
    left: layout.left, width: layout.width, top: layout.top, height: layout.height,
    zIndex: 6, display: 'flex', justifyContent: 'center', opacity }}>
    <div data-detail-line style={{ padding: `${layout.paddingY}px ${layout.paddingX}px`, boxSizing: 'border-box',
      maxWidth: '100%', background: readout ? 'transparent' : 'rgba(12,14,16,0.55)',
      borderRadius: readout ? 0 : 10 * artScale,
      color: readout ? theme.ink : 'rgba(255,255,255,0.96)', fontFamily: theme.font, fontSize: layout.fontSize,
      lineHeight: 1.3, fontWeight: 500, fontStyle: quote ? 'italic' : 'normal', whiteSpace: 'nowrap' }}>
      {layout.chunks[Math.max(0, index)]}
    </div>
  </CheckedDetailText>;
};

/** A complete native UI object on a quiet canvas, with its original source timing. */
export const StudioDetailPlate: React.FC<{
  src: string;
  sourceWidth?: number;
  sourceHeight?: number;
  detail: SourceDetail;
  sourcePlan?: SourceSpan[];
  inSec?: number;
  muted: boolean;
  durF: number;
  title?: string;
  theme: StudioTheme;
}> = ({ src, sourceWidth, sourceHeight, detail, sourcePlan, inSec = 0, muted, durF, title, theme }) => {
  const { fps, width, height } = useVideoConfig();
  const frame = useCurrentFrame();
  const geometry = React.useMemo(() => detailPlateGeometry(sourceWidth, sourceHeight, width, height, detail),
    [sourceWidth, sourceHeight, width, height, detail]);
  const { plate, video } = geometry;
  const artScale = Math.min(width / 1920, height / 1080);
  const entrance = boundedTransitionFrames((detail.entranceSec ?? 0.4) * fps, durF);
  // transitionProgress(…, 0) is fully settled, including frame zero.
  const settled = motionEase(transitionProgress(frame, entrance));
  // No scale pulse: text settles once and stays on exactly the same pixels.
  // Bound the small arrival by the available margin so no object edge gets cut.
  const travel = Math.min(12 * artScale, Math.max(0, height - plate.top - plate.height));
  const radius = Math.max(0, Math.min(detail.radiusPx ?? 0, plate.width / 2, plate.height / 2));
  const mediaStyle: React.CSSProperties = { position: 'absolute', ...video, objectFit: 'fill' };
  return <AbsoluteFill style={{ background: theme.bg, overflow: 'hidden' }}>
    {title?.trim() && <DetailTitle title={title} detail={detail} theme={theme} />}
    <div style={{ position: 'absolute', ...plate, borderRadius: radius,
      transform: `translate3d(0, ${(1 - settled) * travel}px, 0)`,
      outline: `1px solid ${theme.line}`, boxShadow: `0 ${12 * artScale}px ${36 * artScale}px ${-20 * artScale}px rgba(0,0,0,0.18)` }}>
      <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', borderRadius: radius }}>
        {sourcePlan?.length
          ? <SourceVideo src={staticFile(src)} plan={sourcePlan} muted={muted} style={mediaStyle} />
          : <OffthreadVideo src={staticFile(src)} startFrom={Math.round(inSec * fps)} muted={muted} style={mediaStyle} />}
      </div>
    </div>
  </AbsoluteFill>;
};
