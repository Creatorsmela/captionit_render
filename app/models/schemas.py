from datetime import datetime
from enum import Enum
from pydantic import BaseModel


class JobStatus(str, Enum):
    QUEUED      = "queued"
    PROCESSING  = "processing"
    SUCCESS     = "success"
    FAILED      = "failed"


class RenderRequest(BaseModel):
    project_id:      str
    video_url:       str           # presigned S3 URL — no AWS creds needed
    video_s3_key:    str           # kept for reference / upload key derivation
    caption_data:    dict          # full caption payload from /render-payload
    callback_url:    str           # POST destination when done
    callback_secret: str | None = None
    render_width:    int | None = None  # explicit render width in pixels
    render_height:   int | None = None  # explicit render height in pixels
    max_height:      int | None = None  # downscale to this height before rendering (e.g. 1080, 720)


class RenderJob(BaseModel):
    job_id:          str
    project_id:      str
    status:          JobStatus
    created_at:      datetime
    completed_at:    datetime | None = None
    render_s3_key:   str | None = None
    file_size_bytes: int | None = None
    error:           str | None = None
