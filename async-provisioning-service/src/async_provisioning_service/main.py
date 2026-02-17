import logging
import uvicorn
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from async_provisioning_service.api.auth import AgentAuthMiddleware, clear_registry_cache
from async_provisioning_service.api.rate_limit import AgentRateLimitMiddleware
from async_provisioning_service.api.routes import router
from async_provisioning_service.config import settings
from async_provisioning_service.db.database import init_db


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting async provisioning service...")
    init_db()
    logger.info("Database initialized")
    yield
    logger.info("Shutdown complete")


app = FastAPI(
    title="Async Provisioning Service",
    version="0.1.0",
    description=(
        "Asynchronous VM provisioning for a multi-agent compute marketplace.\n\n"
        "## Authentication\n\n"
        "POST requests require an **ERC-8004 agent identity** header:\n\n"
        "```\nX-Agent-ID: eip155:<chain_id>:0x<address>:<token_id>\n```\n\n"
        "GET requests accept the header optionally for agent-scoped filtering.\n"
        "`/health`, `/docs`, and `/redoc` bypass authentication entirely.\n\n"
        "When auth is **disabled** (`ENABLE_AUTH=false`), all requests are allowed "
        "but the agent ID is still extracted if provided.\n\n"
        "## Job Lifecycle\n\n"
        "```\n"
        "queued ──► running ──► succeeded\n"
        "              ├──► failed  (non-retryable or max retries exceeded)\n"
        "              └──► queued  (retryable — re-enqueued with backoff)\n"
        "queued ──► cancelled  (user-initiated)\n"
        "running ──► cancelled (user-initiated, SIGTERM sent)\n"
        "```\n"
    ),
    openapi_tags=[
        {
            "name": "provisioning",
            "description": "Submit, query, and cancel VM provisioning jobs.",
        },
        {
            "name": "health",
            "description": "Liveness probe for the API server.",
        },
    ],
    lifespan=lifespan,
)

app.add_middleware(
    AgentRateLimitMiddleware,
    enabled=settings.enable_rate_limiting,
    max_requests=settings.rate_limit_requests_per_minute,
)

app.add_middleware(
    AgentAuthMiddleware,
    registry_url=settings.registry_url,
    enabled=settings.enable_auth,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.post("/admin/cache/clear", tags=["admin"])
async def admin_clear_cache(x_admin_secret: str = Header(..., alias="X-Admin-Secret")):
    """Clear the agent registry lookup cache. Requires `X-Admin-Secret` header."""
    if not settings.admin_secret:
        raise HTTPException(status_code=501, detail="Admin secret not configured")
    if x_admin_secret != settings.admin_secret:
        raise HTTPException(status_code=403, detail="Invalid admin secret")
    count = clear_registry_cache()
    return {"cleared": count, "message": f"Registry cache cleared ({count} entries removed)"}


if __name__ == "__main__":
    uvicorn.run(
        "async_provisioning_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
