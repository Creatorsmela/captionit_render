import React, { CSSProperties } from "react";
import { AbsoluteFill } from "remotion";
import { CaptionStyles } from "../types/captionTypes";
import { buildCaptionTextStyle } from "../utils/captionStyles";

interface Props {
  styles: CaptionStyles;
  videoWidth: number;
  videoHeight: number;
  children: React.ReactNode;
}

// Mirror of frontend VideoPreview.tsx:
//   BASE_CANVAS_WIDTH = Math.min(nativeWidth, 1080)
//   canvasScale = videoBounds.width / BASE_CANVAS_WIDTH
const MAX_CANVAS_WIDTH = 1080;

export const CaptionOverlay: React.FC<Props> = ({
  styles,
  videoWidth,
  videoHeight,
  children,
}) => {
  const canvasWidth = Math.min(videoWidth, MAX_CANVAS_WIDTH);
  const canvasHeight =
    videoWidth && videoHeight
      ? canvasWidth * (videoHeight / videoWidth)
      : canvasWidth * (16 / 9);
  const canvasScale = videoWidth / canvasWidth;

  const posX = styles.position_x ?? 50;
  const posY = styles.position_y ?? 90;
  const textAlign = (styles.text_align as CSSProperties["textAlign"]) ?? "center";

  // Mirror frontend: buildCaptionTextStyle(segmentStyle, globalStyles)
  // effectiveStyles already has segment merged onto global, but pass as both
  // so fallback fills any missing fields (e.g. segment only has font_size)
  const captionTextStyle = buildCaptionTextStyle(styles, styles);

  return (
    <AbsoluteFill>
      {/* Canvas div — mirrors frontend: width=canvasWidth, scale to fill video */}
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width: canvasWidth,
          height: canvasHeight,
          transform: `scale(${canvasScale})`,
          transformOrigin: "top left",
        }}
      >
        {/* Position div — mirrors frontend captionDivRef */}
        <div
          style={{
            position: "absolute",
            left: `${posX}%`,
            top: `${posY}%`,
            transform: "translate(-50%, -50%)",
            textAlign,
            width: "100%",
          }}
        >
          {/* Style wrapper — mirrors frontend's <span style={captionTextStyle}> */}
          <span style={{ ...captionTextStyle, display: "inline-block" }}>
            {children}
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
