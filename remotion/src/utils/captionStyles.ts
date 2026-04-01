import { CSSProperties } from "react";
import { CaptionStyles, SegmentStyle } from "../types/captionTypes";

// Mirror of frontend VideoPreview.tsx highlight mode detection
export function getHighlightMode(styles: CaptionStyles): "text" | "bubble" {
  const explicit = styles.animation_config?.highlight_mode as string | undefined;
  if (explicit === "bubble") return "bubble";
  if (explicit === "text") return "text";
  if (styles.template_id === "bubble-style") return "bubble";
  if (styles.render_mode === "progressive") return "text";
  if (styles.render_mode === "word-highlight" || styles.render_mode === "karaoke") {
    const dur = styles.animation_config?.duration as number | undefined;
    if (dur !== undefined) return dur < 0.25 ? "bubble" : "text";
  }
  return "text";
}

// Exact mirror of frontend src/utils/captionStyles.ts buildCaptionTextStyle
export function buildCaptionTextStyle(
  eff: CaptionStyles | SegmentStyle | null | undefined,
  fallback?: CaptionStyles,
): CSSProperties {
  const src = eff || fallback;
  const ds = (src as any)?.drop_shadow ?? (fallback as any)?.drop_shadow;
  const ts = (src as any)?.text_stroke ?? (fallback as any)?.text_stroke;

  const hasBg = !!(
    src?.background_color &&
    src.background_color !== "null" &&
    src.background_color !== "transparent"
  );
  const bgPadding = (src as any)?.padding;
  const bgRadius = (src as any)?.border_radius;

  return {
    fontFamily: src?.font_family || "Arial",
    fontSize: `${src?.font_size || 24}px`,
    color: src?.font_color || "#FFFFFF",
    backgroundColor: hasBg ? `${src!.background_color}CC` : undefined,
    padding: hasBg ? (bgPadding != null ? `${bgPadding}px` : "8px 12px") : undefined,
    borderRadius: hasBg ? (bgRadius != null ? `${bgRadius}px` : "4px") : undefined,
    fontWeight: src?.font_weight || (src?.bold ? "bold" : undefined),
    fontStyle: src?.italic ? "italic" : undefined,
    textDecoration: src?.underline ? "underline" : undefined,
    textTransform: src?.uppercase ? "uppercase" : undefined,
    letterSpacing: src?.letter_spacing ? `${src.letter_spacing}px` : undefined,
    lineHeight: src?.line_spacing || 1.4,
    textAlign: ((src as any)?.text_align || "center") as CSSProperties["textAlign"],
    textShadow: (src as any)?.text_shadow_css
      ? (src as any).text_shadow_css
      : ds?.enabled
        ? `${ds.offset_x || 0}px ${ds.offset_y || 0}px ${ds.blur || 0}px ${ds.color || "#000000"}${Math.round((ds.opacity ?? 1) * 255).toString(16).padStart(2, "0")}`
        : "1px 1px 2px rgba(0,0,0,0.8)",
    WebkitTextStroke: ts?.enabled
      ? `${ts.width || 1}px ${ts.color || "#000000"}`
      : undefined,
  };
}

// Exact mirror of frontend src/utils/captionStyles.ts buildWordStyle
// Returns ONLY word-specific overrides — base styles are inherited from parent span
export function buildWordStyle(
  word: SegmentStyle | undefined,
  segStyle: CSSProperties,
  globalStyles?: CaptionStyles,
): CSSProperties {
  if (!word) return {};
  const hasBg = !!(
    word.background_color &&
    word.background_color !== "null" &&
    word.background_color !== "transparent"
  );
  return {
    fontFamily: word.font_family || globalStyles?.font_family || "Arial",
    fontSize: word.font_size ? `${word.font_size}px` : undefined,
    color: word.font_color || undefined,
    backgroundColor: hasBg ? `${word.background_color}CC` : undefined,
    padding: hasBg ? "2px 6px" : undefined,
    borderRadius: hasBg ? "4px" : undefined,
    boxDecorationBreak: hasBg ? ("clone" as any) : undefined,
    fontWeight:
      word.font_weight || (word.bold ? "bold" : undefined) || segStyle.fontWeight,
    fontStyle: word.italic ? "italic" : undefined,
    textDecoration: word.underline ? "underline" : undefined,
    textTransform: word.uppercase ? "uppercase" : undefined,
    letterSpacing: word.letter_spacing ? `${word.letter_spacing}px` : undefined,
    lineHeight: word.line_spacing || undefined,
    textShadow: word.drop_shadow?.enabled
      ? `${word.drop_shadow.offset_x || 0}px ${word.drop_shadow.offset_y || 0}px ${word.drop_shadow.blur || 0}px ${word.drop_shadow.color || "#000000"}`
      : undefined,
    WebkitTextStroke: word.text_stroke?.enabled
      ? `${word.text_stroke.width || 1}px ${word.text_stroke.color || "#000000"}`
      : undefined,
  };
}

export function splitIntoLines<T>(items: T[], maxPerLine: number): T[][] {
  const lines: T[][] = [];
  for (let i = 0; i < items.length; i += maxPerLine) {
    lines.push(items.slice(i, i + maxPerLine));
  }
  return lines;
}

export function getWordIndices(segment: {
  word_indices?: number[];
  word_ids?: number[];
}): number[] {
  return segment.word_indices ?? segment.word_ids ?? [];
}
