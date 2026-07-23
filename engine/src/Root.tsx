import { Composition } from 'remotion';
import { Timeline, TimelineProps, DEFAULT_THEME } from './Timeline';

const defaultProps: TimelineProps = { fps: 30, totalSec: 10, music: null, sfx: {}, segments: [], theme: DEFAULT_THEME };

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="Timeline"
      component={Timeline}
      durationInFrames={300}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={defaultProps}
      calculateMetadata={({ props }) => ({
        durationInFrames: Math.max(1, props.totalFrames ?? Math.round((props.totalSec || 10) * (props.fps || 30))),
        fps: props.fps || 30,
      })}
    />
  );
};
