"""Domain-agnostic event ingestion utilities."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections import deque
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


class EventIngestion:
    """Ingestion helper with injectable validation and config flags."""

    def __init__(
        self,
        *,
        event_validation_mode: str,
        enable_event_queue: bool,
        enable_redis_ingest: bool,
        redis_url: str,
        redis_channels: str,
        is_known_event_type: Callable[[Any], bool] | None = None,
    ) -> None:
        self._event_validation_mode = event_validation_mode
        self._enable_event_queue = enable_event_queue
        self._enable_redis_ingest = enable_redis_ingest
        self._redis_url = redis_url
        self._redis_channels = redis_channels
        self._is_known_event_type = is_known_event_type

        self._event_queue: deque[dict[str, Any]] = deque()
        self._redis_task: asyncio.Task | None = None

    def get_event_queue(self) -> deque[dict[str, Any]]:
        return self._event_queue

    def _validate_event(self, payload: dict[str, Any]) -> tuple[bool, str | None]:
        mode = self._event_validation_mode

        if "event_type" not in payload:
            error = "Missing required field: event_type"
            if mode == "strict":
                return False, error
            logger.warning("[VALIDATION] %s", error)
            return True, None

        if self._is_known_event_type is not None:
            try:
                is_known = self._is_known_event_type(payload["event_type"])
            except Exception:
                is_known = False
            if not is_known:
                error = f"Unknown event_type: {payload.get('event_type')}"
                if mode == "strict":
                    return False, error
                logger.warning("[VALIDATION] %s", error)
                return True, None

        if "event_id" not in payload:
            logger.info("[VALIDATION] Missing recommended field: event_id (will be generated)")
        if "source" not in payload:
            logger.info("[VALIDATION] Missing recommended field: source (will use 'unknown')")
        if "timestamp" not in payload:
            logger.info("[VALIDATION] Missing recommended field: timestamp (will use now)")

        return True, None

    @staticmethod
    def normalize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
        normalized = payload.copy()
        if "event_id" not in normalized:
            normalized["event_id"] = f"evt_{uuid.uuid4()}"
        if "source" not in normalized:
            normalized["source"] = "unknown"
        if "timestamp" not in normalized:
            normalized["timestamp"] = datetime.now().isoformat()
        if "data" not in normalized:
            normalized["data"] = payload.copy()
        return normalized

    def queue_event(self, payload: dict[str, Any]) -> bool:
        is_valid, error = self._validate_event(payload)
        if not is_valid:
            logger.error("[VALIDATION] Rejecting invalid event: %s", error)
            return False

        normalized = self.normalize_event_payload(payload)
        if self._enable_event_queue:
            self._event_queue.append(normalized)
            logger.info(
                "[QUEUE] Event queued: %s (%s)",
                normalized.get("event_id"),
                normalized.get("event_type"),
            )
        else:
            logger.info(
                "[INGEST] Processing event inline: %s (%s)",
                normalized.get("event_id"),
                normalized.get("event_type"),
            )
            return True
        return True

    async def _redis_message_handler(self, message: dict[str, Any]) -> None:
        try:
            if message.get("type") == "message":
                channel = (
                    message.get("channel", "").decode()
                    if isinstance(message.get("channel"), bytes)
                    else message.get("channel", "")
                )
                data = message.get("data", b"")
                payload = json.loads(data.decode()) if isinstance(data, bytes) else data
                logger.info(
                    "[REDIS] Received event from channel %s: %s",
                    channel,
                    payload.get("event_id", "unknown"),
                )
                self.queue_event(payload)
        except Exception as e:
            logger.error("[REDIS] Error processing message: %s", e)

    async def _redis_subscriber_loop(self) -> None:
        try:
            import redis.asyncio as aioredis
        except ImportError:
            logger.warning("[REDIS] redis library not installed. Install with: pip install redis")
            return

        try:
            redis_client = aioredis.from_url(self._redis_url, decode_responses=False)
            pubsub = redis_client.pubsub()
            channels = [ch.strip() for ch in self._redis_channels.split(",")]
            for channel in channels:
                await pubsub.psubscribe(channel)
                logger.info("[REDIS] Subscribed to channel pattern: %s", channel)

            async for message in pubsub.listen():
                await self._redis_message_handler(message)
        except Exception as e:
            logger.error("[REDIS] Subscriber error: %s", e, exc_info=True)
            await asyncio.sleep(5)
            if self._enable_redis_ingest:
                logger.info("[REDIS] Attempting to reconnect...")
                await self._redis_subscriber_loop()

    async def start_redis_subscriber(self) -> None:
        if not self._enable_redis_ingest:
            logger.info("[REDIS] Redis ingestion disabled via config")
            return
        if self._redis_task and not self._redis_task.done():
            logger.warning("[REDIS] Subscriber already running")
            return
        try:
            self._redis_task = asyncio.create_task(self._redis_subscriber_loop())
            logger.info("[REDIS] Subscriber started")
        except Exception as e:
            logger.error("[REDIS] Failed to start subscriber: %s", e)

    async def stop_redis_subscriber(self) -> None:
        if self._redis_task and not self._redis_task.done():
            self._redis_task.cancel()
            try:
                await self._redis_task
            except asyncio.CancelledError:
                pass
            logger.info("[REDIS] Subscriber stopped")

    def pop_event(self) -> dict[str, Any] | None:
        if not self._enable_event_queue:
            return None
        if self._event_queue:
            return self._event_queue.popleft()
        return None

    def has_queued_events(self) -> bool:
        if not self._enable_event_queue:
            return False
        return len(self._event_queue) > 0


_DEFAULT_INGESTION: EventIngestion | None = None


def configure_default_ingestion(
    *,
    event_validation_mode: str,
    enable_event_queue: bool,
    enable_redis_ingest: bool,
    redis_url: str,
    redis_channels: str,
    is_known_event_type: Callable[[Any], bool] | None = None,
) -> None:
    global _DEFAULT_INGESTION
    _DEFAULT_INGESTION = EventIngestion(
        event_validation_mode=event_validation_mode,
        enable_event_queue=enable_event_queue,
        enable_redis_ingest=enable_redis_ingest,
        redis_url=redis_url,
        redis_channels=redis_channels,
        is_known_event_type=is_known_event_type,
    )


def _require_default_ingestion() -> EventIngestion:
    if _DEFAULT_INGESTION is None:
        raise RuntimeError(
            "Event ingestion not configured. Call configure_default_ingestion() first."
        )
    return _DEFAULT_INGESTION


def get_event_queue():
    return _require_default_ingestion().get_event_queue()


def queue_event(payload: dict[str, Any]) -> bool:
    return _require_default_ingestion().queue_event(payload)


async def start_redis_subscriber() -> None:
    await _require_default_ingestion().start_redis_subscriber()


async def stop_redis_subscriber() -> None:
    await _require_default_ingestion().stop_redis_subscriber()


def pop_event() -> dict[str, Any] | None:
    return _require_default_ingestion().pop_event()


def has_queued_events() -> bool:
    return _require_default_ingestion().has_queued_events()
