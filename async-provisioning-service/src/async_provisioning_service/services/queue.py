from redis.asyncio import Redis

from async_provisioning_service.config import settings


_redis_client: Redis | None = None


async def get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def enqueue_job(job_id: str) -> None:
    redis = await get_redis()
    await redis.lpush(settings.redis_queue_name, job_id)


async def dequeue_job(timeout_seconds: int = 5) -> str | None:
    redis = await get_redis()
    result = await redis.brpop(settings.redis_queue_name, timeout=timeout_seconds)
    if not result:
        return None
    _, job_id = result
    return job_id
