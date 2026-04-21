from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Container must be imported and instantiated before the controllers so that
# wiring_config can patch @inject decorators when the controller modules load.
from dependency_injector import providers
import container as _container_module
from container import Container, container
from config import settings
from db.database import init_db
from middleware.auth import AgentAuthMiddleware
from middleware.rate_limit import AgentRateLimitMiddleware


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Controller imports must come AFTER container.py is imported (module-level
# container instance is created there).
from controllers.health_controller import HealthController  # noqa: E402
from controllers.jobs_controller import AnsibleJobsController  # noqa: E402
from controllers.ansible_controller import AnsibleController  # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting provisioning service...")

    # Apply ANSIBLE_CONFIG from the active profile if configured.
    # The ansible-playbook subprocess inherits os.environ, so this must be set
    # before the first playbook run.  The docker profile sets this to the
    # bundled ansible.cfg; in Kubernetes it comes from the ConfigMap.
    ansible_cfg = str(getattr(settings, "ansible_cfg", "") or "").strip()
    if ansible_cfg:
        os.environ["ANSIBLE_CONFIG"] = ansible_cfg
        logger.info("ANSIBLE_CONFIG set to %s", ansible_cfg)

    # Initialise Resource providers (creates the asyncio.Queue inside the
    # running event loop — must happen before any Singleton that depends on it
    # is first accessed).
    await container.init_resources()

    # Create database tables.
    init_db(container.db_engine())
    logger.info("Database initialised")

    # Start the background job processing loop as a long-lived asyncio task.
    # This replaces the former separate worker process.
    # Resolve all services that depend on the job_queue Resource while we are
    # still inside the async lifespan context (event loop available).
    # Store them as plain module-level variables so controllers can retrieve
    # them via a simple attribute lookup — no dependency-injector provider
    # machinery is invoked on the request path, avoiding the
    # asyncio.get_event_loop() call that fails in AnyIO worker threads.
    _container_module.resolved_job_service = await container.job_service.async_()
    _container_module.resolved_session_factory = container.session_factory()
    _container_module.resolved_ansible_service = container.ansible_service()

    processing_task = asyncio.create_task(
        _container_module.resolved_job_service.start_processing_loop(),
        name="job-processing-loop",
    )
    logger.info("Job processing loop started")

    yield

    logger.info("Shutdown initiated...")
    processing_task.cancel()
    try:
        await processing_task
    except asyncio.CancelledError:
        pass

    await container.shutdown_resources()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Async Provisioning Service",
    version="0.1.0",
    description=(
        "Asynchronous VM provisioning for a multi-agent compute marketplace.\n\n"
        "All provisioning endpoints are versioned under `/api/v1/jobs`.\n\n"
        "## Authentication\n\n"
        "POST requests require an **ERC-8004 agent identity** header:\n\n"
        "```\nX-Agent-ID: eip155:<chain_id>:0x<address>:<token_id>\n```\n\n"
        "GET requests accept the header optionally for agent-scoped filtering.\n"
        "`/health`, `/docs`, and `/redoc` bypass authentication entirely.\n\n"
        "When auth is **disabled** (`PROVISIONING_ENABLE_AUTH=false`), all "
        "requests are allowed but the agent ID is still extracted if provided.\n\n"
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
            "name": "jobs",
            "description": "Submit, query, and cancel VM provisioning jobs.",
        },
        {
            "name": "ansible",
            "description": "Inspect inventory and test host connectivity.",
        },
        {
            "name": "health",
            "description": "Liveness probe for the API server.",
        },
    ],
    lifespan=lifespan,
)

# Middleware (order matters — outermost middleware is applied last).
app.add_middleware(
    AgentRateLimitMiddleware,
    enabled=settings.enable_rate_limiting,
    max_requests=settings.rate_limit_requests_per_minute,
)
app.add_middleware(
    AgentAuthMiddleware,
    registry_url=str(settings.registry_url or ""),
    enabled=settings.enable_auth,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(HealthController.make_router())
app.include_router(AnsibleJobsController.make_router(), prefix="/api/v1")
app.include_router(AnsibleController.make_router(), prefix="/api/v1")

# Make the container accessible on the app instance for testing.
app.container = container  # type: ignore[attr-defined]


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )