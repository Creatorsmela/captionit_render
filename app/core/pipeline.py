import asyncio
import contextlib
import hashlib
import hmac
import json
import logging
import math
import os
import subprocess
from datetime import datetime, timezone

import httpx

from app.models.schemas import RenderRequest
from app.core.s3 import upload_video
from app.core.video import probe_video, pre_transcode

logger = logging.getLogger(__name__)


async def run_pipeline(
    job_id: str,
    request: RenderRequest,
    settings,
    update_fn,
) -> None:
    video_path  = f"/tmp/{job_id}_raw.mp4"
    tc_path     = f"/tmp/{job_id}_tc.mp4"
    output_path = f"/tmp/{job_id}_rendered.mp4"
    props_path  = f"/tmp/{job_id}_props.json"

    try:
        update_fn(job_id, {"status": "processing"})

        # 1. Download video via presigned URL (no AWS creds needed)
        logger.info(f"[{job_id}] Downloading video from presigned URL")
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", request.video_url) as resp:
                resp.raise_for_status()
                with open(video_path, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
        logger.info(f"[{job_id}] Video downloaded to {video_path}")

        # 2. Probe
        width, height, fps, duration = probe_video(video_path)
        logger.info(f"[{job_id}] Probed: {width}x{height} @ {fps:.3f}fps, {duration:.1f}s")

        # 3. Pre-transcode if 4K
        active_video = video_path
        if max(width, height) > 1920:
            width, height = pre_transcode(video_path, tc_path)
            active_video = tc_path

        # 4. Build Remotion props
        caption_data = request.caption_data
        props = {
            "videoSrc": f"file://{active_video}",
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
        with open(props_path, "w") as f:
            json.dump(props, f)
        logger.info(f"[{job_id}] Props written ({len(props['captions'])} words, {len(props['segments'])} segments)")

        # 5. Remotion render (subprocess — one Chromium process per job)
        logger.info(f"[{job_id}] Starting Remotion render")
        result = subprocess.run(
            [
                "npx", "remotion", "render",
                "src/index.ts",
                "CaptionVideo",
                output_path,
                f"--props={props_path}",
                "--codec=h264",
                "--crf=18",
                "--concurrency=2",
                "--log=verbose",
            ],
            cwd=settings.remotion_dir,
            capture_output=True,
            timeout=600,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            raise RuntimeError(f"Remotion render failed (exit {result.returncode}):\n{stderr}")
        logger.info(f"[{job_id}] Remotion render complete")

        # 6. Upload to S3
        s3_key = f"renders/{request.project_id}/final.mp4"
        file_size = upload_video(output_path, s3_key, settings)

        # 7. Update job + fire success callback
        update_fn(job_id, {
            "status": "success",
            "completed_at": datetime.now(timezone.utc),
            "render_s3_key": s3_key,
            "file_size_bytes": file_size,
        })
        await _fire_callback(request, job_id, s3_key, file_size, settings)

    except Exception as e:
        logger.error(f"[{job_id}] Pipeline failed: {e}", exc_info=True)
        update_fn(job_id, {
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.now(timezone.utc),
        })
        await _fire_callback(request, job_id, None, None, settings, error=str(e))
        raise

    finally:
        for path in [video_path, tc_path, output_path, props_path]:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)


async def _fire_callback(request, job_id, s3_key, file_size, settings, error=None):
    """HMAC-signed POST to captionit-backend callback URL."""
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
