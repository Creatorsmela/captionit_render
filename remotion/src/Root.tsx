import React from 'react';
import { Composition } from 'remotion';
import { CaptionVideo } from './components/CaptionVideo';
import { CaptionVideoProps } from './types';

export const RemotionRoot: React.FC = () => (
  <Composition
    id="CaptionVideo"
    component={CaptionVideo}
    durationInFrames={300}
    fps={30}
    width={1920}
    height={1080}
    calculateMetadata={async ({ props }: { props: CaptionVideoProps }) => ({
      fps: props.fps,
      width: props.width,
      height: props.height,
      durationInFrames: props.durationInFrames,
    })}
  />
);
