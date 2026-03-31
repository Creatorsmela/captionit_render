import json
import logging
import subprocess

logger = logging.getLogger(__name__)


def probe_video(path: str) -> tuple[int, int, float, float]:
    """
    Returns (display_width, display_height, fps, duration_seconds).
    Swaps width/height for 90°/270° rotated phone videos.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_streams", "-show_format", path],
        capture_output=True, text=True
    )
    data = json.loads(result.stdout)
    video_stream = next((s for s in data["streams"] if s["codec_type"] == "video"), None)

    if not video_stream:
        return 1920, 1080, 30.0, float(data["format"]["duration"])

    width  = int(video_stream["width"])
    height = int(video_stream["height"])
    duration = float(data["format"]["duration"])

    try:
        num, den = video_stream.get("r_frame_rate", "30/1").split("/")
        fps = round(float(num) / float(den), 6) if float(den) else 30.0
    except Exception:
        fps = 30.0

    # Detect rotation — swap dims so caption layout matches display orientation
    rotation = 0
    for sd in video_stream.get("side_data_list") or []:
        if sd.get("side_data_type") == "Display Matrix":
            rotation = abs(int(sd.get("rotation", 0)))
            break
    if rotation in (90, 270):
        width, height = height, width
        logger.info(f"Rotation {rotation}° — swapped to {width}x{height}")

    return width, height, fps, duration


def pre_transcode(input_path: str, output_path: str, max_dim: int = 1920) -> tuple[int, int]:
    """
    Downscale to max_dim on long side. Returns (new_width, new_height).
    Only called when max(width, height) > 1920 (4K source).
    """
    w, h, _, _ = probe_video(input_path)
    scale = max_dim / max(w, h)
    tw = int(w * scale) - int(w * scale) % 2
    th = int(h * scale) - int(h * scale) % 2

    result = subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"scale={tw}:{th}",
        "-c:v", "libx264", "-crf", "18", "-preset", "ultrafast",
        "-c:a", "copy",
        "-metadata:s:v:0", "rotate=0",   # clear rotation tag
        output_path,
    ], capture_output=True)

    if result.returncode != 0:
        raise RuntimeError(f"Pre-transcode failed: {result.stderr.decode(errors='replace')}")

    logger.info(f"Pre-transcode {w}x{h} → {tw}x{th}")
    return tw, th
