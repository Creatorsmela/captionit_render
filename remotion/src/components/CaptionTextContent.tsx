import React, { CSSProperties } from 'react';
import { CaptionStyles, WordWithStyle } from '../types';
import { buildCaptionTextStyle, buildWordStyle, splitIntoLines, getHighlightMode } from '../utils/captionStyles';

interface Props {
  words: WordWithStyle[];
  activeWordId: number | null;
  renderMode: string;
  styles: CaptionStyles;
  highlightColor: string;
}

export const CaptionTextContent: React.FC<Props> = ({
  words, activeWordId, renderMode, styles, highlightColor
}) => {
  const highlightMode = getHighlightMode(styles);
  const baseStyle = buildCaptionTextStyle(styles);
  const maxPerLine = styles.max_words_per_line ?? 5;

  // ── key-word-spotlight layout ────────────────────────────────────
  // Verified against:
  //   frontend  → CaptionTextContent.tsx (lines 42-106)
  //   renderer  → canvas_renderer.py _render_keyword_spotlight_frame() (lines 779-895)
  //
  // Three rules that must be exact:
  //   1. Alignment: key=center, supporting-before-first-key=left, supporting-after=right
  //   2. Run-level visibility: hide entire run if ALL its words are unspoken
  //      (not word-level hide) — prevents layout shift when first word of run appears
  //   3. activeWordId is NOT used here — spotlight is driven purely by is_key_word flag
  if (renderMode === 'key-word-spotlight') {
    // Build runs of consecutive words with same is_key_word status
    const runs: { isKey: boolean; words: WordWithStyle[] }[] = [];
    for (const word of words) {
      const isKey = word.style?.is_key_word === true;
      const last = runs[runs.length - 1];
      if (!isKey && last && !last.isKey) {
        last.words.push(word);
      } else {
        runs.push({ isKey, words: [word] });
      }
    }

    // Index of first key run — determines left/right alignment of supporting runs
    const firstKeyIdx = runs.findIndex(r => r.isKey);

    return (
      <div style={{ textAlign: 'center' }}>
        {runs.map((run, ri) => {
          // Hide entire run if ALL its words are unspoken (matches canvas renderer logic)
          // Individual word-level hidden is NOT used here — whole run appears at once
          const runHidden = run.words.every(w => w.hidden);

          // Alignment mirrors frontend exactly:
          //   key word run     → center
          //   supporting before first key → left
          //   supporting after first key  → right
          const align: CSSProperties['textAlign'] = run.isKey
            ? 'center'
            : ri < firstKeyIdx ? 'left' : 'right';

          return (
            <span key={ri} style={{
              display: 'block',
              textAlign: align,
              visibility: runHidden ? 'hidden' : 'visible',
            }}>
              {run.words.map((w, wi) => {
                const style: CSSProperties = run.isKey
                  ? {
                      ...baseStyle,
                      fontSize: `${(styles.font_size ?? 24) * 2}px`,
                      fontWeight: 900,
                      color: highlightColor,
                      textTransform: 'uppercase',
                      lineHeight: 1.1,
                      display: 'inline-block',
                    }
                  : {
                      ...baseStyle,
                      fontSize: `${(styles.font_size ?? 24) * 0.72}px`,
                      opacity: 0.85,
                      // word-level visibility still needed for words within a partially-spoken run
                      visibility: w.hidden ? 'hidden' : 'visible',
                    };
                return (
                  <span key={wi} style={style}>
                    {w.text}{wi < run.words.length - 1 ? ' ' : ''}
                  </span>
                );
              })}
            </span>
          );
        })}
      </div>
    );
  }

  // ── All other modes: line-by-line layout ─────────────────────────
  const lines = splitIntoLines(words, maxPerLine);

  return (
    <div style={{ textAlign: (styles.text_align as any) ?? 'center' }}>
      {lines.map((line, li) => (
        <div key={li} style={{ display: 'block' }}>
          {line.map((w, wi) => {
            const isActive = activeWordId === w.wordIndex;

            let wordStyle: CSSProperties = buildWordStyle(w.style, baseStyle);

            if (isActive) {
              if (highlightMode === 'bubble') {
                wordStyle = {
                  ...wordStyle,
                  backgroundColor: highlightColor,
                  borderRadius: '4px',
                  padding: '2px 8px',
                  boxDecorationBreak: 'clone',
                  WebkitBoxDecorationBreak: 'clone',
                };
              } else {
                wordStyle = { ...wordStyle, color: highlightColor };
              }
            }

            if (w.hidden) {
              wordStyle = { ...wordStyle, visibility: 'hidden' };
            }

            return (
              <span key={wi} style={wordStyle}>{w.text} </span>
            );
          })}
        </div>
      ))}
    </div>
  );
};
