import asyncio
import hashlib
import hmac
import json
import logging
import math
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import boto3
import httpx
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from app.models.schemas import RenderRequest
from app.core.video import probe_video

logger = logging.getLogger(__name__)


def _sign_request(method: str, url: str, settings, service: str, body: bytes = b"") -> dict:
    """Return signed headers for an AWS request using SigV4."""
    credentials = Credentials(
        access_key=settings.aws_access_key_id,
        secret_key=settings.aws_secret_access_key,
    )
    aws_request = AWSRequest(method=method, url=url, data=body)
    SigV4Auth(credentials, service, settings.remotion_lambda_region).add_auth(aws_request)
    return dict(aws_request.headers)


def _remotion_bucket(settings) -> str:
    """Extract Remotion Lambda bucket name from serve URL."""
    # e.g. https://remotionlambda-apsouth1-ysxu1xtptu.s3.ap-south-1.amazonaws.com/sites/...
    hostname = urlparse(settings.remotion_lambda_serve_url).hostname
    return hostname.split(".")[0]


async def _get_render_progress(render_id: str, bucket: str, settings) -> dict | None:
    """
    Fetch Remotion's progress.json from S3 via boto3.
    Returns None if not yet written (render still starting up).
    """
    key = f"renders/{render_id}/progress.json"
    loop = asyncio.get_running_loop()
    try:
        s3 = boto3.client(
            "s3",
            region_name=settings.remotion_lambda_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        response = await loop.run_in_executor(
            None, lambda: s3.get_object(Bucket=bucket, Key=key)
        )
        return json.loads(response["Body"].read())
    except Exception as e:
        if "NoSuchKey" in str(e) or "404" in str(e):
            return None
        logger.warning(f"S3 progress poll error (render_id={render_id}, bucket={bucket}): {type(e).__name__}: {e}")
        return None


async def _render_with_lambda(job_id: str, request: RenderRequest, props: dict, settings) -> str:
    """
    Invoke Remotion Lambda synchronously to get back the actual renderId,
    then poll progress.json in S3 every 5s.
    The 'start' handler returns in <1s after spawning child Lambdas.
    """
    render_id = uuid.uuid4().hex[:21]
    bucket = _remotion_bucket(settings)

    logger.info(f"[{job_id}] Invoking Remotion Lambda — function={settings.remotion_lambda_function_name} render_id={render_id}")

    url = (
        f"https://lambda.{settings.remotion_lambda_region}.amazonaws.com"
        f"/2015-03-31/functions/{settings.remotion_lambda_function_name}/invocations"
    )

    lambda_payload = {
        "type": "start",
        "version": "4.0.443",
        "renderId": render_id,
        "bucketName": bucket,
        "serveUrl": settings.remotion_lambda_serve_url,
        "composition": "CaptionVideo",
        "inputProps": props,
        "codec": "h264",
        "imageFormat": "jpeg",
        "maxRetries": 1,
        "framesPerLambda": settings.remotion_lambda_frames_per_lambda,
        "privacy": "private",
        "outName": f"renders/{request.project_id}/final.mp4",
    }

    payload_bytes = json.dumps(lambda_payload).encode()
    headers = _sign_request("POST", url, settings, "lambda", payload_bytes)
    # Sync invocation — 'start' handler returns in <1s with the actual renderId

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(url, content=payload_bytes, headers=headers)
        if resp.status_code not in (200, 202):
            raise RuntimeError(f"Lambda invocation failed: HTTP {resp.status_code} — {resp.text}")
        try:
            resp_data = resp.json()
            actual_id = resp_data.get("renderId")
            actual_bucket = resp_data.get("bucketName")
            if actual_id:
                logger.info(f"[{job_id}] Lambda accepted render — actual renderId={actual_id} (requested={render_id})")
                render_id = actual_id
            if actual_bucket:
                bucket = actual_bucket
        except Exception:
            pass  # no JSON body (202 async fallback), use our render_id

    logger.info(f"[{job_id}] Polling progress every 5s (bucket={bucket}, render_id={render_id})")

    # Poll S3 progress.json — max 5 min (60 × 5s)
    for attempt in range(60):
        await asyncio.sleep(5)

        progress = await _get_render_progress(render_id, bucket, settings)

        if progress is None:
            logger.info(f"[{job_id}] [{attempt * 5}s] Waiting for Lambda to start...")
            continue

        if progress.get("fatalErrorEncountered"):
            errors = progress.get("errors", [])
            msg = errors[0].get("message", "unknown") if errors else "unknown"
            raise RuntimeError(f"Lambda render failed: {msg}")

        pct = int(progress.get("overallProgress", 0) * 100)
        chunks = progress.get("chunks", 0)
        lambdas = progress.get("lambdasInvoked", 0)
        frames = progress.get("frames", 0)
        logger.info(f"[{job_id}] [{attempt * 5}s] Rendering {pct}% — {frames} frames, {chunks} chunks, {lambdas} lambdas")

        if progress.get("done"):
            s3_key = progress.get("outputFile") or f"renders/{request.project_id}/final.mp4"
            logger.info(f"[{job_id}] Lambda render complete — s3_key={s3_key}")
            return s3_key

    raise RuntimeError(f"Lambda render timed out after 5 minutes — render_id={render_id}")


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
