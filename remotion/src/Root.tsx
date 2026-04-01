import React from "react";
import { loadFont as loadAnton } from "@remotion/google-fonts/Anton";
import { loadFont as loadBangers } from "@remotion/google-fonts/Bangers";
import { loadFont as loadBungee } from "@remotion/google-fonts/Bungee";
import { loadFont as loadCormorantGaramond } from "@remotion/google-fonts/CormorantGaramond";
import { loadFont as loadFredoka } from "@remotion/google-fonts/Fredoka";
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadMontserrat } from "@remotion/google-fonts/Montserrat";
import { loadFont as loadOswald } from "@remotion/google-fonts/Oswald";
import { loadFont as loadPlayfairDisplay } from "@remotion/google-fonts/PlayfairDisplay";
import { loadFont as loadPlusJakartaSans } from "@remotion/google-fonts/PlusJakartaSans";
import { loadFont as loadPoppins } from "@remotion/google-fonts/Poppins";
import { CaptionVideo } from "./components/CaptionVideo";
import { defaultProps, TypedComposition } from "./utils/remotionUtils";

type FontResult = { waitUntilDone: () => Promise<void> };

// Call loadFont() at MODULE LEVEL so each Chromium rendering tab registers the font
// CSS immediately when the bundle loads. Font SELECTION still comes from the API
// (font-family in CSS). We just ensure the font files are available before rendering.
const FONT_WAITERS: Record<string, () => Promise<void>> = {
  "Anton": (loadAnton() as unknown as FontResult).waitUntilDone,
  "Bangers": (loadBangers() as unknown as FontResult).waitUntilDone,
  "Bungee": (loadBungee() as unknown as FontResult).waitUntilDone,
  "Cormorant Garamond": (loadCormorantGaramond() as unknown as FontResult).waitUntilDone,
  "Fredoka": (loadFredoka() as unknown as FontResult).waitUntilDone,
  "Inter": (loadInter() as unknown as FontResult).waitUntilDone,
  "Montserrat": (loadMontserrat() as unknown as FontResult).waitUntilDone,
  "Oswald": (loadOswald() as unknown as FontResult).waitUntilDone,
  "Playfair Display": (loadPlayfairDisplay() as unknown as FontResult).waitUntilDone,
  "Plus Jakarta Sans": (loadPlusJakartaSans() as unknown as FontResult).waitUntilDone,
  "Poppins": (loadPoppins() as unknown as FontResult).waitUntilDone,
};

export const RemotionRoot: React.FC = () => (
  <TypedComposition
    id="CaptionVideo"
    component={CaptionVideo}
    defaultProps={defaultProps}
    durationInFrames={300}
    fps={30}
    width={1920}
    height={1080}
    calculateMetadata={async ({ props }) => {
      // Wait for the font specified by the API to finish downloading
      const fontFamily = (props.styles as { font_family?: string })?.font_family ?? "Inter";
      const waiter = FONT_WAITERS[fontFamily];
      if (waiter) await waiter();

      return {
        fps: props.fps,
        width: props.width,
        height: props.height,
        durationInFrames: props.durationInFrames,
      };
    }}
  />
);
