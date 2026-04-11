import { CalculateMetadataFunction } from "remotion";
import { CaptionVideoProps } from "./captionTypes";

export type CaptionVideoRecord = CaptionVideoProps & Record<string, unknown>;

export type TypedCompositionProps = {
  id: string;
  component: React.ComponentType<CaptionVideoProps>;
  defaultProps: CaptionVideoProps;
  durationInFrames: number;
  fps: number;
  width: number;
  height: number;
  calculateMetadata?: CalculateMetadataFunction<CaptionVideoRecord>;
};
