"""Unit tests for the queue module (async_provisioning_service.services.queue)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from async_provisioning_service.config import settings
from async_provisioning_service.services.queue import dequeue_job, enqueue_job, get_redis


@pytest.fixture(autouse=True)
def reset_redis(monkeypatch):
    """Reset the module-level Redis singleton before each test."""
    import async_provisioning_service.services.queue as q

    monkeypatch.setattr(q, "_redis_client", None)


class TestGetRedis:
    @pytest.mark.anyio
    async def test_get_redis_creates_connection(self):
        mock_redis = AsyncMock()
        with patch("async_provisioning_service.services.queue.Redis") as mock_cls:
            mock_cls.from_url.return_value = mock_redis
            result = await get_redis()

        mock_cls.from_url.assert_called_once_with(settings.redis_url, decode_responses=True)
        assert result is mock_redis

    @pytest.mark.anyio
    async def test_get_redis_reuses_connection(self):
        mock_redis = AsyncMock()
        with patch("async_provisioning_service.services.queue.Redis") as mock_cls:
            mock_cls.from_url.return_value = mock_redis
            first = await get_redis()
            second = await get_redis()

        # from_url should only be called once despite two calls to get_redis()
        mock_cls.from_url.assert_called_once()
        assert first is second


class TestEnqueueJob:
    @pytest.mark.anyio
    async def test_enqueue_job(self):
        mock_redis = AsyncMock()
        with patch("async_provisioning_service.services.queue.get_redis", return_value=mock_redis):
            await enqueue_job("job-123")

        mock_redis.lpush.assert_called_once_with(settings.redis_queue_name, "job-123")


class TestDequeueJob:
    @pytest.mark.anyio
    async def test_dequeue_job_returns_id(self):
        mock_redis = AsyncMock()
        mock_redis.brpop.return_value = (settings.redis_queue_name, "job-123")
        with patch("async_provisioning_service.services.queue.get_redis", return_value=mock_redis):
            result = await dequeue_job(timeout_seconds=5)

        assert result == "job-123"
        mock_redis.brpop.assert_called_once_with(settings.redis_queue_name, timeout=5)

    @pytest.mark.anyio
    async def test_dequeue_job_timeout_returns_none(self):
        mock_redis = AsyncMock()
        mock_redis.brpop.return_value = None
        with patch("async_provisioning_service.services.queue.get_redis", return_value=mock_redis):
            result = await dequeue_job(timeout_seconds=5)

        assert result is None
