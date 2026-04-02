import asyncio
import hashlib
import hmac
import json
import logging
import math
from datetime import datetime, timezone

import boto3
import httpx

from app.models.schemas import RenderRequest
from app.core.video import probe_video

logger = logging.getLogger(__name__)

# Module-level singleton — boto3 clients are thread-safe, reuse across renders
_lambda_client = None

def _get_lambda_client(settings):
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client(
            "lambda",
            region_name=settings.remotion_lambda_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
    return _lambda_client


async def _render_with_lambda(job_id: str, request: RenderRequest, props: dict, settings) -> str:
    """
    Invoke Remotion Lambda synchronously.
    Lambda renders + uploads to S3 itself — returns the S3 key.
    """
    logger.info(f"[{job_id}] Invoking Remotion Lambda — function={settings.remotion_lambda_function_name}")

    lambda_client = _get_lambda_client(settings)

    lambda_payload = {
        "type": "start",
        "serveUrl": settings.remotion_lambda_serve_url,
        "composition": "CaptionVideo",
        "inputProps": props,
        "codec": "h264",
        "imageFormat": "jpeg",
        "maxRetries": 1,
        "framesPerLambda": settings.remotion_lambda_frames_per_lambda,
        "privacy": "private",
        "outName": f"renders/{request.project_id}/final.mp4",
        "s3OutputBucket": settings.aws_s3_bucket,
        "s3OutputRegion": settings.aws_region,
    }

    # Run blocking boto3 call in thread pool so we don't block the event loop
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(
        None,
        lambda: lambda_client.invoke(
            FunctionName=settings.remotion_lambda_function_name,
            InvocationType="RequestResponse",
            Payload=json.dumps(lambda_payload).encode(),
        ),
    )

    result_payload = json.loads(response["Payload"].read())
    logger.info(f"[{job_id}] Lambda response type={result_payload.get('type')}")

    if result_payload.get("type") == "error":
        raise RuntimeError(f"Lambda render failed: {result_payload.get('message')}")

    s3_key = result_payload["outputFile"]
    logger.info(f"[{job_id}] Lambda render complete — s3_key={s3_key}")
    return s3_key


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

        # 3. Build props — Lambda fetches video directly from presigned URL
        caption_data = request.caption_data
        props = {
            "videoSrc": request.video_url,
            "width": width,
            "height": height,
            "fps": round(fps, 6),
            "durationInFrames": int(math.ceil(duration * fps)),
            "captions":       caption_data.get("captions", []),
            "segments":       caption_data.get("segments", []),
            "styles":         caption_data.get("styles", {}),
            "segment_styles": caption_data.get("segment_styles", {}),
            "word_styles":    caption_data.get("word_styles", {}),
        }
        logger.info(f"[{job_id}] Props built ({len(props['captions'])} words, {len(props['segments'])} segments)")

        # 4. Invoke Remotion Lambda
        s3_key = await _render_with_lambda(job_id, request, props, settings)

        # 5. Update job + fire callback
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
