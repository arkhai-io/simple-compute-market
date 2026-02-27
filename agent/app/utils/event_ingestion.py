"""Event ingestion utilities for HTTP and Redis sources."""

from __future__ import annotations

from typing import Any

from core.agent.app.utils.event_ingestion import EventIngestion

from app.schema.pydantic_models import EventType
from app.utils.config import CONFIG


def _is_known_event_type(event_type: Any) -> bool:
    try:
        EventType(event_type)
        return True
    except (ValueError, KeyError, TypeError):
        return False


_INGESTION = EventIngestion(
    event_validation_mode=CONFIG.event_validation_mode,
    enable_event_queue=CONFIG.enable_event_queue,
    enable_redis_ingest=CONFIG.enable_redis_ingest,
    redis_url=CONFIG.redis_url,
    redis_channels=CONFIG.redis_channels,
    is_known_event_type=_is_known_event_type,
)


def get_event_queue():
    return _INGESTION.get_event_queue()


def normalize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return EventIngestion.normalize_event_payload(payload)


def queue_event(payload: dict[str, Any]) -> bool:
    return _INGESTION.queue_event(payload)


async def start_redis_subscriber() -> None:
    await _INGESTION.start_redis_subscriber()


async def stop_redis_subscriber() -> None:
    await _INGESTION.stop_redis_subscriber()


def pop_event() -> dict[str, Any] | None:
    return _INGESTION.pop_event()


def has_queued_events() -> bool:
    return _INGESTION.has_queued_events()
