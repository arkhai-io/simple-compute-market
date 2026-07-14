from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from compute_provisioning.app import (
    ComputeProvisioningAppConfig,
    ComputeProvisioningMiddlewareMount,
    ComputeProvisioningRouterMount,
    build_compute_provisioning_app,
)
from compute_provisioning.startup import (
    start_compute_provisioning_runtime,
    stop_compute_provisioning_runtime,
)

import app_runtime
import container as _container_module
from container import container
from config import settings
from middleware.auth import StorefrontAuthMiddleware
from middleware.rate_limit import AgentRateLimitMiddleware


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
from controllers.leases_controller import AdminLeasesController, LeasesController   # noqa: E402
from controllers.bare_metal_leases_controller import BareMetalLeasesController  # noqa: E402
from market_site.router import make_capacity_router  # noqa: E402



@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting provisioning service...")

    runtime = await start_compute_provisioning_runtime(
        startup_steps=app_runtime.startup_steps(),
        background_tasks=app_runtime.background_tasks,
        logger=logger,
    )

    try:
        yield
    finally:
        logger.info("Shutdown initiated...")
        await stop_compute_provisioning_runtime(
            runtime,
            shutdown_steps=app_runtime.shutdown_steps(),
            logger=logger,
        )
        logger.info("Shutdown complete")


PROVISIONING_DESCRIPTION = (
    "Asynchronous VM provisioning for a multi-agent compute marketplace.\n\n"
    "## Authentication\n\n"
    "The service is an internal dependency of a single storefront. When an\n"
    "admin key is configured, every non-health request must present it:\n\n"
    "```\nX-Admin-Key: <admin_api_key>\n```\n\n"
    "This is the same shared secret the provisioning→storefront callback\n"
    "uses, so the link can cross an untrusted network. `/health`, `/docs`,\n"
    "and `/redoc` bypass authentication entirely.\n\n"
    "## Job lifecycle\n\n"
    "```\n"
    "queued --> running --> succeeded\n"
    "              +-> failed  (non-retryable or max retries exceeded)\n"
    "              +-> queued  (retryable -- re-enqueued with backoff)\n"
    "queued --> cancelled  (user-initiated)\n"
    "running --> cancelled (user-initiated, SIGTERM sent)\n"
    "```\n"
)

PROVISIONING_OPENAPI_TAGS = [
    {
        "name": "vms",
        "description": (
            "Admin/operator VM operations (create, start, shutdown, etc.). "
            "Tenant self-service requires lease-owner authorization and is "
            "not exposed by this controller."
        ),
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
        "description": (
            "VM lease lifecycle — register, query, terminate, release oversight, "
            "and admin repair actions."
        ),
    },
    {
        "name": "bare-metal",
        "description": (
            "Bare-metal domain adapter — register and query SSH-access leases "
            "against site allocations."
        ),
    },
    {
        "name": "admin",
        "description": "Admin-only repair operations for exceptional lifecycle states.",
    },
    {
        "name": "capacity",
        "description": (
            "Site-authority capacity ledger — snapshot, probe, "
            "reserve/commit/release, and the versioned event feed."
        ),
    },
]

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
#   /api/v1/hosts/{host}/vms/*       <- direct VM admin/operator lifecycle
#   /api/v1/leases/*                 <- market-managed lease lifecycle
#   /api/v1/bare-metal/leases/*      <- bare-metal domain lease adapter
# ---------------------------------------------------------------------------
app = build_compute_provisioning_app(
    config=ComputeProvisioningAppConfig(
        title="Provisioning Service",
        version="0.2.0",
        description=PROVISIONING_DESCRIPTION,
        openapi_tags=PROVISIONING_OPENAPI_TAGS,
    ),
    lifespan=lifespan,
    # Middleware order matches the previous direct add_middleware calls.
    middlewares=(
        ComputeProvisioningMiddlewareMount(
            AgentRateLimitMiddleware,
            {
                "enabled": settings.enable_rate_limiting,
                "max_requests": settings.rate_limit_requests_per_minute,
            },
        ),
        ComputeProvisioningMiddlewareMount(
            StorefrontAuthMiddleware,
            {"admin_key": str(settings.storefront_admin_key or "")},
        ),
        ComputeProvisioningMiddlewareMount(
            CORSMiddleware,
            {
                "allow_origins": ["*"],
                "allow_credentials": True,
                "allow_methods": ["*"],
                "allow_headers": ["*"],
            },
        ),
    ),
    routers=(
        ComputeProvisioningRouterMount(SystemController.make_health_router()),
        ComputeProvisioningRouterMount(SystemController.make_system_router(), "/api/v1"),
        ComputeProvisioningRouterMount(AnsibleJobsController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(HostController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(VmController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(LeasesController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(BareMetalLeasesController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(AdminLeasesController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(
            make_capacity_router(
                lambda: _container_module.resolved_capacity_ledger_service
            ),
            "/api/v1",
        ),
    ),
)

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
