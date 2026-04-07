import asyncio
import hashlib
import hmac
import json
import logging
import math
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import boto3
import httpx

from app.models.schemas import RenderRequest
from app.core.video import probe_video

logger = logging.getLogger(__name__)


def _remotion_bucket(settings) -> str:
    """Extract Remotion Lambda bucket name from serve URL."""
    # 🔴 Problem Area 1: bucket = _remotion_bucket(settings)
    logger.debug(f"_remotion_bucket: REMOTION_LAMBDA_SERVE_URL={settings.remotion_lambda_serve_url}")

    if not settings.remotion_lambda_serve_url:
        logger.error("ERROR: REMOTION_LAMBDA_SERVE_URL is not configured!")
        raise ValueError("REMOTION_LAMBDA_SERVE_URL not set")

    # e.g. https://remotionlambda-apsouth1-ysxu1xtptu.s3.ap-south-1.amazonaws.com/sites/...
    parsed_url = urlparse(settings.remotion_lambda_serve_url)
    hostname = parsed_url.hostname

    if not hostname:
        logger.error(f"ERROR: Could not parse hostname from URL: {settings.remotion_lambda_serve_url}")
        raise ValueError("Invalid REMOTION_LAMBDA_SERVE_URL format")

    bucket = hostname.split(".")[0]
    logger.info(f"_remotion_bucket: Extracted bucket={bucket} from hostname={hostname}")
    logger.debug(f"_remotion_bucket: Full parsed URL - scheme={parsed_url.scheme}, netloc={parsed_url.netloc}")

    return bucket


async def _get_render_progress(render_id: str, bucket: str, settings) -> dict | None:
    """
    Fetch Remotion's progress.json from S3 via boto3.
    Returns None if not yet written (render still starting up).
    """
    key = f"renders/{render_id}/progress.json"
    loop = asyncio.get_running_loop()

    # 🔴 Problem Area 3: S3 client created with credentials
    logger.debug(f"_get_render_progress: Fetching s3://{bucket}/{key}")
    logger.debug(f"_get_render_progress: region={settings.remotion_lambda_region}")
    logger.debug(f"_get_render_progress: AWS_ACCESS_KEY_ID={'***' if settings.aws_access_key_id else 'EMPTY'}")

    try:
        s3 = boto3.client(
            "s3",
            region_name=settings.remotion_lambda_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        logger.debug(f"_get_render_progress: S3 client created successfully")

        response = await loop.run_in_executor(
            None, lambda: s3.get_object(Bucket=bucket, Key=key)
        )
        data = json.loads(response["Body"].read())
        logger.debug(f"_get_render_progress: Successfully fetched progress for render_id={render_id}")
        return data

    except Exception as e:
        error_str = str(e)
        if "NoSuchKey" in error_str or "404" in error_str:
            logger.debug(f"_get_render_progress: progress.json not yet available (render_id={render_id})")
            return None

        # Log detailed error info for debugging
        logger.warning(f"S3 progress poll error (render_id={render_id}, bucket={bucket}, key={key})")
        logger.warning(f"  Error Type: {type(e).__name__}")
        logger.warning(f"  Error Message: {error_str}")

        # Check for specific error types
        if "InvalidAccessKeyId" in error_str or "SignatureDoesNotMatch" in error_str:
            logger.error("ERROR: AWS credentials are invalid or have wrong permissions!")
        elif "NoCredentialProviders" in error_str:
            logger.error("ERROR: AWS credentials not configured!")

        return None


async def _render_with_lambda(job_id: str, request: RenderRequest, props: dict, settings) -> str:
    """
    Invoke Remotion Lambda using the Node.js SDK wrapper.
    The SDK handles all props serialization/deserialization automatically.
    """
    output_bucket = settings.aws_s3_bucket
    progress_bucket = _remotion_bucket(settings)  # Remotion writes progress.json to its own Lambda bucket
    logger.info(f"[{job_id}] Invoking Remotion Lambda via SDK wrapper")
    logger.info(f"[{job_id}] function={settings.remotion_lambda_function_name}, output_bucket={output_bucket}, progress_bucket={progress_bucket}")

    # Build payload for Node.js wrapper
    lambda_payload = {
        "functionName": settings.remotion_lambda_function_name,
        "serveUrl": settings.remotion_lambda_serve_url,
        "composition": "CaptionVideo",
        "inputProps": props,
        "codec": "h264",
        "imageFormat": "jpeg",  # JPEG reduces memory/disk vs PNG (~40% savings)
        "crf": 25,  # H264 quality: 0-51, 25=visually lossless for captions, ~30% faster encode than CRF=18
        "pixelFormat": "yuv420p",  # Standard H264 color format (prevents color shift)
        "maxRetries": 1,
        "framesPerLambda": settings.remotion_lambda_frames_per_lambda,
        "privacy": "private",
        "outName": f"renders/{request.project_id}/final.mp4",
        "s3OutputBucket": output_bucket,
        "s3OutputRegion": settings.remotion_lambda_region,
        "region": settings.remotion_lambda_region,
    }

    props_size = len(json.dumps(props))
    logger.debug(f"[{job_id}] inputProps size: {props_size} bytes")
    logger.debug(f"[{job_id}] inputProps: captions={len(props.get('captions', []))}, segments={len(props.get('segments', []))}")

    # Write payload to temp file
    loop = asyncio.get_running_loop()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(lambda_payload, f)
        payload_file = f.name

    try:
        # Call Node.js wrapper script
        remotion_dir = Path(__file__).parent.parent.parent / "remotion"
        script_path = remotion_dir / "render-lambda.js"

        logger.info(f"[{job_id}] Calling Node.js wrapper: {script_path}")

        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["node", str(script_path), payload_file],
                capture_output=True,
                text=True,
                timeout=600,
            ),
        )

        if result.returncode != 0:
            logger.error(f"[{job_id}] Node.js wrapper failed:")
            logger.error(f"[{job_id}] stderr: {result.stderr}")
            logger.error(f"[{job_id}] stdout: {result.stdout}")
            raise RuntimeError(f"Lambda invocation failed: {result.stderr}")

        logger.debug(f"[{job_id}] Node.js wrapper output: {result.stdout[:500]}")
        response_data = json.loads(result.stdout)

        if not response_data.get("success"):
            error = response_data.get("error", "Unknown error")
            logger.error(f"[{job_id}] Lambda SDK error: {error}")
            raise RuntimeError(f"Lambda render failed: {error}")

        render_data = response_data.get("data", {})
        render_id = render_data.get("renderId")

        if not render_id:
            logger.error(f"[{job_id}] No renderId returned from Lambda")
            logger.error(f"[{job_id}] Response: {response_data}")
            raise RuntimeError("Lambda returned no renderId")

        logger.info(f"[{job_id}] ✅ Lambda accepted render — renderId={render_id}")
        logger.info(f"[{job_id}] Starting progress polling (bucket={progress_bucket}, render_id={render_id})")

    finally:
        # Cleanup temp file
        try:
            Path(payload_file).unlink()
        except Exception as e:
            logger.debug(f"[{job_id}] Failed to delete temp file {payload_file}: {e}")

    # Poll S3 progress.json — max 10 min (120 × 5s)
    for attempt in range(120):
        await asyncio.sleep(5)

        progress = await _get_render_progress(render_id, progress_bucket, settings)

        if progress is None:
            if attempt < 6:  # First 30 seconds - normal for Lambda cold start
                logger.info(f"[{job_id}] [{attempt * 5}s] Waiting for progress.json (Lambda cold start, attempt {attempt + 1})...")
            else:  # After 30 seconds - something is wrong
                logger.warning(f"[{job_id}] [{attempt * 5}s] ⚠️ Progress not yet available (attempt {attempt + 1}/120) — Lambda may be stuck or S3 write failed")
            continue

        if progress.get("fatalErrorEncountered"):
            errors = progress.get("errors", [])
            msg = errors[0].get("message", "unknown") if errors else "unknown"
            logger.error(f"[{job_id}] ❌ FATAL ERROR from Lambda: {msg}")
            logger.debug(f"[{job_id}] Full error details: {errors}")
            raise RuntimeError(f"Lambda render failed: {msg}")

        post_render = progress.get("postRenderData")
        frames_rendered = progress.get("framesRendered", 0)
        chunks = progress.get("chunks", 0)
        lambdas = progress.get("lambdasInvoked", 0)
        logger.info(f"[{job_id}] [{attempt * 5}s] Rendering — {frames_rendered} frames, {chunks} chunks, {lambdas} lambdas")

        # Remotion 4.x signals completion via postRenderData (no "done" key)
        if post_render:
            dest_key = f"renders/{request.project_id}/final.mp4"

            # Output file lands in the Remotion Lambda bucket — copy it to our S3 bucket
            output_url = post_render.get("outputFile", "")
            logger.info(f"[{job_id}] ✅ Lambda render COMPLETE — outputFile={output_url}")
            try:
                parsed = urlparse(output_url)
                path_parts = parsed.path.lstrip("/").split("/", 1)
                src_bucket = path_parts[0]
                src_key = path_parts[1] if len(path_parts) > 1 else ""
                logger.info(f"[{job_id}] Copying s3://{src_bucket}/{src_key} → s3://{settings.aws_s3_bucket}/{dest_key}")
                s3 = boto3.client(
                    "s3",
                    region_name=settings.remotion_lambda_region,
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                )
                await loop.run_in_executor(
                    None,
                    lambda: s3.copy_object(
                        CopySource={"Bucket": src_bucket, "Key": src_key},
                        Bucket=settings.aws_s3_bucket,
                        Key=dest_key,
                    ),
                )
                logger.info(f"[{job_id}] ✅ Copied to s3://{settings.aws_s3_bucket}/{dest_key}")
            except Exception as copy_err:
                logger.error(f"[{job_id}] S3 copy failed: {copy_err}", exc_info=True)
                raise RuntimeError(f"Failed to copy render output to output bucket: {copy_err}")

            return dest_key

    logger.error(f"[{job_id}] ⏱️ TIMEOUT: Lambda render timed out after 10 minutes")
    logger.error(f"[{job_id}] render_id={render_id}, progress_bucket={progress_bucket}")
    raise RuntimeError(f"Lambda render timed out after 10 minutes — render_id={render_id}")


async def run_pipeline(
    job_id: str,
    request: RenderRequest,
    settings,
    update_fn,
) -> None:
    try:
        update_fn(job_id, {"status": "processing"})
        logger.info(f"[{job_id}] Pipeline started — project={request.project_id}")

        # 1. Probe directly from presigned URL — no download needed
        width, height, fps, duration = probe_video(request.video_url)
        logger.info(f"[{job_id}] Probed: {width}x{height} @ {fps:.3f}fps, {duration:.1f}s")

        # 2. Build props — Lambda fetches video directly from presigned URL
        caption_data = request.caption_data

        # Handle rendering dimensions: explicit dimensions take precedence over max_height fallback
        render_width = width
        render_height = height

        if request.render_width and request.render_height:
            # Use explicit dimensions sent by frontend (portrait-aware, no guessing)
            render_width = request.render_width
            render_height = request.render_height
            # Ensure even pixels for h264
            render_width = render_width if render_width % 2 == 0 else render_width - 1
            render_height = render_height if render_height % 2 == 0 else render_height - 1
            if render_width != width or render_height != height:
                logger.info(f"[{job_id}] Scaling: {width}x{height} → {render_width}x{render_height}")
        elif request.max_height and request.max_height < height:
            # Legacy fallback: proportional downscale from max_height
            scale_factor = request.max_height / height
            render_height = request.max_height
            render_width = int(width * scale_factor)
            render_width = render_width if render_width % 2 == 0 else render_width - 1
            logger.info(f"[{job_id}] Downscaling: {width}x{height} → {render_width}x{render_height}")

        props = {
            "videoSrc": request.video_url,
            "width": render_width,
            "height": render_height,
            "fps": round(fps, 6),
            "durationInFrames": int(math.ceil(duration * fps)),
            "captions":       caption_data.get("captions", []),
            "segments":       caption_data.get("segments", []),
            "styles":         caption_data.get("styles", {}),
            "segment_styles": caption_data.get("segment_styles", {}),
            "word_styles":    caption_data.get("word_styles", {}),
        }
        logger.info(f"[{job_id}] Props built — {render_width}x{render_height}, {len(props['captions'])} words, {len(props['segments'])} segments")

        # 3. Invoke Remotion Lambda (async + poll)
        s3_key = await _render_with_lambda(job_id, request, props, settings)

        # 4. Update job + fire callback
        update_fn(job_id, {
            "status": "success",
            "completed_at": datetime.now(timezone.utc),
            "render_s3_key": s3_key,
            "file_size_bytes": None,
        })
        await _fire_callback(request, job_id, s3_key, None, settings)

    except Exception as e:
        logger.error(f"[{job_id}] Pipeline failed: {e}", exc_info=True)
        update_fn(job_id, {
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.now(timezone.utc),
        })
        await _fire_callback(request, job_id, None, None, settings, error=str(e))
        raise


async def _fire_callback(request, job_id, s3_key, file_size, settings, error=None):
    payload = {
        "job_id": job_id,
        "project_id": request.project_id,
        "status": "success" if s3_key else "failed",
        "render_s3_key": s3_key,
        "file_size_bytes": file_size,
        "error": error,
    }
    body = json.dumps(payload).encode()
    secret = (request.callback_secret or settings.callback_hmac_secret).encode()
    sig = hmac.new(secret, body, hashlib.sha256).hexdigest()

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                request.callback_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Render-Signature": f"sha256={sig}",
                },
                timeout=30,
            )
            resp.raise_for_status()
            logger.info(f"[{job_id}] Callback fired → {resp.status_code}")
    except Exception as e:
        logger.error(f"[{job_id}] Callback failed (non-fatal): {e}")
