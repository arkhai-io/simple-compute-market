"""Market condition providers for context building."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any

from .config import CONFIG

logger = logging.getLogger(__name__)


class MarketProvider(ABC):
    """Abstract base class for market condition providers."""
    
    @abstractmethod
    async def get_state(self) -> dict[str, Any]:
        """Get current market state."""
        pass


class StaticMarketProvider(MarketProvider):
    """Static market provider that returns default/empty state."""
    
    def __init__(self, default_state: dict[str, Any] | None = None):
        self.default_state = default_state or {}
    
    async def get_state(self) -> dict[str, Any]:
        """Return static/default market state."""
        return self.default_state.copy()


class RedisMarketProvider(MarketProvider):
    """Market provider that reads from Redis keys."""
    
    def __init__(self, redis_url: str, key_patterns: list[str] | None = None):
        self.redis_url = redis_url
        self.key_patterns = key_patterns or ["market:*"]
        self._redis_client = None
    
    async def _get_redis_client(self):
        """Lazy initialization of Redis client."""
        if self._redis_client is None:
            try:
                import redis.asyncio as aioredis
                self._redis_client = aioredis.from_url(self.redis_url, decode_responses=True)
            except ImportError:
                logger.warning("[MARKET] redis library not installed. Falling back to static provider.")
                return None
        return self._redis_client
    
    async def get_state(self) -> dict[str, Any]:
        """Get market state from Redis."""
        redis_client = await self._get_redis_client()
        if redis_client is None:
            return {}
        
        state = {}
        try:
            # For each pattern, scan and get values
            for pattern in self.key_patterns:
                cursor = 0
                while True:
                    cursor, keys = await redis_client.scan(cursor, match=pattern, count=100)
                    for key in keys:
                        try:
                            value = await redis_client.get(key)
                            if value:
                                # Try to parse as JSON, otherwise use raw string
                                try:
                                    parsed = json.loads(value)
                                    # Strip 'market:' prefix for cleaner keys
                                    clean_key = key.replace("market:", "") if key.startswith("market:") else key
                                    state[clean_key] = parsed
                                except json.JSONDecodeError:
                                    clean_key = key.replace("market:", "") if key.startswith("market:") else key
                                    state[clean_key] = value
                        except Exception as e:
                            logger.warning(f"[MARKET] Error reading key {key}: {e}")
                    
                    if cursor == 0:
                        break
            
            logger.debug(f"[MARKET] Loaded {len(state)} market state entries")
        except Exception as e:
            logger.error(f"[MARKET] Error loading market state: {e}")
            return {}
        
        return state


def create_market_provider() -> MarketProvider:
    """Factory to create appropriate market provider based on config."""
    if CONFIG.market_provider == "redis":
        key_patterns = [pattern.strip() for pattern in CONFIG.redis_channels.split(",") if "market" in pattern.lower()]
        if not key_patterns:
            key_patterns = ["market:*"]
        return RedisMarketProvider(CONFIG.redis_url, key_patterns)
    else:
        # Default to static
        return StaticMarketProvider()
