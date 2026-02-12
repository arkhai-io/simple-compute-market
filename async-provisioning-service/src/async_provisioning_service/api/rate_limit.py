"""
Per-agent rate limiting middleware.

Uses a sliding window counter per agent_id. Disabled by default.
Enable via ENABLE_RATE_LIMITING=true and configure
RATE_LIMIT_REQUESTS_PER_MINUTE.
"""

import logging
import time
from collections import defaultdict
from collections.abc import MutableMapping

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from async_provisioning_service.config import settings


logger = logging.getLogger(__name__)


class SlidingWindowCounter:
    """Simple in-memory sliding window rate limiter."""

    def __init__(self, max_requests: int, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: MutableMapping[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        cutoff = now - self.window_seconds

        # Clean expired entries
        timestamps = self._requests[key]
        self._requests[key] = [ts for ts in timestamps if ts > cutoff]

        if len(self._requests[key]) >= self.max_requests:
            return False

        self._requests[key].append(now)
        return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        cutoff = now - self.window_seconds
        current = sum(1 for ts in self._requests.get(key, []) if ts > cutoff)
        return max(0, self.max_requests - current)


class AgentRateLimitMiddleware(BaseHTTPMiddleware):
    """Rate limits POST requests per agent_id using sliding window."""

    def __init__(self, app, enabled: bool = False, max_requests: int = 30):
        super().__init__(app)
        self.enabled = enabled
        self.limiter = SlidingWindowCounter(max_requests=max_requests)

    async def dispatch(self, request: Request, call_next):
        if not self.enabled:
            return await call_next(request)

        # Only rate limit POST requests
        if request.method != "POST":
            return await call_next(request)

        # Get agent_id from request state (set by auth middleware)
        agent_id = getattr(request.state, "agent_id", None)
        if not agent_id:
            return await call_next(request)

        if not self.limiter.is_allowed(agent_id):
            remaining = self.limiter.remaining(agent_id)
            logger.warning("Rate limit exceeded for agent %s", agent_id)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded. Try again later.",
                headers={
                    "X-RateLimit-Remaining": str(remaining),
                    "Retry-After": "60",
                },
            )

        response = await call_next(request)
        remaining = self.limiter.remaining(agent_id)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        return response
