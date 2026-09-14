from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import container as _container_module
from config import settings
from controllers.keys_controller import make_keys_router
from controllers.system_controller import make_health_router, make_system_router
from identity import (
    expected_principals,
    require_signer,
    signed_authentication_enabled,
)
from market_site.auth import (
    CAPACITY_ROUTE_CONTRACTS,
    EXCLUDED_PATHS,
    SiteAuthMiddleware,
)
from market_site.router import make_capacity_router
from middleware.auth import AdminKeyAuthMiddleware
from middleware.route_contracts import CREDITS_ROUTE_CONTRACTS


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting API-credits service...")
    _container_module.init()
    logger.info("Database initialised")
    yield
    logger.info("Shutdown complete")


app = FastAPI(
    title="API-Credits Service",
    version="0.1.0",
    description=(
        "Keys, prepaid credit grants, and consumption accounting for "
        "token-gated services sold on the marketplace, plus this site's "
        "quota ledger.\n\n"
        "## Authentication\n\n"
        "Every non-health request carries a marketplace signature, and "
        "every response is signed in return -- refusals included. Callers "
        "are authorised by role: `seller` for the storefront selling these "
        "credits, `service` for the gated application spending them, and "
        "`admin` for manual operation.\n\n"
        "A deployment with no identity provisioned falls back to the "
        "`X-Admin-Key` shared-secret gate.\n\n"
        "Callers are the seller's storefront (issuance, guard lookups, "
        "capacity) and the gated service's middlewares (consume/verify). "
        "`/health`, `/docs`, and `/redoc` bypass authentication."
    ),
    openapi_tags=[
        {
            "name": "keys",
            "description": (
                "Issuance (market-facing), consume/verify "
                "(middleware-facing), and key administration."
            ),
        },
        {
            "name": "capacity",
            "description": (
                "Site-authority quota ledger — snapshot, probe, "
                "reserve/commit/release, and the versioned event feed."
            ),
        },
        {"name": "system", "description": "Health and version."},
    ],
    lifespan=lifespan,
)

# Paths served without a signature: liveness and documentation only.
# `/docs/oauth2-redirect` is loaded by the docs page itself, and the versioned
# health/version pair exists so an orchestrator can probe this service without
# holding a marketplace credential.
_UNSIGNED_PATHS = EXCLUDED_PATHS | {
    "/docs/oauth2-redirect",
    "/api/v1/system/health",
    "/api/v1/system/version",
}

# Middleware (outermost applied last)
if signed_authentication_enabled():
    # Both route tables under one middleware. `kit/site` owns the capacity
    # contracts because it defines those paths; this service owns its own.
    # Anything mounted without a contract is refused rather than waved
    # through, so adding a route without one fails loudly.
    app.add_middleware(
        SiteAuthMiddleware,
        signer_provider=require_signer,
        expected_principals=expected_principals,
        contracts=CREDITS_ROUTE_CONTRACTS + CAPACITY_ROUTE_CONTRACTS,
        max_timestamp_skew=int(settings.get("max_timestamp_skew", 300)),
        excluded_paths=_UNSIGNED_PATHS,
    )
else:
    # No identity provisioned. Keeping the shared-secret gate is the honest
    # fallback: the alternative is an open service, and half-enabling signed
    # authentication would verify callers and then answer them unsigned --
    # the one failure the kit's client cannot read at all.
    logger.warning(
        "No site signing credential or trusted principals configured; "
        "falling back to the X-Admin-Key gate. Marketplace-signed callers "
        "will be refused."
    )
    app.add_middleware(
        AdminKeyAuthMiddleware,
        admin_key=str(settings.storefront_admin_key or ""),
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
#   /api/v1/system/*                 <- versioned health + version
#   /api/v1/issuance                 <- deal fulfillment (storefront)
#   /api/v1/keys/*                   <- consume/verify, admin, guard lookup
#   /api/v1/capacity/*               <- site quota ledger (market_site)
# ---------------------------------------------------------------------------
app.include_router(make_health_router())                                       # /health
app.include_router(make_system_router(), prefix="/api/v1")                     # /api/v1/system/*
app.include_router(                                                            # /api/v1/issuance, /api/v1/keys/*
    make_keys_router(lambda: _container_module.resolved_keys_service),
    prefix="/api/v1",
)
app.include_router(                                                            # /api/v1/capacity/*
    make_capacity_router(lambda: _container_module.resolved_capacity_ledger_service),
    prefix="/api/v1",
)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
