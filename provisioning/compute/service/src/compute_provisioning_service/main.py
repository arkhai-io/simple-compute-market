from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, Request
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

from market_identity import RotationRequest
from compute_provisioning_service import app_runtime
from compute_provisioning_service import container as _container_module
from compute_provisioning_service.container import container
from compute_provisioning_service.config import settings
from compute_provisioning_service.middleware.auth import ProvisioningAuthMiddleware
from compute_provisioning_service.middleware.rate_limit import AgentRateLimitMiddleware
from compute_provisioning_service.services.capacity_inventory import (
    load_capacity_pool_metadata,
    load_capacity_resource_inventory,
)
from compute_provisioning_service.route_table import assemble_service_route_table
from compute_provisioning_service.controllers.capacity_definitions_controller import CapacityDefinitionsController
from compute_provisioning_service.controllers.pools_controller import PoolController
from compute_provisioning_service.controllers.relays_controller import RelayController
from compute_provisioning_service.controllers.fulfillment_controller import FulfillmentController
from compute_provisioning_service.controllers.system_controller import make_system_routers
from compute_provisioning_service.services.system_status import SERVICE_VERSION
from compute_provisioning_service.controllers import (
    host_import_controller,
    hosts_controller,
    jobs_controller,
    leases_controller,
    test_jobs_controller,
)
from market_site.router import make_capacity_router
from vm_provisioning_adapter.routers import (
    vm_mock_router,
    vm_route_contracts,
    vm_router_mounts,
)
from bare_metal_provisioning_adapter.routers import (
    bare_metal_mock_router,
    bare_metal_route_contracts,
)


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)



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
    "The compute family's provisioning service: a site's capacity authority, "
    "resource pools, execution hosts, provisioning jobs, fulfillment, and lease "
    "lifecycle, executing through the domain adapters composed into it (VM and "
    "bare metal).\n\n"
    "## Authentication\n\n"
    "Every route but `/health`, `/docs`, and `/redoc` uses the scheme-tagged "
    "marketplace request signature v2 contract. A request is body-bound to a "
    "configured caller principal under the role it asserts, and each route "
    "admits the roles its contract names: the seller (a storefront) and the "
    "administrator, or the administrator alone. Responses are signed by the "
    "configured provisioning service principal.\n\n"
    "## Job lifecycle\n\n"
    "```\n"
    "queued --> running --> succeeded\n"
    "              +-> failed  (non-retryable or max retries exceeded)\n"
    "              +-> queued  (retryable -- re-enqueued with backoff)\n"
    "queued --> cancelled  (operator-initiated)\n"
    "running --> cancelled (operator-initiated; the job's executor stops it)\n"
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
        "description": (
            "Execution host registry — CRUD, enable and disable, and "
            "connectivity checks over each host's typed connection."
        ),
    },
    {
        "name": "jobs",
        "description": "Query and cancel provisioning jobs, whichever executor runs them.",
    },
    {
        "name": "system",
        "description": "Health, status, version, and worker controls.",
    },
    {
        "name": "leases",
        "description": (
            "Lease lifecycle for every offering mode — register, query, terminate, "
            "release oversight, and admin repair actions."
        ),
    },
    {
        "name": "bare-metal",
        "description": (
            "Bare-metal mock controls, mounted only under the mock profile."
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
#   /api/v1/system/status            <- operator status, execution, components
#   /api/v1/jobs/*                   <- job read + cancel
#   /api/v1/hosts/*                  <- host registry CRUD, capacity, connectivity
#   /api/v1/hosts/{host}/vms/*       <- direct VM admin/operator lifecycle
#   /api/v1/contract/leases/*        <- lease lifecycle, every offering mode
#   /api/v1/pools/*                  <- resource pool registry (CRUD, import, validate)
# ---------------------------------------------------------------------------

def _inventory_views():
    views = _container_module.resolved_inventory_views
    if views is None:
        raise RuntimeError("inventory views are not composed")
    return views


def _capacity_resource_inventory() -> list[dict[str, object]]:
    ledger = _container_module.resolved_capacity_ledger_service
    if ledger is None:
        raise RuntimeError("capacity ledger is not initialized")
    return load_capacity_resource_inventory(ledger.list_resources(), _inventory_views())


def _capacity_pool_directory() -> dict[str, dict[str, object]]:
    return load_capacity_pool_metadata(container.session_factory(), _inventory_views())


# The service's own system routes, and each adapter's routes, are mounted when
# the app is built and reach collaborators the lifespan composes later, so each
# takes accessors read per request.
_health_router, _system_router = make_system_routers(
    status_service=lambda: _container_module.resolved_system_status_service,
    lease_lifecycle=lambda: _container_module.resolved_lease_lifecycle_service,
    convergence_watchdog=lambda: _container_module.resolved_fulfillment_convergence_watchdog,
)


def _vm_mock_router():
    return vm_mock_router(
        vm_runner=lambda: _container_module.resolved_ansible_service,
        host_authority=lambda: _container_module.resolved_host_authority,
    )


def _bare_metal_mock_router():
    return bare_metal_mock_router(
        mock_executor=lambda: _container_module.resolved_bare_metal_mock_executor,
        host_authority=lambda: _container_module.resolved_host_authority,
    )



# Every route this service mounts, from every owner that declares one: what the
# authentication middleware admits. Each adapter contributes its declarations
# beside its routers.
provisioning_route_table = assemble_service_route_table(
    vm_route_contracts(),
    bare_metal_route_contracts(),
)

app = build_compute_provisioning_app(
    config=ComputeProvisioningAppConfig(
        title="Provisioning Service",
        version=SERVICE_VERSION,
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
            ProvisioningAuthMiddleware,
            {
                "identity_provider": container.identity_context,
                "replay_store_provider": container.provisioning_replay_store,
                "principal_authority_provider": container.principal_authority,
                "route_table": provisioning_route_table,
                "max_timestamp_skew": int(
                    getattr(settings, "identity_max_timestamp_skew_seconds", 300)
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
        ComputeProvisioningRouterMount(_health_router),
        ComputeProvisioningRouterMount(_system_router, "/api/v1"),
        *vm_router_mounts(
            vm_operations=lambda: _container_module.resolved_vm_operations_service,
            host_operations=lambda: _container_module.resolved_host_operations_service,
        ),
        ComputeProvisioningRouterMount(jobs_controller.router, "/api/v1"),
        ComputeProvisioningRouterMount(host_import_controller.router, "/api/v1"),
        ComputeProvisioningRouterMount(hosts_controller.router, "/api/v1"),
        ComputeProvisioningRouterMount(leases_controller.router, "/api/v1"),
        ComputeProvisioningRouterMount(PoolController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(CapacityDefinitionsController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(RelayController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(FulfillmentController.make_router(), "/api/v1"),
        ComputeProvisioningRouterMount(
            make_capacity_router(
                lambda: _container_module.resolved_capacity_ledger_service,
                get_resource_inventory=_capacity_resource_inventory,
                get_pool_directory=_capacity_pool_directory,
            ),
            "/api/v1",
        ),
    ),
)

# Durable administrator-controlled caller-principal rotation.
@app.post("/api/v1/identity/rotations/{role}")
async def rotate_provisioning_principal(
    role: str,
    body: RotationRequest,
    request: Request,
):
    from compute_provisioning_service.services.principal_authority import (
        PrincipalRotationError,
    )

    try:
        return container.principal_authority().rotate(
            role,
            body,
            actor=request.state.marketplace_principal,
        )
    except PrincipalRotationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Test controller — only mounted when mock profile is active.
# Never present in production or staging.
import os as _os
_active_profiles = [p.strip() for p in _os.environ.get("ACTIVE_PROFILES", "").split(",") if p.strip()]
if "mock" in _active_profiles:
    app.include_router(test_jobs_controller.router)                                  # /test/jobs/*
    app.include_router(_vm_mock_router())                                            # /test/*
    app.include_router(_bare_metal_mock_router())                                    # /test/bare-metal/*
    logger.info("Test controllers mounted at /test/* (mock profile active)")

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
