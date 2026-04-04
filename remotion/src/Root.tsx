import React from "react";
import { CaptionVideo } from "./components/CaptionVideo";
import { defaultProps, TypedComposition } from "./utils/remotionUtils";

type FontResult = { waitUntilDone: () => Promise<void> };

// Cache for loaded fonts to avoid re-loading
const fontLoadCache = new Map<string, Promise<void>>();

/**
 * Convert font display name to module name (e.g., "Dancing Script" → "DancingScript")
 * Handles spaces, hyphens, and special characters
 */
function fontNameToModuleName(fontFamily: string): string {
  return fontFamily
    .split(/[\s-]+/)  // Split by spaces or hyphens
    .map((word) => {
      // Capitalize first letter of each word, lowercase rest
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join("");  // Join without spaces → camelCase
}

/**
 * Dynamically load a Google Font and return promise that resolves when font is ready.
 * Works with any Google Font from @remotion/google-fonts
 */
async function getDynamicFontLoader(fontFamily: string): Promise<() => Promise<void>> {
  // Convert display name to module name (e.g., "Dancing Script" → "DancingScript")
  const moduleName = fontNameToModuleName(fontFamily);

  try {
    // Dynamic import from @remotion/google-fonts/{ModuleName}
    const module = await import(`@remotion/google-fonts/${moduleName}`);
    const loadFont = module.loadFont;
    const fontResult = loadFont() as unknown as FontResult;
    return fontResult.waitUntilDone;
  } catch (error) {
    // Font not found, return no-op
    return async () => {};
  }
}

/**
 * Get or load a font, with caching to avoid duplicate loads
 */
async function ensureFontLoaded(fontFamily: string): Promise<void> {
  if (!fontFamily) return;

  if (!fontLoadCache.has(fontFamily)) {
    fontLoadCache.set(fontFamily, (async () => {
      const loader = await getDynamicFontLoader(fontFamily);
      await loader();
    })());
  }

  await fontLoadCache.get(fontFamily);
}

export const RemotionRoot: React.FC = () => (
  <TypedComposition
    id="CaptionVideo"
    component={CaptionVideo}
    defaultProps={defaultProps}
    durationInFrames={defaultProps.durationInFrames}
    fps={defaultProps.fps}
    width={defaultProps.width}
    height={defaultProps.height}
    calculateMetadata={async ({ props }) => {
      // Dynamically load the font specified by the API
      const fontFamily = (props.styles as { font_family?: string })?.font_family ?? "Inter";
      await ensureFontLoaded(fontFamily);

      return {
        fps: props.fps ?? defaultProps.fps,
        width: props.width ?? defaultProps.width,
        height: props.height ?? defaultProps.height,
        durationInFrames: props.durationInFrames ?? defaultProps.durationInFrames,
      };
    }}
  />
);
