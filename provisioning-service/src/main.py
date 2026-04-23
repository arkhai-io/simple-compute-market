from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import container as _container_module
from container import Container, container
from config import settings
from db.database import init_db
from middleware.auth import AgentAuthMiddleware
from middleware.rate_limit import AgentRateLimitMiddleware
from services.async_job_queue import AsyncJobQueue


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Controller imports must come AFTER container.py is imported so the module-level
# container instance exists before @cbv decorators run.
from controllers.system_controller import SystemController   # noqa: E402
from controllers.jobs_controller import AnsibleJobsController  # noqa: E402
from controllers.hosts_controller import HostController      # noqa: E402
from controllers.vms_controller import VmController          # noqa: E402


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting provisioning service...")

    # Apply ANSIBLE_CONFIG from the active profile if configured.
    ansible_cfg = str(getattr(settings, "ansible_cfg", "") or "").strip()
    if ansible_cfg:
        os.environ["ANSIBLE_CONFIG"] = ansible_cfg
        logger.info("ANSIBLE_CONFIG set to %s", ansible_cfg)

    container.init_resources()
    init_db(container.db_engine())
    logger.info("Database initialised")

    # Resolve services as plain module-level variables so controllers
    # can retrieve them via a simple lambda, avoiding any provider
    # machinery on the request path (prevents asyncio.get_event_loop()
    # errors in AnyIO worker threads).
    _container_module.resolved_job_service = container.job_service()
    _container_module.resolved_session_factory = container.session_factory()
    _container_module.resolved_ansible_service = container.ansible_service()
    _container_module.resolved_system_service = container.system_service()

    # AsyncJobQueue is a plain object; instantiate inside the running event loop.
    job_queue = AsyncJobQueue(max_concurrent=settings.max_concurrent_jobs)
    _container_module.resolved_job_queue = job_queue

    processing_task = asyncio.create_task(
        job_queue.start(_container_module.resolved_job_service._process_job),
        name="job-processing-loop",
    )
    logger.info(
        "Job processing loop started (max_concurrent=%d)", settings.max_concurrent_jobs
    )

    yield

    logger.info("Shutdown initiated...")
    processing_task.cancel()
    try:
        await processing_task
    except asyncio.CancelledError:
        pass

    container.shutdown_resources()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Provisioning Service",
    version="0.2.0",
    description=(
        "Asynchronous VM provisioning for a multi-agent compute marketplace.\n\n"
        "## URL structure\n\n"
        "VM operations are scoped to a KVM host in the URL:\n\n"
        "```\n"
        "POST   /api/v1/hosts/{host}/vms                  Create a VM\n"
        "GET    /api/v1/hosts/{host}/vms                  List VMs (async)\n"
        "POST   /api/v1/hosts/{host}/vms/{vm}/start\n"
        "POST   /api/v1/hosts/{host}/vms/{vm}/shutdown\n"
        "POST   /api/v1/hosts/{host}/vms/{vm}/reboot\n"
        "POST   /api/v1/hosts/{host}/vms/{vm}/destroy\n"
        "POST   /api/v1/hosts/{host}/vms/{vm}/undefine\n"
        "GET    /api/v1/hosts/{host}/vms/{vm}/monitor     Stats snapshot (async)\n"
        "POST   /api/v1/hosts/{host}/vms/{vm}/reset-password\n"
        "POST   /api/v1/hosts/{host}/vms/{vm}/expiry      Schedule expiry\n"
        "DELETE /api/v1/hosts/{host}/vms/{vm}/expiry      Cancel expiry\n"
        "\n"
        "GET    /api/v1/hosts                             List inventory hosts\n"
        "GET    /api/v1/hosts/{host}/capacity             Host resource check (async)\n"
        "GET    /api/v1/hosts/{host}/connectivity         Ansible ping\n"
        "```\n\n"
        "## Polling\n\n"
        "All job-creating endpoints return "
        "`{\"job_id\": \"...\", \"status\": \"queued\"}`. "
        "Poll `GET /api/v1/jobs/{job_id}` for status updates.\n\n"
        "## Authentication\n\n"
        "POST/DELETE requests require an **ERC-8004 agent identity** header:\n\n"
        "```\nX-Agent-ID: eip155:<chain_id>:0x<address>:<token_id>\n```\n\n"
        "GET requests accept the header optionally for agent-scoped filtering.\n"
        "`/health`, `/docs`, and `/redoc` bypass authentication entirely.\n\n"
        "## Job lifecycle\n\n"
        "```\n"
        "queued --> running --> succeeded\n"
        "              +-> failed  (non-retryable or max retries exceeded)\n"
        "              +-> queued  (retryable -- re-enqueued with backoff)\n"
        "queued --> cancelled  (user-initiated)\n"
        "running --> cancelled (user-initiated, SIGTERM sent)\n"
        "```\n"
    ),
    openapi_tags=[
        {
            "name": "vms",
            "description": "VM lifecycle operations (create, start, shutdown, etc.).",
        },
        {
            "name": "hosts",
            "description": "KVM host inventory, capacity checks, and connectivity tests.",
        },
        {
            "name": "jobs",
            "description": "Query and cancel Ansible jobs.",
        },
        {
            "name": "system",
            "description": "Health, version, and Ansible readiness diagnostics.",
        },
    ],
    lifespan=lifespan,
)

# Middleware (outermost applied last)
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

# ---------------------------------------------------------------------------
# Routers
#
# URL hierarchy:
#   /health                          ← bare liveness probe (no prefix)
#   /api/v1/system/health            ← versioned alias
#   /api/v1/system/version
#   /api/v1/system/ansible/readiness
#   /api/v1/jobs/*                   ← job read + cancel
#   /api/v1/hosts/*                  ← host inventory, capacity, connectivity
#   /api/v1/hosts/{host}/vms/*       ← VM lifecycle (VmController composes here)
#
# VmController and HostController are registered independently at /api/v1.
# Their prefixes (/hosts/{host}/vms and /hosts) assemble the full hierarchy
# explicitly in this file rather than via router nesting.
# ---------------------------------------------------------------------------
app.include_router(SystemController.make_health_router())                          # /health
app.include_router(SystemController.make_system_router(), prefix="/api/v1")        # /api/v1/system/*
app.include_router(AnsibleJobsController.make_router(), prefix="/api/v1")          # /api/v1/jobs/*
app.include_router(HostController.make_router(), prefix="/api/v1")                 # /api/v1/hosts/*
app.include_router(VmController.make_router(), prefix="/api/v1")                   # /api/v1/hosts/{host}/vms/*

# Expose the container on the app instance for integration test overrides.
app.container = container  # type: ignore[attr-defined]


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )