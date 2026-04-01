import { Composition } from "remotion";
import { TypedCompositionProps } from "../types/remotionRootTypes";
import { CaptionVideoProps } from "../types/captionTypes";

export const TypedComposition =
  Composition as unknown as React.FC<TypedCompositionProps>;

export const defaultProps: CaptionVideoProps = {
  videoSrc: "",
  width: 1920,
  height: 1080,
  fps: 30,
  durationInFrames: 300,
  captions: [],
  segments: [],
  styles: {},
  segment_styles: {},
  word_styles: {},
};
