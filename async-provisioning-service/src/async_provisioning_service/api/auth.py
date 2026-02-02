"""
Authentication middleware for async provisioning service.

Validates agent ID from HTTP headers to ensure only authorized agents
can submit provisioning jobs.
"""

import logging
from typing import Optional

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware


logger = logging.getLogger(__name__)


class AgentAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware to validate agent ID from X-Agent-ID header.

    This middleware:
    1. Extracts the X-Agent-ID header from requests
    2. Validates that the agent ID is a valid Python identifier
    3. Optionally verifies the agent against a registry API (future enhancement)

    For now, this provides basic validation to prevent injection attacks
    and ensures consistent agent identification across requests.
    """

    def __init__(self, app, registry_url: Optional[str] = None, enabled: bool = True):
        """
        Initialize the authentication middleware.

        Args:
            app: FastAPI application
            registry_url: Optional URL of the agent registry API for verification
            enabled: Whether to enable authentication (default: True)
        """
        super().__init__(app)
        self.registry_url = registry_url
        self.enabled = enabled

    async def dispatch(self, request: Request, call_next):
        # Skip authentication for health check and docs endpoints
        if request.url.path in ("/health", "/docs", "/openapi.json", "/redoc"):
            return await call_next(request)

        # Skip if authentication is disabled
        if not self.enabled:
            return await call_next(request)

        # Skip authentication for GET requests (status, logs)
        # Only enforce on POST requests (submit, cancel)
        if request.method != "POST":
            return await call_next(request)

        # Extract agent ID from header
        agent_id = request.headers.get("X-Agent-ID")

        if not agent_id:
            logger.warning("Request to %s missing X-Agent-ID header", request.url.path)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Agent-ID header",
                headers={"WWW-Authenticate": "Agent"},
            )

        # Validate agent ID format (must be valid Python identifier)
        if not agent_id.isidentifier():
            logger.warning("Invalid agent ID format: %s", agent_id)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid agent ID format. Must be a valid Python identifier.",
                headers={"WWW-Authenticate": "Agent"},
            )

        # Future enhancement: verify agent against registry API
        # if self.registry_url:
        #     is_valid = await verify_agent_with_registry(self.registry_url, agent_id)
        #     if not is_valid:
        #         logger.warning("Agent ID %s not found in registry", agent_id)
        #         raise HTTPException(
        #             status_code=status.HTTP_403_FORBIDDEN,
        #             detail="Agent not registered",
        #         )

        # Store agent ID in request state for use in route handlers
        request.state.agent_id = agent_id
        logger.debug("Authenticated request from agent: %s", agent_id)

        return await call_next(request)


def validate_agent_id(agent_id: str) -> bool:
    """
    Validate that an agent ID is a valid Python identifier.

    Args:
        agent_id: Agent identifier to validate

    Returns:
        True if valid, False otherwise
    """
    return agent_id.isidentifier()
