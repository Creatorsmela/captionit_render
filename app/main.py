import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.core.job_queue import get_queue
from app.core.workers import start_workers
from app.api.routes.jobs import router as jobs_router

# Debug logging based on ENVIRONMENT setting
environment = os.getenv("ENVIRONMENT", "production")
log_level = logging.DEBUG if environment == "development" else logging.INFO

logging.basicConfig(
    level=log_level,
    format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)
logger.info(f"Logging level: {logging.getLevelName(log_level)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    queue = get_queue(settings)
    app.state.queue = queue
    await start_workers(queue, settings)
    mode = "Redis" if settings.redis_url else "Local"
    logger.info(f"Render service ready [{mode} queue, {settings.max_concurrent_renders} workers]")
    yield
    logger.info("Render service shutting down")


app = FastAPI(title="CaptionIT Render Service", lifespan=lifespan)
app.include_router(jobs_router)
