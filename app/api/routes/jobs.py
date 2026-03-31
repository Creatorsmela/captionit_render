import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request

from app.config import get_settings
from app.models.schemas import JobStatus, RenderJob, RenderRequest
from app.core.workers import get_job, register_job

router = APIRouter(tags=["Jobs"])


def _verify_api_key(request: Request):
    auth = request.headers.get("Authorization", "")
    settings = get_settings()
    if not settings.api_key:
        return   # no key configured = dev mode, allow all
    if auth != f"Bearer {settings.api_key}":
        raise HTTPException(status_code=401, detail="Invalid API key")


@router.post("/jobs", status_code=202)
async def submit_job(
    request: RenderRequest,
    req: Request,
    _=Depends(_verify_api_key),
):
    """Accept a render job. Returns 202 immediately, renders in background."""
    queue = req.app.state.queue

    job_id = str(uuid.uuid4())
    job = RenderJob(
        job_id=job_id,
        project_id=request.project_id,
        status=JobStatus.QUEUED,
        created_at=datetime.now(timezone.utc),
    )
    register_job(job)

    accepted = await queue.enqueue(job_id, request)
    if not accepted:
        raise HTTPException(
            status_code=429,
            detail="Render queue is full. Please try again later.",
        )

    return {"job_id": job_id, "status": "queued"}


@router.get("/jobs/{job_id}")
async def get_job_status(job_id: str, _=Depends(_verify_api_key)):
    """Poll job status."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/health")
async def health(req: Request):
    settings = get_settings()
    queue = req.app.state.queue
    qsize = queue.qsize() if callable(queue.qsize) else "unknown"
    return {
        "status": "ok",
        "queue_backend": "redis" if settings.redis_url else "local",
        "max_concurrent_renders": settings.max_concurrent_renders,
        "queue_size": qsize,
    }
