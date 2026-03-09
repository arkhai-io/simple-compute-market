import logging
import re
from typing import Optional
from urllib.parse import quote

import httpx
from cachetools import TTLCache
from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from async_provisioning_service.config import settings


logger = logging.getLogger(__name__)

ERC8004_PATTERN = re.compile(r"^eip155:\d+:0x[0-9a-fA-F]{40}:\d+$")

# Caches both positive and negative registry lookups
_registry_cache: TTLCache = TTLCache(
    maxsize=settings.registry_cache_max_size,
    ttl=settings.registry_cache_ttl_seconds,
)

EXCLUDED_PATHS = frozenset({"/health", "/docs", "/openapi.json", "/redoc"})


def validate_erc8004_agent_id(agent_id: str) -> bool:
    """Validate that an agent ID matches ERC-8004 format."""
    return bool(ERC8004_PATTERN.match(agent_id))


async def verify_agent_with_registry(registry_url: str, agent_id: str) -> bool:
    """Verify agent against the registry API. Fails open on errors."""
    cached = _registry_cache.get(agent_id)
    if cached is not None:
        return cached

    try:
        encoded_id = quote(agent_id, safe="")
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{registry_url}/agents/{encoded_id}")

        if response.status_code == 200:
            data = response.json()
            is_valid = data.get("status") == "healthy" or data.get("exists", False)
            _registry_cache[agent_id] = is_valid
            return is_valid
        elif response.status_code == 404:
            _registry_cache[agent_id] = False
            logger.warning("Agent %s not found in registry", agent_id)
            return False
        else:
            logger.warning(
                "Registry returned unexpected status %d for agent %s, failing open",
                response.status_code,
                agent_id,
            )
            return True

    except Exception as exc:
        logger.warning("Registry verification failed for %s (failing open): %s", agent_id, exc)
        return True


class AgentAuthMiddleware(BaseHTTPMiddleware):
    """POST requests require a valid ERC-8004 X-Agent-ID. GET requests extract it optionally."""

    def __init__(self, app, registry_url: Optional[str] = None, enabled: bool = True):
        super().__init__(app)
        self.registry_url = registry_url
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXCLUDED_PATHS:
            return await call_next(request)

        if not self.enabled:
            agent_id = request.headers.get("X-Agent-ID")
            if agent_id and validate_erc8004_agent_id(agent_id):
                request.state.agent_id = agent_id
            else:
                request.state.agent_id = None
            return await call_next(request)

        if request.method != "POST":
            agent_id = request.headers.get("X-Agent-ID")
            if agent_id and validate_erc8004_agent_id(agent_id):
                request.state.agent_id = agent_id
            else:
                request.state.agent_id = None
            return await call_next(request)

        agent_id = request.headers.get("X-Agent-ID")

        if not agent_id:
            logger.warning("POST to %s missing X-Agent-ID header", request.url.path)
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Missing X-Agent-ID header"},
                headers={"WWW-Authenticate": "Agent"},
            )

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

        if self.registry_url:
            is_valid = await verify_agent_with_registry(self.registry_url, agent_id)
            if not is_valid:
                return JSONResponse(
                    status_code=status.HTTP_403_FORBIDDEN,
                    content={"detail": "Agent not registered or unhealthy"},
                )

        request.state.agent_id = agent_id
        logger.debug("Authenticated request from agent: %s", agent_id)

        return await call_next(request)
