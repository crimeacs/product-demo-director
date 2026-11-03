import React from 'react';
import { Freeze, OffthreadVideo, Sequence, useVideoConfig } from 'remotion';

/** A build-compiled, frame-exact source-time span within a shot. */
export type SourceSpan = {
  startFrame: number;
  frames: number;
  sourceStartSec: number;
  sourceEndSec: number;
  playbackRate: number;
  hold: boolean;
};

/**
 * Source time and presentation time are independent. A real action can advance
 * at its authored rate, then a known source frame can hold for the explanation.
 * The outer ClipView still owns the camera, framing, and annotations.
 */
export const SourceVideo: React.FC<{
  src: string;
  plan: readonly SourceSpan[];
  muted: boolean;
  style?: React.CSSProperties;
}> = ({ src, plan, muted, style }) => {
  const { fps } = useVideoConfig();
  return <>{plan.map((span, index) => {
    // Remotion trims before changing playback speed. trimBefore is measured in
    // composition-fps frames, even when the source's native fps differs. Do not
    // divide the trim by playbackRate or round away fractional source positions.
    const video = <OffthreadVideo src={src} trimBefore={span.sourceStartSec * fps}
      playbackRate={span.hold ? 1 : span.playbackRate} muted={muted || span.hold} style={style} />;
    return <Sequence key={index} from={span.startFrame} durationInFrames={span.frames}
      layout="none" name={span.hold ? `Hold source ${span.sourceStartSec.toFixed(2)}s`
        : `Source ${span.sourceStartSec.toFixed(2)}–${span.sourceEndSec.toFixed(2)}s`}>
      {/* A hold points at an actual, compiler-validated source timestamp. It does
          not replay or fabricate intermediate UI states and cannot emit audio. */}
      {span.hold ? <Freeze frame={0}>{video}</Freeze> : video}
    </Sequence>;
  })}</>;
};
