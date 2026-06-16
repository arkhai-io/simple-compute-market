"""API-tokens storefront FastAPI application.

Mirrors the VM storefront's shape: ``FastAPI(lifespan=lifespan)``
resolves singletons and starts the background tasks; controllers mount
after the module-level app exists; admin auth via Security() on
individual routers.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

import apitokens_storefront.container as _container
from apitokens_storefront.utils.config import AGENT_ID, settings
from apitokens_storefront.utils.sqlite_client import get_sqlite_client
from apitokens_storefront.utils.sync_negotiation import continue_sync_negotiation
from core_storefront.openapi import install_admin_key_openapi
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import set_stage_event_db_path, stage_event

logger = logging.getLogger(__name__)

_GLOBALLY_PAUSED: bool = False


def is_globally_paused() -> bool:
    return _GLOBALLY_PAUSED


def _set_globally_paused(value: bool) -> None:
    global _GLOBALLY_PAUSED
    _GLOBALLY_PAUSED = value


def run_serve(host: str = "0.0.0.0", port: int | None = None) -> None:
    """Launch uvicorn. Called by ``apitokens-storefront serve``."""
    import uvicorn

    resolved_port = port if port is not None else settings.port
    uvicorn.run(
        app, host=host, port=resolved_port,
        root_path=settings.gateway.root_path,
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    from apitokens_storefront.services import alkahest_service
    from apitokens_storefront.services.listing_service import ListingService
    from apitokens_storefront.services.system_service import SystemService
    from apitokens_storefront.startup import _startup_tasks

    sqlite_client = get_sqlite_client()
    set_stage_event_db_path(sqlite_client.db_path)
    alkahest_clients = alkahest_service.build_clients()

    _container.resolved_sqlite_client = sqlite_client
    _container.resolved_alkahest_clients = alkahest_clients
    _container.resolved_listing_service = ListingService(
        sqlite_client=sqlite_client,
    )
    _container.resolved_negotiation_service = NegotiationService(
        sqlite_client=sqlite_client,
        continue_negotiation=continue_sync_negotiation,
        stage_event=stage_event,
    )
    _container.resolved_system_service = SystemService(
        sqlite_client=sqlite_client, agent_id=AGENT_ID,
    )

    logger.info("[STARTUP] Singletons initialized")
    await _startup_tasks()
    logger.info("[STARTUP] Background tasks started")

    yield

    logger.info("[SHUTDOWN] API-tokens storefront shutting down")


app = FastAPI(
    title="Arkhai API-Tokens Storefront",
    description=(
        "Seller-side storefront for the Arkhai API-tokens marketplace.\n\n"
        "**Admin endpoints** require an `X-Admin-Key` header.\n\n"
        "**Buyer-facing endpoints** (`/api/v1/negotiate/*`, `/api/v1/settle/*`) "
        "require EIP-191 signed `X-Signature` + `X-Timestamp` headers."
    ),
    version="1.0.0",
    lifespan=lifespan,
    root_path=settings.gateway.root_path,
    swagger_ui_parameters={"persistAuthorization": True},
)


install_admin_key_openapi(app, root_path=settings.gateway.root_path)

# Controller imports after module-level app exists.
from apitokens_storefront.controllers.system_controller import router as system_router          # noqa: E402
from apitokens_storefront.controllers.listings_controller import router as listings_router      # noqa: E402
from apitokens_storefront.controllers.negotiate_controller import router as negotiate_router    # noqa: E402
from apitokens_storefront.controllers.negotiations_controller import router as negotiations_router  # noqa: E402
from apitokens_storefront.controllers.settle_controller import (                                 # noqa: E402
    admin_settle_router,
    router as settle_router,
)

app.include_router(system_router)
app.include_router(listings_router)
app.include_router(negotiate_router)
app.include_router(negotiations_router)
app.include_router(settle_router)
app.include_router(admin_settle_router)
