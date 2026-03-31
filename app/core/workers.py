import asyncio
import logging

from app.core.job_queue import AbstractJobQueue
from app.models.schemas import RenderJob

logger = logging.getLogger(__name__)

# In-memory job state store (shared across workers in a single container)
# In Layer 2 (multi-container), use Redis hash instead for cross-container visibility
_job_store: dict[str, RenderJob] = {}


def update_job(job_id: str, patch: dict):
    if job_id in _job_store:
        for k, v in patch.items():
            setattr(_job_store[job_id], k, v)


def get_job(job_id: str) -> RenderJob | None:
    return _job_store.get(job_id)


def register_job(job: RenderJob):
    _job_store[job.job_id] = job


async def start_workers(queue: AbstractJobQueue, settings):
    """Called once at startup — creates N permanent worker coroutines."""
    for i in range(settings.max_concurrent_renders):
        asyncio.create_task(_worker(i, queue, settings))
    logger.info(
        f"Started {settings.max_concurrent_renders} render workers "
        f"({'Redis' if settings.redis_url else 'Local'} queue)"
    )


async def _worker(worker_id: int, queue: AbstractJobQueue, settings):
    """
    Permanent coroutine — pulls one job at a time from the queue.
    MAX_CONCURRENT_RENDERS controls how many of these run simultaneously.
    """
    from app.core.pipeline import run_pipeline
    logger.info(f"Worker {worker_id} ready")
    while True:
        job_id, request = await queue.dequeue()   # blocks until job available
        logger.info(f"Worker {worker_id} picked up job {job_id}")
        try:
            await run_pipeline(job_id, request, settings, update_job)
        except Exception as e:
            logger.error(f"Worker {worker_id} unhandled error on job {job_id}: {e}", exc_info=True)
