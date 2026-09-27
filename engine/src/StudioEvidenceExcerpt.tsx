import React from 'react';
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from 'remotion';
import { CheckedDetailText } from './StudioDetailPlate';
import { detailTextWidth } from './render-math';
import { boundedTransitionFrames, motionEase, transitionProgress } from './studio-motion';
import type { StudioTheme } from './Studio';

/** Editorial readout, never a reconstructed product screen or an invented quotation. */
export type EvidenceExcerpt = {
  finding: string;
  source: string;
  limitation: string;
  label: string;
};

function fitLines(text: string, fontSize: number, maxLines: number, width: number): string[] | null {
  if (typeof text !== 'string' || !text.trim()) return null;
  const lines: string[] = [];
  for (const word of text.trim().split(/\s+/u)) {
    if (detailTextWidth(word) * fontSize * 1.1 > width) return null;
    const previous = lines[lines.length - 1];
    if (previous && detailTextWidth(`${previous} ${word}`) * fontSize * 1.1 <= width) {
      lines[lines.length - 1] += ` ${word}`;
    } else lines.push(word);
  }
  return lines.length <= maxLines ? lines : null;
}

/** Every field stays readable at a 320px player; excessive copy fails instead of shrinking. */
export const StudioEvidenceExcerpt: React.FC<{
  excerpt: EvidenceExcerpt; theme: StudioTheme; durF: number; align?: 'left' | 'center';
}> = ({ excerpt, theme, durF, align = 'left' }) => {
  const { fps, width, height } = useVideoConfig();
  const frame = useCurrentFrame();
  const scale = Math.min(width / 1920, height / 1080);
  const left = (width - 1920 * scale) / 2, top = (height - 1080 * scale) / 2;
  const centered = align === 'center';
  const label = fitLines(excerpt.label, 72, 1, 1656);
  let finding: string[] | null = null, findingSize = 120;
  for (; findingSize >= 100; findingSize--) {
    finding = fitLines(excerpt.finding, findingSize, 2, 1656);
    if (finding && finding.length * findingSize * 1.3 <= 276) break;
    finding = null;
  }
  const source = fitLines(excerpt.source, 76, 2, 1656);
  const limitation = fitLines(excerpt.limitation, 76, 2, 1624);
  if (!label || !finding || !source || !limitation) {
    throw new Error('Evidence excerpt cannot fit at a phone-readable size; shorten its finding, source, limitation, or label');
  }
  const arrival = motionEase(transitionProgress(frame, boundedTransitionFrames(0.22 * fps, durF)));
  const textBand = (name: string, lines: string[], fontSize: number, y: number,
    x = 132, availableWidth = 1656, weight = 500, move = 0) => (
    <CheckedDetailText label={`Evidence ${name}`} style={{ position: 'absolute',
      left: left + x * scale, top: top + (y + move) * scale,
      width: availableWidth * scale, height: lines.length * fontSize * 1.3 * scale,
      color: theme.ink, fontFamily: theme.font, fontSize: fontSize * scale,
      fontWeight: weight, lineHeight: 1.3, textAlign: align }}>
      {lines.map((line, index) => <div key={index} data-detail-line style={{ whiteSpace: 'nowrap' }}>{line}</div>)}
    </CheckedDetailText>
  );
  return <AbsoluteFill style={{ background: theme.bg, overflow: 'hidden', WebkitFontSmoothing: 'antialiased' }}>
    {textBand('provenance', label, 72, 104)}
    <div style={{ position: 'absolute', left: left + 132 * scale, top: top + 226 * scale,
      width: 1656 * scale, height: scale, background: theme.line }} />
    <div style={{ position: 'absolute', left: left + (centered ? 918 : 132) * scale, top: top + 224 * scale,
      width: 84 * scale, height: 4 * scale, background: theme.accent }} />
    {textBand('finding', finding, findingSize, 294, 132, 1656, 600, (1 - arrival) * 8)}
    {textBand('source', source, 76, 594)}
    <div style={{ position: 'absolute', left: left + (centered ? 918 : 132) * scale,
      top: top + (centered ? 782 : 815) * scale, width: (centered ? 84 : 4) * scale,
      height: (centered ? 4 : 76 * 1.3) * scale, background: theme.accent }} />
    {textBand('limitation', limitation, 76, 812, centered ? 148 : 164, 1624)}
  </AbsoluteFill>;
};
