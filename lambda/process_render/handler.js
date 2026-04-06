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
};

const FRAMES_PER_LAMBDA = {
  "360p":  480,
  "720p":  300,
  "1080p": parseInt(process.env.REMOTION_LAMBDA_FRAMES_PER_LAMBDA || "240", 10),
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

    // video dimensions come from the caption_data or are detected client-side
    const width           = caption_data.width           || 1920;
    const height          = caption_data.height          || 1080;
    const fps             = caption_data.fps             || 30;
    const durationInFrames = caption_data.durationInFrames || Math.ceil((caption_data.duration || 60) * fps);

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
        jpegQuality: 80,
        // Force output dimensions — ensures correct aspect ratio even if
        // caption_data dimensions are missing for old projects
        forceWidth: width,
        forceHeight: height,
        maxRetries: 1,
        framesPerLambda,
        // 2 threads per renderer Lambda = ~2x speed with no extra cost
        concurrencyPerLambda: 2,
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
    console.log(`Job ${job_id} accepted by Remotion — renderId=${renderId}`);

    await updateJob(job_id, {
      status: "rendering",
      render_id: renderId,
    });
    // SQS auto-acks on success. Remotion will call the webhook when done.
  }
};
