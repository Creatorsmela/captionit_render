import asyncio
import contextlib
import hashlib
import hmac
import http.server
import json
import logging
import math
import os
import socket
import subprocess
import threading
from datetime import datetime, timezone

import httpx

from app.models.schemas import RenderRequest
from app.core.s3 import upload_video
from app.core.video import probe_video

logger = logging.getLogger(__name__)


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class _SilentHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@contextlib.contextmanager
def _serve_file(path: str):
    """Serve a local file over HTTP so Remotion's Chromium can fetch it (rejects file://)."""
    directory = os.path.dirname(path)
    filename = os.path.basename(path)
    port = _find_free_port()
    server = http.server.HTTPServer(
        ("127.0.0.1", port),
        lambda *a, **kw: _SilentHandler(*a, directory=directory, **kw),
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}/{filename}"
    finally:
        server.shutdown()


async def run_pipeline(
    job_id: str,
    request: RenderRequest,
    settings,
    update_fn,
) -> None:
    video_path  = f"/tmp/{job_id}_raw.mp4"
    output_path = f"/tmp/{job_id}_rendered.mp4"
    props_path  = f"/tmp/{job_id}_props.json"

    try:
        update_fn(job_id, {"status": "processing"})
        logger.info(f"[{job_id}] Pipeline started — project={request.project_id}, max_height={request.max_height}")

        # 1. Download video via presigned URL
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
        native_width, native_height = width, height
        logger.info(f"[{job_id}] Probed: {width}x{height} @ {fps:.3f}fps, {duration:.1f}s")

        # 3. Downscale if max_height requested.
        # max_height is treated as the SHORT SIDE target (standard resolution naming:
        # "1080p" = short side 1080 for both landscape 1920×1080 and portrait 1080×1920).
        short_side = min(width, height)
        if request.max_height and short_side > request.max_height:
            scaled_path = f"/tmp/{job_id}_scaled.mp4"
            logger.info(f"[{job_id}] Downscaling {native_width}x{native_height} — short side {short_side}px → {request.max_height}px")
            scale = request.max_height / short_side
            tw = int(width * scale) - int(width * scale) % 2
            th = int(height * scale) - int(height * scale) % 2
            result = subprocess.run([
                "ffmpeg", "-y", "-i", video_path,
                "-vf", f"scale={tw}:{th}",
                "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast",
                "-c:a", "copy",
                "-metadata:s:v:0", "rotate=0",
                scaled_path,
            ], capture_output=True)
            if result.returncode != 0:
                raise RuntimeError(f"Downscale failed: {result.stderr.decode(errors='replace')}")
            os.replace(scaled_path, video_path)
            width, height = tw, th
            logger.info(f"[{job_id}] Downscale complete: {native_width}x{native_height} → {width}x{height}")
        else:
            if request.max_height:
                logger.info(f"[{job_id}] Skipping downscale: short side {short_side}px <= max_height {request.max_height}px")
            else:
                logger.info(f"[{job_id}] No max_height requested — rendering at original resolution {width}x{height}")

        logger.info(f"[{job_id}] Final render resolution: {width}x{height} (native: {native_width}x{native_height}, max_height requested: {request.max_height})")
        caption_data = request.caption_data
        with _serve_file(video_path) as video_src_url:
            logger.info(f"[{job_id}] Serving video at {video_src_url}")
            props = {
                "videoSrc": video_src_url,
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

            # 5. Remotion render — single pass, H264 output
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
                    "--concurrency=4",
                    "--timeout=120000",
                    "--log=verbose",
                ],
                cwd=settings.remotion_dir,
                capture_output=True,
                timeout=600,
            )

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            raise RuntimeError(f"Remotion render failed (exit {result.returncode}):\n{stderr}")

        output_size = os.path.getsize(output_path)
        logger.info(f"[{job_id}] Remotion render complete ({output_size:,} bytes)")

        # 6. Upload to S3
        s3_key = f"renders/{request.project_id}/final.mp4"
        file_size = upload_video(output_path, s3_key, settings)

        # 7. Update job + fire callback
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
        for path in [video_path, output_path, props_path]:
            with contextlib.suppress(FileNotFoundError):
                os.remove(path)


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
