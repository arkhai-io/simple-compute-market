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

from compute_provisioning_service import app_runtime
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.container import container
from compute_provisioning_service.config import settings
from compute_provisioning_service.middleware.auth import StorefrontAuthMiddleware
from compute_provisioning_service.middleware.rate_limit import AgentRateLimitMiddleware
from compute_provisioning_service.services.capacity_inventory import (
    load_capacity_resource_inventory,
)


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Adapter router imports come AFTER container.py so controller decorators can
# resolve the shared composition module without creating an import cycle.
from vm_provisioning_adapter.routers import vm_mock_router, vm_router_mounts  # noqa: E402
from bare_metal_provisioning_adapter.routers import bare_metal_router_mounts  # noqa: E402
from compute_provisioning_service.controllers.compute_contract_controller import ComputeContractController  # noqa: E402
from compute_provisioning_service.controllers.pools_controller import PoolController  # noqa: E402
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
            "against site reservations."
        ),
    },
    {
        "name": "admin",
        "description": "Admin-only repair operations for exceptional lifecycle states.",
    },
    {
        "name": "pools",
        "description": (
            "Resource pool registry — infrastructure routing/scheduling metadata. "
            "CRUD plus YAML import/validate."
        ),
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
#   /api/v1/pools/*                  <- resource pool registry (CRUD, import, validate)
# ---------------------------------------------------------------------------

def _capacity_resource_inventory() -> list[dict[str, object]]:
    ledger = _container_module.resolved_capacity_ledger_service
    if ledger is None:
        raise RuntimeError("capacity ledger is not initialized")
    return load_capacity_resource_inventory(
        container.session_factory(),
        capacity_resources=ledger.list_resources(),
    )


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
            {
                "admin_key": str(settings.storefront_admin_key or ""),
                "principal_keys": getattr(
                    settings,
                    "storefront_api_keys",
                    None,
                ),
            },
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
        *vm_router_mounts(),
        *bare_metal_router_mounts(),
        ComputeProvisioningRouterMount(ComputeContractController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(PoolController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(
            make_capacity_router(
                lambda: _container_module.resolved_capacity_ledger_service,
                get_resource_inventory=_capacity_resource_inventory,
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
    app.include_router(vm_mock_router())                                             # /test/*
    logger.info("Test controller mounted at /test/* (mock profile active)")

# Expose the container on the app instance for integration test overrides.
app.container = container  # type: ignore[attr-defined]


def run() -> None:
    """Run the supported compute provisioning API command."""
    uvicorn.run(
        "compute_provisioning_service.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    run()
