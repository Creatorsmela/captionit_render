#!/usr/bin/env node
/**
 * Wrapper: Calls Remotion Lambda SDK to render video
 * Usage: node render-lambda.js <payloadJsonFile>
 */

const fs = require("fs");
const { renderMediaOnLambda } = require("@remotion/lambda");

const payloadFile = process.argv[2];
if (!payloadFile) {
  console.error("Usage: node render-lambda.js <payloadJsonFile>");
  process.exit(1);
}

const payload = JSON.parse(fs.readFileSync(payloadFile, "utf-8"));

(async () => {
  try {
    const result = await renderMediaOnLambda({
      functionName: payload.functionName,
      serveUrl: payload.serveUrl,
      composition: payload.composition,
      inputProps: payload.inputProps,
      codec: payload.codec || "h264",
      imageFormat: payload.imageFormat || "jpeg",
      maxRetries: payload.maxRetries || 1,
      framesPerLambda: payload.framesPerLambda || 20,
      privacy: payload.privacy || "private",
      outName: payload.outName,
      s3OutputBucket: payload.s3OutputBucket,
      s3OutputRegion: payload.s3OutputRegion,
      region: payload.region,
    });

    console.log(JSON.stringify({ success: true, data: result }));
  } catch (error) {
    console.error(JSON.stringify({ success: false, error: error.message, stack: error.stack }));
    process.exit(1);
  }
})();
