import asyncio
import json
import logging
from abc import ABC, abstractmethod

from app.models.schemas import RenderRequest

logger = logging.getLogger(__name__)


class AbstractJobQueue(ABC):
    @abstractmethod
    async def enqueue(self, job_id: str, request: RenderRequest) -> bool:
        """Returns False if queue is full — caller should return 429."""
        ...

    @abstractmethod
    async def dequeue(self) -> tuple[str, RenderRequest]:
        """Blocks until a job is available."""
        ...


class LocalJobQueue(AbstractJobQueue):
    """
    Layer 1 — asyncio.Queue.
    Single container, no external deps.
    Jobs lost on restart.
    """
    def __init__(self, maxsize: int):
        self._q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        logger.info(f"LocalJobQueue initialized (maxsize={maxsize})")

    async def enqueue(self, job_id: str, request: RenderRequest) -> bool:
        try:
            self._q.put_nowait((job_id, request))
            return True
        except asyncio.QueueFull:
            return False

    async def dequeue(self) -> tuple[str, RenderRequest]:
        return await self._q.get()

    def qsize(self) -> int:
        return self._q.qsize()


class RedisJobQueue(AbstractJobQueue):
    """
    Layer 2 — Redis LPUSH/BRPOP.
    Multi-container, shared queue, jobs persist on restart.
    """
    QUEUE_KEY = "captionit:render_queue"

    def __init__(self, redis_client, max_queue_size: int):
        self._redis = redis_client
        self._max = max_queue_size
        logger.info(f"RedisJobQueue initialized (maxsize={max_queue_size})")

    async def enqueue(self, job_id: str, request: RenderRequest) -> bool:
        length = await self._redis.llen(self.QUEUE_KEY)
        if length >= self._max:
            return False
        payload = json.dumps({"job_id": job_id, "request": request.model_dump()})
        await self._redis.lpush(self.QUEUE_KEY, payload)
        return True

    async def dequeue(self) -> tuple[str, RenderRequest]:
        # BRPOP blocks until a job arrives — no polling, zero CPU waste
        _, raw = await self._redis.brpop(self.QUEUE_KEY)
        data = json.loads(raw)
        return data["job_id"], RenderRequest(**data["request"])

    async def qsize(self) -> int:
        return await self._redis.llen(self.QUEUE_KEY)


def get_queue(settings) -> AbstractJobQueue:
    """
    Factory — auto-selects backend from config.
    Workers call dequeue() without knowing which backend is used.
    """
    if settings.redis_url:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        return RedisJobQueue(client, settings.max_queue_size)
    return LocalJobQueue(settings.max_queue_size)
