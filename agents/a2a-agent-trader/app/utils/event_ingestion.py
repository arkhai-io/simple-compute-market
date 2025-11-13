"""Event ingestion utilities for HTTP and Redis sources."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime
from typing import Any, Callable, Optional

from app.schema.pydantic_models import EventType
from app.utils.config import CONFIG

logger = logging.getLogger(__name__)

# Global event queue
_event_queue: Optional[deque[dict[str, Any]]] = None
_redis_subscriber: Optional[Any] = None
_redis_task: Optional[asyncio.Task] = None


def get_event_queue() -> deque[dict[str, Any]]:
    """Get or create the global event queue."""
    global _event_queue
    if _event_queue is None:
        _event_queue = deque()
    return _event_queue


def _validate_event(payload: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """Validate event payload. Returns (is_valid, error_message)."""
    mode = CONFIG.event_validation_mode
    
    # Required fields
    if "event_type" not in payload:
        error = "Missing required field: event_type"
        if mode == "strict":
            return False, error
        logger.warning(f"[VALIDATION] {error}")
        return True, None  # Best-effort: continue with warning
    
    # Validate event_type is a known type
    try:
        EventType(payload["event_type"])
    except (ValueError, KeyError):
        error = f"Unknown event_type: {payload.get('event_type')}"
        if mode == "strict":
            return False, error
        logger.warning(f"[VALIDATION] {error}")
        return True, None
    
    # Recommended fields
    if "event_id" not in payload:
        logger.info("[VALIDATION] Missing recommended field: event_id (will be generated)")
    if "source" not in payload:
        logger.info("[VALIDATION] Missing recommended field: source (will use 'unknown')")
    if "timestamp" not in payload:
        logger.info("[VALIDATION] Missing recommended field: timestamp (will use now)")
    
    return True, None


def normalize_event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize event payload with required fields."""
    normalized = payload.copy()
    
    if "event_id" not in normalized:
        import uuid
        normalized["event_id"] = f"evt_{uuid.uuid4()}"
    
    if "source" not in normalized:
        normalized["source"] = "unknown"
    
    if "timestamp" not in normalized:
        normalized["timestamp"] = datetime.now().isoformat()
    
    if "data" not in normalized:
        normalized["data"] = payload.copy()
    
    return normalized


def queue_event(payload: dict[str, Any]) -> bool:
    """Queue an event for processing. Returns True if queued, False if validation failed."""
    is_valid, error = _validate_event(payload)
    if not is_valid:
        logger.error(f"[VALIDATION] Rejecting invalid event: {error}")
        return False
    
    normalized = normalize_event_payload(payload)
    
    if CONFIG.enable_event_queue:
        queue = get_event_queue()
        queue.append(normalized)
        logger.info(f"[QUEUE] Event queued: {normalized.get('event_id')} ({normalized.get('event_type')})")
    else:
        # Process inline if queue disabled
        logger.info(f"[INGEST] Processing event inline: {normalized.get('event_id')} ({normalized.get('event_type')})")
        # This will be handled by the caller
        return True
    
    return True


async def _redis_message_handler(message: dict[str, Any]) -> None:
    """Handle incoming Redis message."""
    try:
        if message.get("type") == "message":
            channel = message.get("channel", "").decode() if isinstance(message.get("channel"), bytes) else message.get("channel", "")
            data = message.get("data", b"")
            
            if isinstance(data, bytes):
                payload = json.loads(data.decode())
            else:
                payload = data
            
            logger.info(f"[REDIS] Received event from channel {channel}: {payload.get('event_id', 'unknown')}")
            queue_event(payload)
    except Exception as e:
        logger.error(f"[REDIS] Error processing message: {e}")


async def _redis_subscriber_loop() -> None:
    """Background task to subscribe to Redis channels."""
    try:
        import redis.asyncio as aioredis
    except ImportError:
        logger.warning("[REDIS] redis library not installed. Install with: pip install redis")
        return
    
    try:
        redis_client = aioredis.from_url(CONFIG.redis_url, decode_responses=False)
        pubsub = redis_client.pubsub()
        
        # Parse channels (comma-separated or pattern)
        channels = [ch.strip() for ch in CONFIG.redis_channels.split(",")]
        
        # Subscribe to channels
        for channel in channels:
            await pubsub.psubscribe(channel)
            logger.info(f"[REDIS] Subscribed to channel pattern: {channel}")
        
        # Listen for messages
        async for message in pubsub.listen():
            await _redis_message_handler(message)
            
    except Exception as e:
        logger.error(f"[REDIS] Subscriber error: {e}", exc_info=True)
        # Try to reconnect after delay
        await asyncio.sleep(5)
        if CONFIG.enable_redis_ingest:
            logger.info("[REDIS] Attempting to reconnect...")
            await _redis_subscriber_loop()


async def start_redis_subscriber() -> None:
    """Start Redis subscriber background task."""
    global _redis_task
    
    if not CONFIG.enable_redis_ingest:
        logger.info("[REDIS] Redis ingestion disabled via config")
        return
    
    if _redis_task and not _redis_task.done():
        logger.warning("[REDIS] Subscriber already running")
        return
    
    try:
        _redis_task = asyncio.create_task(_redis_subscriber_loop())
        logger.info("[REDIS] Subscriber started")
    except Exception as e:
        logger.error(f"[REDIS] Failed to start subscriber: {e}")


async def stop_redis_subscriber() -> None:
    """Stop Redis subscriber background task."""
    global _redis_task
    
    if _redis_task and not _redis_task.done():
        _redis_task.cancel()
        try:
            await _redis_task
        except asyncio.CancelledError:
            pass
        logger.info("[REDIS] Subscriber stopped")


def pop_event() -> Optional[dict[str, Any]]:
    """Pop an event from the queue if available."""
    if not CONFIG.enable_event_queue:
        return None
    
    queue = get_event_queue()
    if queue:
        return queue.popleft()
    return None


def has_queued_events() -> bool:
    """Check if there are events in the queue."""
    if not CONFIG.enable_event_queue:
        return False
    queue = get_event_queue()
    return len(queue) > 0

