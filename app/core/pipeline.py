import hashlib
import hmac
import json
import logging
import math
from datetime import datetime, timezone

import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from app.models.schemas import RenderRequest
from app.core.video import probe_video

logger = logging.getLogger(__name__)


async def _render_with_lambda(job_id: str, request: RenderRequest, props: dict, settings) -> str:
    """
    Invoke Remotion Lambda via httpx + SigV4 signing.
    Truly async — no run_in_executor, proper 900s timeout.
    Lambda renders + uploads to S3 itself — returns the S3 key.
    """
    logger.info(f"[{job_id}] Invoking Remotion Lambda — function={settings.remotion_lambda_function_name}")

    url = (
        f"https://lambda.{settings.remotion_lambda_region}.amazonaws.com"
        f"/2015-03-31/functions/{settings.remotion_lambda_function_name}/invocations"
    )

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

    payload_bytes = json.dumps(lambda_payload).encode()

    # Sign request with AWS SigV4 using botocore (no boto3 client needed)
    credentials = Credentials(
        access_key=settings.aws_access_key_id,
        secret_key=settings.aws_secret_access_key,
    )
    aws_request = AWSRequest(method="POST", url=url, data=payload_bytes)
    SigV4Auth(credentials, "lambda", settings.remotion_lambda_region).add_auth(aws_request)

    async with httpx.AsyncClient(timeout=900) as client:
        resp = await client.post(
            url,
            content=payload_bytes,
            headers=dict(aws_request.headers),
        )
        resp.raise_for_status()

    # Lambda execution errors come back as 200 with this header set
    if resp.headers.get("x-amz-function-error"):
        raise RuntimeError(f"Lambda execution error: {resp.text}")

    try:
        result_payload = resp.json()
    except Exception:
        raise RuntimeError(f"Lambda returned invalid JSON: {resp.text[:500]}")

    logger.info(f"[{job_id}] Lambda response type={result_payload.get('type')}")

    if result_payload.get("type") == "error":
        raise RuntimeError(f"Lambda render failed: {result_payload.get('message')}")

    s3_key = result_payload.get("outputFile")
    if not s3_key:
        raise RuntimeError(f"Lambda succeeded but returned no outputFile. Response: {result_payload}")

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

        # 2. Build props — Lambda fetches video directly from presigned URL
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

        # 3. Invoke Remotion Lambda
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
