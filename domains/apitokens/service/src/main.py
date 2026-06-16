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
from core_site.router import make_capacity_router
from middleware.auth import AdminKeyAuthMiddleware


logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("Starting API-tokens service...")
    _container_module.init()
    logger.info("Database initialised")
    yield
    logger.info("Shutdown complete")


app = FastAPI(
    title="API-Tokens Service",
    version="0.1.0",
    description=(
        "Keys, prepaid credit grants, and consumption accounting for "
        "token-gated services sold on the marketplace, plus this site's "
        "quota ledger.\n\n"
        "## Authentication\n\n"
        "The service is an internal dependency of one seller. When an "
        "admin key is configured, every non-health request must present "
        "it:\n\n```\nX-Admin-Key: <admin_api_key>\n```\n\n"
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

# Middleware (outermost applied last)
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
#   /api/v1/capacity/*               <- site quota ledger (core_site)
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
