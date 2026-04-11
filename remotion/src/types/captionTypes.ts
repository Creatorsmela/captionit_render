export interface Caption {
  id: number;
  text: string;
  start: number;
  end: number;
}

// NOTE: old DB rows may use "word_ids" instead of "word_indices" — handle both
export interface Segment {
  start: number;
  end: number;
  word_indices?: number[];
  word_ids?: number[];         // legacy fallback
}

export interface DropShadowSettings {
  enabled: boolean;
  color: string;
  opacity: number;
  offset_x: number;
  offset_y: number;
  blur: number;
}

export interface TextStrokeSettings {
  enabled: boolean;
  color: string;
  width: number;
}

export interface CaptionStyles {
  font_family?: string;
  font_size?: number;
  font_color?: string;
  font_weight?: number;
  bold?: boolean;
  italic?: boolean;
  underline?: boolean;
  uppercase?: boolean;
  text_align?: string;
  letter_spacing?: number;
  line_spacing?: number;
  background_color?: string;
  border_radius?: number;
  padding?: number;
  position_x?: number;
  position_y?: number;
  max_words_per_line?: number;
  highlight_color?: string;
  render_mode?: string;
  animation_config?: Record<string, unknown>;
  drop_shadow?: DropShadowSettings;
  text_stroke?: TextStrokeSettings;
  text_shadow_css?: string;
  glow?: boolean;
  gradient?: string;
  template_id?: string;
}

export type SegmentStyle = Partial<CaptionStyles> & { is_key_word?: boolean };
export type WordStyle = SegmentStyle;

export interface WordWithStyle {
  text: string;
  wordIndex: number;
  style?: WordStyle;
  hidden?: boolean;
}

export interface CaptionVideoProps {
  videoSrc: string;
  width: number;
  height: number;
  fps: number;
  durationInFrames: number;
  captions: Caption[];
  segments: Segment[];
  styles: CaptionStyles;
  segment_styles: Record<string, SegmentStyle>;
  word_styles: Record<string, WordStyle>;
}
