import { CSSProperties } from 'react';
import { CaptionStyles, SegmentStyle, WordStyle } from '../types';

// Mirror of frontend VideoPreview.tsx highlight mode detection
export function getHighlightMode(styles: CaptionStyles): 'text' | 'bubble' {
  const explicit = styles.animation_config?.highlight_mode as string | undefined;
  if (explicit === 'bubble') return 'bubble';
  if (explicit === 'text') return 'text';
  if (styles.template_id === 'bubble-style') return 'bubble';
  if (styles.render_mode === 'progressive') return 'text';
  if (styles.render_mode === 'word-highlight' || styles.render_mode === 'karaoke') {
    const dur = styles.animation_config?.duration as number | undefined;
    if (dur !== undefined) return dur < 0.25 ? 'bubble' : 'text';
  }
  return 'text';
}

// Converts CaptionStyles → React CSSProperties
export function buildCaptionTextStyle(
  styles: CaptionStyles | SegmentStyle | null | undefined
): CSSProperties {
  if (!styles) return {};

  const css: CSSProperties = {};

  if (styles.font_family) css.fontFamily = styles.font_family;
  if (styles.font_size)   css.fontSize   = `${styles.font_size}px`;
  if (styles.font_color)  css.color      = styles.font_color;

  const weight = styles.font_weight ?? (styles.bold ? 700 : 400);
  css.fontWeight = weight;

  if (styles.italic)    css.fontStyle     = 'italic';
  if (styles.underline) css.textDecoration = 'underline';
  if (styles.uppercase) css.textTransform  = 'uppercase';
  if (styles.text_align) css.textAlign     = styles.text_align as CSSProperties['textAlign'];
  if (styles.letter_spacing != null) css.letterSpacing = `${styles.letter_spacing}px`;

  const lineSpacing = styles.line_spacing ?? 1.4;
  css.lineHeight = lineSpacing;

  const rawBg = String(styles.background_color ?? '').toLowerCase().trim();
  if (rawBg && rawBg !== 'null' && rawBg !== 'transparent') {
    css.backgroundColor = styles.background_color!;
    css.borderRadius    = `${styles.border_radius ?? 4}px`;
    css.padding         = `${styles.padding ?? 4}px ${(styles.padding ?? 4) * 2}px`;
  }

  if (styles.drop_shadow?.enabled) {
    const ds = styles.drop_shadow;
    const alpha = Math.round((ds.opacity ?? 1) * 255).toString(16).padStart(2, '0');
    css.textShadow = `${ds.offset_x}px ${ds.offset_y}px ${ds.blur}px ${ds.color}${alpha}`;
  } else if (styles.text_shadow_css) {
    css.textShadow = styles.text_shadow_css;
  }

  if (styles.text_stroke?.enabled) {
    const ts = styles.text_stroke;
    (css as any).WebkitTextStroke = `${ts.width}px ${ts.color}`;
  }

  return css;
}

// Merges word override onto a base style
export function buildWordStyle(
  wordStyle: WordStyle | undefined,
  baseStyle: CSSProperties
): CSSProperties {
  if (!wordStyle) return baseStyle;
  const overrides = buildCaptionTextStyle(wordStyle);
  return { ...baseStyle, ...overrides };
}

// Chunks array into lines
export function splitIntoLines<T>(items: T[], maxPerLine: number): T[][] {
  const lines: T[][] = [];
  for (let i = 0; i < items.length; i += maxPerLine) {
    lines.push(items.slice(i, i + maxPerLine));
  }
  return lines;
}

// Resolve segment word indices — handles both "word_indices" and legacy "word_ids"
export function getWordIndices(segment: { word_indices?: number[]; word_ids?: number[] }): number[] {
  return segment.word_indices ?? segment.word_ids ?? [];
}
