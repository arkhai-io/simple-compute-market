"""
Authentication middleware for async provisioning service.

Validates agent identity using ERC-8004 format and verifies agents
against the registry API with TTL caching.
"""

import logging
import re
from typing import Optional
from urllib.parse import quote

import httpx
from cachetools import TTLCache
from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from async_provisioning_service.config import settings


logger = logging.getLogger(__name__)

# ERC-8004 agent ID format: eip155:<chain_id>:0x<40_hex_chars>:<token_id>
ERC8004_PATTERN = re.compile(r"^eip155:\d+:0x[0-9a-fA-F]{40}:\d+$")

# TTL cache for registry lookups (both positive and negative)
_registry_cache: TTLCache = TTLCache(
    maxsize=settings.registry_cache_max_size,
    ttl=settings.registry_cache_ttl_seconds,
)

# Paths that skip authentication entirely
EXCLUDED_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


def validate_erc8004_agent_id(agent_id: str) -> bool:
    """Validate that an agent ID matches ERC-8004 format.

    Format: eip155:<chain_id>:0x<40_hex_chars>:<token_id>
    Example: eip155:31337:0x5FbDB2315678afecb367f032d93F642f64180aa3:1
    """
    return bool(ERC8004_PATTERN.match(agent_id))


async def verify_agent_with_registry(registry_url: str, agent_id: str) -> bool:
    """Verify an agent ID against the registry API.

    Uses TTL cache to avoid hammering the registry. Caches both positive
    and negative results. Fails open on registry errors (transient issues
    should not block provisioning).

    Returns:
        True if agent is verified or registry is unavailable (fail-open).
        False only if registry explicitly says agent is not found/unhealthy.
    """
    # Check cache first
    cached = _registry_cache.get(agent_id)
    if cached is not None:
        return cached

    try:
        encoded_id = quote(agent_id, safe="")
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{registry_url}/agents/{encoded_id}")

        if response.status_code == 200:
            data = response.json()
            # Agent must exist and be healthy
            is_valid = data.get("status") == "healthy" or data.get("exists", False)
            _registry_cache[agent_id] = is_valid
            return is_valid
        elif response.status_code == 404:
            # Agent explicitly not found
            _registry_cache[agent_id] = False
            logger.warning("Agent %s not found in registry", agent_id)
            return False
        else:
            # Unexpected status - fail open
            logger.warning(
                "Registry returned unexpected status %d for agent %s, failing open",
                response.status_code,
                agent_id,
            )
            return True

    except Exception as exc:
        # Registry unavailable - fail open
        logger.warning("Registry verification failed for %s (failing open): %s", agent_id, exc)
        return True


class AgentAuthMiddleware(BaseHTTPMiddleware):
    """Middleware to validate agent identity via X-Agent-ID header.

    POST requests require a valid ERC-8004 agent ID. If a registry URL is
    configured, the agent is verified against it (with TTL caching).

    GET requests extract agent_id if present (for scoped filtering) but
    do not require it. Excluded paths skip auth entirely.
    """

    def __init__(self, app, registry_url: Optional[str] = None, enabled: bool = True):
        super().__init__(app)
        self.registry_url = registry_url
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        # Skip excluded paths
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        # Skip if auth is disabled
        if not self.enabled:
            # Still extract agent_id if provided (for optional scoping)
            agent_id = request.headers.get("X-Agent-ID")
            if agent_id and validate_erc8004_agent_id(agent_id):
                request.state.agent_id = agent_id
            else:
                request.state.agent_id = None
            return await call_next(request)

        # GET requests: extract agent_id if present but don't require it
        if request.method != "POST":
            agent_id = request.headers.get("X-Agent-ID")
            if agent_id and validate_erc8004_agent_id(agent_id):
                request.state.agent_id = agent_id
            else:
                request.state.agent_id = None
            return await call_next(request)

        # POST requests: require valid X-Agent-ID
        agent_id = request.headers.get("X-Agent-ID")

        if not agent_id:
            logger.warning("POST to %s missing X-Agent-ID header", request.url.path)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing X-Agent-ID header"},
                headers={"WWW-Authenticate": "Agent"},
            )

        # Validate ERC-8004 format
        if not validate_erc8004_agent_id(agent_id):
            logger.warning("Invalid ERC-8004 agent ID format: %s", agent_id)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": (
                        "Invalid agent ID format. Must be ERC-8004 format: "
                        "eip155:<chain_id>:0x<address>:<token_id>"
                    )
                },
                headers={"WWW-Authenticate": "Agent"},
            )

        # Verify against registry if configured
        if self.registry_url:
            is_valid = await verify_agent_with_registry(self.registry_url, agent_id)
            if not is_valid:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Agent not registered or unhealthy"},
                )

        # Store agent ID in request state
        request.state.agent_id = agent_id
        logger.debug("Authenticated request from agent: %s", agent_id)

        return await call_next(request)
