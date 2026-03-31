import React from 'react';
import { AbsoluteFill } from 'remotion';
import { CaptionStyles } from '../types';

interface Props {
  styles: CaptionStyles;
  videoWidth: number;
  videoHeight: number;
  children: React.ReactNode;
}

// BASE_CANVAS_WIDTH matches the frontend's BASE_CANVAS_WIDTH = 1080
const BASE_CANVAS_WIDTH = 1080;

export const CaptionOverlay: React.FC<Props> = ({ styles, videoWidth, children }) => {
  const canvasScale = videoWidth / BASE_CANVAS_WIDTH;
  const posX = styles.position_x ?? 50;
  const posY = styles.position_y ?? 90;

  return (
    <AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          left: `${posX}%`,
          top: `${posY}%`,
          transform: `translate(-50%, -50%) scale(${canvasScale})`,
          transformOrigin: 'center center',
          pointerEvents: 'none',
          whiteSpace: 'nowrap',
        }}
      >
        {children}
      </div>
    </AbsoluteFill>
  );
};
