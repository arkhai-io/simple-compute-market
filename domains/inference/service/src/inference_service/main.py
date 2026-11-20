from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import injected_time
import uvicorn
from arkhai_api_authority import load_pool_directory, site_route_contracts
from arkhai_api_contracts import operations
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from market_site.auth import (
    CAPACITY_ROUTE_CONTRACTS,
    EXCLUDED_PATHS,
    SiteAuthMiddleware,
)
from market_site.router import make_capacity_router

import inference_service.container as _container_module
from inference_service.config import settings
from inference_service.controllers.keys_controller import make_keys_router
from inference_service.controllers.system_controller import (
    make_health_router,
    make_system_router,
    make_time_router,
)
from inference_service.identity import (
    expected_principals,
    require_signer,
    signed_authentication_enabled,
)

# The authority's routes, adapted from the declarations its clients sign from.
INFERENCE_ROUTE_CONTRACTS = site_route_contracts()


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Installed before the application is built: `time.source`, "wall" unless
# "injected". The site ledger this service hosts reads it too.
injected_time.install(
    injected_time.source_for(
        injected_time.WALL
        if settings.configured_time_source is None
        else settings.configured_time_source,
        setting="time.source",
    )
)


def announce_time_source(source: injected_time.TimeSource) -> None:
    """Log an injected source at startup; a wall-time service logs nothing here."""
    if source.name == injected_time.INJECTED:
        logger.info(
            '[STARTUP] time.source is "injected": time is held at %s until set '
            "through POST /api/v1/system/time",
            source.now(),
        )


class MissingSiteIdentity(RuntimeError):
    """The service has no signing credential or no trusted principals."""


def require_signed_authentication() -> None:
    """Refuse to serve without both halves of the site identity; signed authentication is the only gate."""
    if not signed_authentication_enabled():
        raise MissingSiteIdentity(
            "the inference service requires site_signing_key_file and at least "
            "one trusted_principals role"
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting inference service...")
    announce_time_source(injected_time.installed())
    require_signed_authentication()
    _container_module.init()
    logger.info("Database initialised")
    yield
    logger.info("Shutdown complete")


app = FastAPI(
    title="Inference Service",
    version="0.1.0",
    description=(
        "Keys, prepaid request-credit grants, and consumption accounting for "
        "inference sold on the marketplace, plus this site's quota ledger.\n\n"
        "## Authentication\n\n"
        "Every non-health request carries a marketplace signature, and "
        "every response is signed in return -- refusals included. Callers "
        "are authorised by role: `seller` for the inference storefront, "
        "`service` for the inference gateway spending request credits, and "
        "`admin` for manual operation. A key's bearer secret authenticates "
        "no route. `/health`, `/docs`, and `/redoc` bypass authentication."
    ),
    openapi_tags=[
        {
            "name": "keys",
            "description": (
                "Issuance (market-facing), consume/verify "
                "(gateway-facing), and key administration."
            ),
        },
        {
            "name": "capacity",
            "description": (
                "Site-authority quota ledger — snapshot, probe, "
                "reserve/commit/release, and the versioned event feed."
            ),
        },
        {"name": "system", "description": "Health, version, status, and time."},
    ],
    lifespan=lifespan,
)

# Paths served without a signature: liveness and documentation only.
_UNSIGNED_PATHS = EXCLUDED_PATHS | {
    "/docs/oauth2-redirect",
    "/api/v1/system/health",
    "/api/v1/system/version",
}

# A route mounted without a contract is refused rather than waved through.
app.add_middleware(
    SiteAuthMiddleware,
    signer_provider=require_signer,
    expected_principals=expected_principals,
    contracts=INFERENCE_ROUTE_CONTRACTS + CAPACITY_ROUTE_CONTRACTS,
    max_timestamp_skew=int(settings.get("max_timestamp_skew", 300)),
    excluded_paths=_UNSIGNED_PATHS,
    time_setting_operation=operations.SYSTEM_TIME,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(make_health_router())
app.include_router(
    make_system_router(lambda: _container_module.resolved_system_service),
    prefix="/api/v1",
)
app.include_router(
    make_keys_router(lambda: _container_module.resolved_route_service),
    prefix="/api/v1",
)
app.include_router(
    make_capacity_router(
        lambda: _container_module.resolved_capacity_ledger_service,
        # The resource-pool projection carries each pool's declarations, which
        # a storefront resolves to bind a listing with its pool's backing.
        get_pool_directory=lambda: load_pool_directory(
            _container_module.resolved_session_factory
        ),
    ),
    prefix="/api/v1",
)
# Mounted only under injected time; a wall-time service serves no such route.
if injected_time.TimeRouteService(injected_time.installed()).settable:
    app.include_router(
        make_time_router(lambda: _container_module.resolved_system_service),
        prefix="/api/v1",
    )


if __name__ == "__main__":
    uvicorn.run(
        "inference_service.main:app",
        host=settings.host,
        port=settings.port,
    )
