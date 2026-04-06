/**
 * Lambda: captionit-render-process
 * Trigger: SQS (batchSize=1)
 *
 * Receives a render job from SQS, builds Remotion props,
 * calls renderMediaOnLambda with a webhook for completion,
 * stores the render_id in DynamoDB, then exits.
 * No S3 polling — Remotion calls the webhook when done.
 */

const { DynamoDBClient } = require("@aws-sdk/client-dynamodb");
const { DynamoDBDocumentClient, UpdateCommand } = require("@aws-sdk/lib-dynamodb");
const { renderMediaOnLambda } = require("@remotion/lambda");

const DYNAMODB_TABLE = process.env.DYNAMODB_TABLE;
// BACKEND_URL: base URL of the CaptionIT backend (e.g. https://captions.example.com)
// Remotion will POST to {BACKEND_URL}/api/v1/webhook/remotion-complete on completion.
const BACKEND_URL = process.env.BACKEND_URL;
const CALLBACK_HMAC_SECRET = process.env.CALLBACK_HMAC_SECRET;
const AWS_S3_BUCKET = process.env.AWS_S3_BUCKET;
const REMOTION_LAMBDA_REGION = process.env.REMOTION_LAMBDA_REGION || "ap-south-1";
const REMOTION_LAMBDA_SERVE_URL = process.env.REMOTION_LAMBDA_SERVE_URL;

const LAMBDA_FUNCTIONS = {
  "360p":  process.env.REMOTION_LAMBDA_FUNCTION_360P  || process.env.REMOTION_LAMBDA_FUNCTION_1080P,
  "720p":  process.env.REMOTION_LAMBDA_FUNCTION_720P  || process.env.REMOTION_LAMBDA_FUNCTION_1080P,
  "1080p": process.env.REMOTION_LAMBDA_FUNCTION_1080P,
  "4k":    process.env.REMOTION_LAMBDA_FUNCTION_4K    || process.env.REMOTION_LAMBDA_FUNCTION_1080P,
};

// framesPerLambda controls how many parallel Lambdas Remotion spawns.
// Lower = more parallel Lambdas = faster render (at higher cost).
// Formula: parallel_lambdas = totalFrames / framesPerLambda
// For 1 min @ 30fps (1800 frames):
//   360p:  1800/120 = 15 parallel Lambdas
//   720p:  1800/100 = 18 parallel Lambdas
//   1080p: 1800/80  = 22 parallel Lambdas
//   4k:    1800/60  = 30 parallel Lambdas
const FRAMES_PER_LAMBDA = {
  "360p":  120,
  "720p":  100,
  "1080p": 80,
  "4k":    60,
};

// Concurrent browser tabs per renderer Lambda.
// 4K: 4 tabs on 10GB Lambda (4 × 600MB = 2.4GB, safe).
// Others: 2 tabs on 3GB Lambda (2 × 400MB = 800MB, safe).
const CONCURRENCY_PER_LAMBDA = {
  "360p":  2,
  "720p":  2,
  "1080p": 2,
  "4k":    4,
};

const ddb = DynamoDBDocumentClient.from(new DynamoDBClient({ region: REMOTION_LAMBDA_REGION }));

async function updateJob(jobId, patch) {
  const keys = Object.keys(patch);
  const setExpr = keys.map((k) => `#${k} = :${k}`).join(", ");
  await ddb.send(new UpdateCommand({
    TableName: DYNAMODB_TABLE,
    Key: { job_id: jobId },
    UpdateExpression: `SET ${setExpr}`,
    ExpressionAttributeNames: Object.fromEntries(keys.map((k) => [`#${k}`, k])),
    ExpressionAttributeValues: Object.fromEntries(keys.map((k) => [`:${k}`, patch[k]])),
  }));
}

exports.handler = async (event) => {
  for (const record of event.Records) {
    const { job_id, request } = JSON.parse(record.body);
    const {
      project_id,
      video_url,
      caption_data,
      callback_url,
      callback_secret,
      max_height,
      quality = "1080p",
    } = request;

    console.log(`Processing job ${job_id} for project ${project_id} (quality=${quality})`);

    await updateJob(job_id, {
      status: "processing",
      callback_url: callback_url || "",
      callback_secret: callback_secret || "",
      quality,
    });

    // Build Remotion props (mirrors pipeline.py)
    const captions       = caption_data.captions       || [];
    const segments       = caption_data.segments       || [];
    const styles         = caption_data.styles         || {};
    const segment_styles = caption_data.segment_styles || {};
    const word_styles    = caption_data.word_styles    || {};

    // video dimensions — passed from backend (ffprobe at transcription or render time)
    console.log(`[process-render] job=${job_id} project=${project_id} | received dimensions from backend: width=${caption_data.width} height=${caption_data.height} fps=${caption_data.fps} durationInFrames=${caption_data.durationInFrames} duration=${caption_data.duration}`);

    const rawWidth  = caption_data.width  || 1920;
    const rawHeight = caption_data.height || 1080;
    const fps             = caption_data.fps             || 30;
    const durationInFrames = caption_data.durationInFrames || Math.ceil((caption_data.duration || 60) * fps);

    if (!caption_data.width || !caption_data.height) {
      console.warn(`[process-render] job=${job_id} | WARNING: width/height missing from backend payload — falling back to ${rawWidth}x${rawHeight}. Check backend ffprobe logs.`);
    }

    // Scale down to the quality preset's max long-side dimension, preserving aspect ratio.
    // This prevents OOM on the Lambda for high-res source videos.
    // 4K uses a dedicated 10GB Lambda and is not scaled down.
    // Quality caps: 1080p → 1920px, 720p → 1280px, 360p → 640px, 4k → 3840px
    const QUALITY_MAX_LONG_SIDE = { "360p": 640, "720p": 1280, "1080p": 1920, "4k": 3840 };
    const maxLongSide = QUALITY_MAX_LONG_SIDE[quality] || 1920;
    const longSide = Math.max(rawWidth, rawHeight);
    const scale = longSide > maxLongSide ? maxLongSide / longSide : 1;
    // H264 requires even dimensions — round to nearest even number
    const width  = Math.round(rawWidth  * scale / 2) * 2;
    const height = Math.round(rawHeight * scale / 2) * 2;

    if (scale < 1) {
      console.log(`[process-render] job=${job_id} | Scaled ${rawWidth}x${rawHeight} → ${width}x${height} (${quality} cap: ${maxLongSide}px long side, scale=${scale.toFixed(3)})`);
    }

    console.log(`[process-render] job=${job_id} | FINAL props for Remotion: width=${width} height=${height} fps=${fps} durationInFrames=${durationInFrames} quality=${quality} functionName=${LAMBDA_FUNCTIONS[quality] || LAMBDA_FUNCTIONS["1080p"]}`);

    const props = {
      videoSrc: video_url,
      width,
      height,
      fps,
      durationInFrames,
      captions,
      segments,
      styles,
      segment_styles,
      word_styles,
    };

    const functionName = LAMBDA_FUNCTIONS[quality] || LAMBDA_FUNCTIONS["1080p"];
    const framesPerLambda = FRAMES_PER_LAMBDA[quality] || 150;
    const outName = `renders/${project_id}/${quality}.mp4`;

    // Webhook config — Remotion calls this URL when the render completes.
    // Routes to the backend directly (no Lambda Function URL needed).
    const webhook = BACKEND_URL ? {
      url: `${BACKEND_URL}/api/v1/webhook/remotion-complete`,
      secret: CALLBACK_HMAC_SECRET,
    } : undefined;

    let result;
    try {
      result = await renderMediaOnLambda({
        functionName,
        serveUrl: REMOTION_LAMBDA_SERVE_URL,
        composition: "CaptionVideo",
        inputProps: props,
        codec: "h264",
        imageFormat: "jpeg",
        // 4K: quality 70 is indistinguishable at that resolution but 30% faster I/O
        jpegQuality: quality === "4k" ? 70 : 80,
        maxRetries: 1,
        framesPerLambda,
        concurrencyPerLambda: CONCURRENCY_PER_LAMBDA[quality] || 2,
        privacy: "private",
        outName,
        s3OutputBucket: AWS_S3_BUCKET,
        s3OutputRegion: REMOTION_LAMBDA_REGION,
        region: REMOTION_LAMBDA_REGION,
        timeoutInMilliseconds: 240000,
        webhook,
      });
    } catch (err) {
      console.error(`renderMediaOnLambda failed for job ${job_id}: ${err.message}`);
      await updateJob(job_id, {
        status: "failed",
        error: err.message,
        completed_at: Math.floor(Date.now() / 1000),
      });
      // Rethrow so SQS moves the message to DLQ after maxReceiveCount
      throw err;
    }

    const renderId = result.renderId;
    const bucketName = result.bucketName;
    console.log(`Job ${job_id} accepted by Remotion — renderId=${renderId} bucket=${bucketName}`);

    await updateJob(job_id, {
      status: "rendering",
      render_id: renderId,
      remotion_bucket: bucketName,
      function_name: functionName,
    });
    // SQS auto-acks on success. Remotion will call the webhook when done.
  }
};
