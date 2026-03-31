import React, { useEffect, useState } from 'react';
import { AbsoluteFill, OffthreadVideo, useCurrentFrame, useVideoConfig, delayRender, continueRender } from 'remotion';
import { CaptionVideoProps, CaptionStyles, WordWithStyle } from '../types';
import { getWordIndices } from '../utils/captionStyles';
import { CaptionOverlay } from './CaptionOverlay';
import { CaptionTextContent } from './CaptionTextContent';

// Build word list for the current segment applying render mode visibility rules
function buildWordsForMode(
  wordIndices: number[],
  captions: CaptionVideoProps['captions'],
  wordStyles: CaptionVideoProps['word_styles'],
  renderMode: string | undefined,
  currentTime: number,
  activeWordId: number | null
): WordWithStyle[] {
  const byId = new Map(captions.map(c => [c.id, c]));

  const all: WordWithStyle[] = wordIndices.map(idx => ({
    text: byId.get(idx)?.text ?? '',
    wordIndex: idx,
    style: wordStyles[String(idx)],
  }));

  switch (renderMode) {
    case 'progressive':
      return all.filter(w => (byId.get(w.wordIndex)?.start ?? Infinity) <= currentTime);

    case 'pop-words':
      return all.filter(w => w.wordIndex === activeWordId);

    case 'fade-words':
      return all.filter(w => (byId.get(w.wordIndex)?.start ?? Infinity) <= currentTime);

    case 'key-word-spotlight':
      return all.map(w => ({
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

  // Font loading — delayRender until Google Fonts ready
  const [fontHandle] = useState(() => delayRender('Loading caption fonts'));
  useEffect(() => {
    const fontFamily = props.styles.font_family ?? 'Noto Sans';
    const weight = props.styles.font_weight ?? 400;
    const url = `https://fonts.googleapis.com/css2?family=${encodeURIComponent(fontFamily)}:wght@${weight}&display=block`;
    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = url;
    document.head.appendChild(link);
    document.fonts.ready.then(() => continueRender(fontHandle));
  }, []);

  // Find current segment
  const segmentIndex = props.segments.findIndex(
    s => currentTime >= s.start && currentTime < s.end
  );
  const currentSegment = segmentIndex >= 0 ? props.segments[segmentIndex] : null;

  // Merge segment style override onto global styles
  const segStyle = segmentIndex >= 0
    ? (props.segment_styles[String(segmentIndex)] ?? {})
    : {};
  const effectiveStyles: CaptionStyles = { ...props.styles, ...segStyle };

  const renderMode = effectiveStyles.render_mode ?? 'normal';
  const highlightColor = effectiveStyles.highlight_color ?? '#FFFF00';

  // Find active word for animated modes
  const activeWordId = (() => {
    const animatedModes = ['word-highlight', 'karaoke', 'progressive', 'key-word-spotlight', 'pop-words', 'fade-words'];
    if (!animatedModes.includes(renderMode)) return null;
    const active = props.captions.find(c => currentTime >= c.start && currentTime < c.end);
    return active?.id ?? null;
  })();

  // Build word list for this segment
  const wordIndices = currentSegment ? getWordIndices(currentSegment) : [];
  const wordsWithStyles = buildWordsForMode(
    wordIndices,
    props.captions,
    props.word_styles,
    renderMode,
    currentTime,
    activeWordId
  );

  return (
    <AbsoluteFill>
      <OffthreadVideo src={props.videoSrc} />
      {currentSegment && wordsWithStyles.length > 0 && (
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
