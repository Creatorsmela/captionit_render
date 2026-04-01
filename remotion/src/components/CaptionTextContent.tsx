import React, { CSSProperties } from "react";
import { CaptionStyles, WordWithStyle } from "../types/captionTypes";
import {
  buildCaptionTextStyle,
  buildWordStyle,
  splitIntoLines,
  getHighlightMode,
} from "../utils/captionStyles";

interface Props {
  words: WordWithStyle[];
  activeWordId: number | null;
  renderMode: string;
  styles: CaptionStyles;
  highlightColor: string;
}

export const CaptionTextContent: React.FC<Props> = ({
  words,
  activeWordId,
  renderMode,
  styles,
  highlightColor,
}) => {
  const highlightMode = getHighlightMode(styles);
  // captionTextStyle is the base — mirrors the parent <span style={captionTextStyle}> in frontend
  const captionTextStyle = buildCaptionTextStyle(styles);
  const maxPerLine = styles.max_words_per_line ?? 5;

  // ── key-word-spotlight ───────────────────────────────────────────
  if (renderMode === "key-word-spotlight") {
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
    const firstKeyIdx = runs.findIndex((r) => r.isKey);

    return (
      <div style={{ textAlign: "center" }}>
        {runs.map((run, ri) => {
          const runHidden = run.words.every((w) => w.hidden);
          const align: CSSProperties["textAlign"] = run.isKey
            ? "center"
            : ri < firstKeyIdx
              ? "left"
              : "right";

          return (
            <span
              key={ri}
              style={{
                display: "block",
                textAlign: align,
                visibility: runHidden ? "hidden" : "visible",
              }}
            >
              {run.words.map((w, wi) => {
                // Exact mirror of frontend CaptionTextContent key-word-spotlight
                const base = buildWordStyle(w.style, captionTextStyle, styles);
                const override: CSSProperties = run.isKey
                  ? {
                      fontSize: "2em",
                      color: highlightColor || "#C8FF00",
                      fontWeight: 900,
                      textTransform: "uppercase",
                      lineHeight: 1.1,
                      display: "inline-block",
                    }
                  : {
                      fontSize: "0.72em",
                      opacity: 0.85,
                      visibility: w.hidden ? "hidden" : "visible",
                    };
                return (
                  <span key={`${w.wordIndex}-${wi}`}>
                    <span style={{ ...base, ...override }}>{w.text}</span>
                    {wi < run.words.length - 1 ? " " : ""}
                  </span>
                );
              })}
            </span>
          );
        })}
      </div>
    );
  }

  // ── All other modes: line-by-line ────────────────────────────────
  const lines = splitIntoLines(words, maxPerLine);

  return (
    <div style={{ textAlign: (styles.text_align as CSSProperties["textAlign"]) ?? "center" }}>
      {lines.map((line, li) => (
        <span key={li} style={{ display: "block", whiteSpace: "nowrap" }}>
          {line.map((w, wi) => {
            const isActive =
              (renderMode === "word-highlight" ||
                renderMode === "karaoke" ||
                renderMode === "progressive") &&
              activeWordId != null &&
              w.wordIndex === activeWordId;

            // buildWordStyle returns only word-level overrides, inheriting from captionTextStyle
            const base = buildWordStyle(w.style, captionTextStyle, styles);
            const activeOverride: CSSProperties =
              isActive && highlightColor
                ? highlightMode === "bubble"
                  ? {
                      backgroundColor: highlightColor,
                      borderRadius: "4px",
                      padding: "2px 8px",
                      boxDecorationBreak: "clone",
                      WebkitBoxDecorationBreak: "clone" as any,
                    }
                  : { color: highlightColor }
                : {};

            const hiddenOverride: CSSProperties = w.hidden
              ? { visibility: "hidden" }
              : {};

            return (
              <span
                key={`${w.wordIndex}-${wi}`}
                style={{ ...base, ...activeOverride, ...hiddenOverride }}
              >
                {w.text}
                {wi < line.length - 1 ? " " : ""}
              </span>
            );
          })}
        </span>
      ))}
    </div>
  );
};
