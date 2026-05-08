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
from controllers.leases_controller import LeasesController   # noqa: E402


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
    _container_module.resolved_host_service = container.host_service()
    _container_module.resolved_lease_service = container.lease_service()
    _container_module.resolved_lease_lifecycle_service = container.lease_lifecycle_service()
    _container_module.resolved_lease_watchdog = container.lease_watchdog()

    # ------------------------------------------------------------------
    # Inventory seeding — runs once at startup if the hosts table is empty.
    #
    # Source priority:
    #   1. inventory_ini setting (non-empty string) — used by the Helm chart,
    #      injected via the provisioning-secrets config profile.
    #   2. inventory_path on disk — used by the Docker profile, which points
    #      at the IAC hosts file baked into the image.
    #
    # Seeding is skipped when the hosts table already has rows, so that
    # operator changes made via the API (POST /hosts, PUT /hosts/{host}, etc.)
    # are not overwritten on pod restart.  To force a re-seed, use
    # POST /api/v1/hosts/import which always upserts regardless of table state.
    # ------------------------------------------------------------------
    host_service = _container_module.resolved_host_service
    existing_hosts = host_service.list_hosts(enabled_only=False)
    if existing_hosts:
        logger.info("Inventory seeding: skipped — %d host(s) already registered", len(existing_hosts))
    else:
        inventory_ini = str(getattr(settings, "inventory_ini", "") or "").strip()
        inventory_path = getattr(settings, "resolved_inventory_path", None)

        ini_text: str | None = None
        source: str | None = None

        if inventory_ini:
            ini_text = inventory_ini
            source = "inventory_ini setting (provisioning-secrets profile)"
        elif inventory_path and inventory_path.exists():
            try:
                ini_text = inventory_path.read_text(encoding="utf-8")
                source = str(inventory_path)
            except OSError as exc:
                logger.warning("Inventory seeding: could not read %s: %s", inventory_path, exc)

        if ini_text:
            try:
                seeded = host_service.seed_from_ini(ini_text)
                logger.info("Inventory seeding: registered %d host(s) from %s", len(seeded), source)
            except Exception as exc:
                logger.error("Inventory seeding failed (source: %s): %s", source, exc)
        else:
            logger.info("Inventory seeding: no inventory source configured — starting with empty host registry")

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

    # Lease watchdog — only started when enabled in config (default: true).
    watchdog_task = None
    watchdog_enabled = bool(getattr(settings, "lease_watchdog_enabled", True))
    if watchdog_enabled:
        watchdog_task = asyncio.create_task(
            _container_module.resolved_lease_watchdog.run(),
            name="lease-watchdog",
        )
        logger.info(
            "Lease watchdog started (interval=%ds grace=%ds)",
            getattr(settings, "lease_watchdog_poll_interval_seconds", 60),
            getattr(settings, "lease_watchdog_grace_period_seconds", 300),
        )
    else:
        logger.info("Lease watchdog disabled (lease_watchdog_enabled=false)")

    yield

    logger.info("Shutdown initiated...")
    processing_task.cancel()
    try:
        await processing_task
    except asyncio.CancelledError:
        pass

    if watchdog_task is not None:
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass

    container.shutdown_resources()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Provisioning Service",
    version="0.2.0",
    description=(
        "Asynchronous VM provisioning for a multi-agent compute marketplace.\n\n"
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
            "description": "KVM host registry — CRUD, capacity checks, and connectivity tests.",
        },
        {
            "name": "jobs",
            "description": "Query and cancel Ansible jobs.",
        },
        {
            "name": "system",
            "description": "Health, version, and Ansible readiness diagnostics.",
        },
        {
            "name": "leases",
            "description": "VM lease lifecycle — register, query, and cancel leases.",
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
#   /health                          <- bare liveness probe (no prefix)
#   /api/v1/system/health            <- versioned alias
#   /api/v1/system/version
#   /api/v1/system/ansible/readiness
#   /api/v1/jobs/*                   <- job read + cancel
#   /api/v1/hosts/*                  <- host registry CRUD, capacity, connectivity
#   /api/v1/hosts/{host}/vms/*       <- VM lifecycle (VmController composes here)
# ---------------------------------------------------------------------------
app.include_router(SystemController.make_health_router())                          # /health
app.include_router(SystemController.make_system_router(), prefix="/api/v1")        # /api/v1/system/*
app.include_router(AnsibleJobsController.make_router(), prefix="/api/v1")          # /api/v1/jobs/*
app.include_router(HostController.make_router(), prefix="/api/v1")                 # /api/v1/hosts/*
app.include_router(VmController.make_router(), prefix="/api/v1")                   # /api/v1/hosts/{host}/vms/*
app.include_router(LeasesController.make_router(), prefix="/api/v1")               # /api/v1/leases/*

# Test controller — only mounted when mock profile is active.
# Never present in production or staging.
import os as _os
_active_profiles = [p.strip() for p in _os.environ.get("ACTIVE_PROFILES", "").split(",") if p.strip()]
if "mock" in _active_profiles:
    from controllers.test_controller import make_router as _make_test_router
    app.include_router(_make_test_router())                                         # /test/*
    logger.info("Test controller mounted at /test/* (mock profile active)")

# Expose the container on the app instance for integration test overrides.
app.container = container  # type: ignore[attr-defined]


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )