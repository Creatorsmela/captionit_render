import React from "react";
import {
  AbsoluteFill,
  OffthreadVideo,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import {
  CaptionVideoProps,
  CaptionStyles,
  WordWithStyle,
} from "../types/captionTypes";
import { getWordIndices } from "../utils/captionStyles";
import { CaptionOverlay } from "./CaptionOverlay";
import { CaptionTextContent } from "./CaptionTextContent";

function buildWordsForMode(
  wordIndices: number[],
  captions: CaptionVideoProps["captions"],
  wordStyles: CaptionVideoProps["word_styles"],
  renderMode: string | undefined,
  currentTime: number,
  activeWordId: number | null,
): WordWithStyle[] {
  const byId = new Map(captions.map((c) => [c.id, c]));

  const all: WordWithStyle[] = wordIndices.map((idx) => ({
    text: byId.get(idx)?.text ?? "",
    wordIndex: idx,
    style: wordStyles[String(idx)],
  }));

  switch (renderMode) {
    case "progressive":
      return all.filter(
        (w) => (byId.get(w.wordIndex)?.start ?? Infinity) <= currentTime,
      );
    case "pop-words":
      return all.filter((w) => w.wordIndex === activeWordId);
    case "fade-words":
      return all.filter(
        (w) => (byId.get(w.wordIndex)?.start ?? Infinity) <= currentTime,
      );
    case "key-word-spotlight":
      return all.map((w) => ({
        ...w,
        hidden: (byId.get(w.wordIndex)?.start ?? Infinity) > currentTime,
      }));
    default:
      return all;
  }
}

export const CaptionVideo: React.FC<CaptionVideoProps> = (props) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const currentTime = frame / fps;

  const segmentIndex = props.segments.findIndex(
    (s) => currentTime >= s.start && currentTime < s.end,
  );
  const currentSegment =
    segmentIndex >= 0 ? props.segments[segmentIndex] : null;

  const segStyle =
    segmentIndex >= 0 ? (props.segment_styles[String(segmentIndex)] ?? {}) : {};
  const effectiveStyles: CaptionStyles = { ...props.styles, ...segStyle };

  const renderMode = effectiveStyles.render_mode ?? "normal";
  const highlightColor = effectiveStyles.highlight_color ?? "#FFFF00";

  const activeWordId = (() => {
    const animatedModes = [
      "word-highlight", "karaoke", "progressive",
      "key-word-spotlight", "pop-words", "fade-words",
    ];
    if (!animatedModes.includes(renderMode)) return null;
    const active = props.captions.find(
      (c) => currentTime >= c.start && currentTime < c.end,
    );
    return active?.id ?? null;
  })();

  const wordIndices = currentSegment ? getWordIndices(currentSegment) : [];

  // Clamp to the last word's actual end time — segment.end from DB may equal the
  // next segment's start, which would cause captions to show during the gap.
  const captionById = new Map(props.captions.map((c) => [c.id, c]));
  const lastWordEnd =
    wordIndices.length > 0
      ? Math.max(...wordIndices.map((idx) => captionById.get(idx)?.end ?? 0))
      : 0;
  const segmentVisible = currentSegment !== null && currentTime <= lastWordEnd;

  const wordsWithStyles = buildWordsForMode(
    segmentVisible ? wordIndices : [],
    props.captions,
    props.word_styles,
    renderMode,
    currentTime,
    activeWordId,
  );

  return (
    <AbsoluteFill>
      <OffthreadVideo src={props.videoSrc} />
      {segmentVisible && wordsWithStyles.length > 0 && (
        <CaptionOverlay
          styles={effectiveStyles}
          videoWidth={props.width}
          videoHeight={props.height}
        >
          <CaptionTextContent
            words={wordsWithStyles}
            activeWordId={activeWordId}
            renderMode={renderMode}
            styles={effectiveStyles}
            highlightColor={highlightColor}
          />
        </CaptionOverlay>
      )}
    </AbsoluteFill>
  );
};
