"""Storefront FastAPI application.

Mirrors domains/vms/provisioning/service/src/main.py:

* ``FastAPI(lifespan=lifespan)`` — resolves singletons, starts background tasks.
* ``app.include_router()`` for every controller router.
* Admin auth via FastAPI Security() on individual routers — no middleware.
* X-Admin-Key OpenAPI security scheme registered so Swagger renders the
  Authorize button.

Global pause state
------------------
``_GLOBALLY_PAUSED`` is the module-level flag read by
``sync_negotiation.start_sync_negotiation``.
"""
from __future__ import annotations

import logging

import market_storefront.container as _container
from core_storefront.app_composition import (
    build_storefront_app,
    default_storefront_app_config,
)
from core_storefront.app_lifecycle import (
    StorefrontLifecycleCallbacks,
    build_storefront_lifespan,
)
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import set_stage_event_db_path, stage_event
from market_storefront.domain_runtime import get_market_domain_contract
from market_storefront.utils.config import settings, AGENT_ID
from market_storefront.utils.sqlite_client import get_sqlite_client
from market_storefront.utils.sync_negotiation import continue_sync_negotiation

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global pause flag
# ---------------------------------------------------------------------------

_GLOBALLY_PAUSED: bool = False


def is_globally_paused() -> bool:
    return _GLOBALLY_PAUSED


def _set_globally_paused(value: bool) -> None:
    global _GLOBALLY_PAUSED
    _GLOBALLY_PAUSED = value


# ---------------------------------------------------------------------------
def run_serve(
    host: str = "0.0.0.0",
    port: int | None = None,
) -> None:
    """Launch uvicorn. Called by ``market-storefront serve``."""
    import uvicorn

    resolved_port = port if port is not None else settings.port
    uvicorn.run(app, host=host, port=resolved_port, root_path=settings.gateway.root_path)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


def _build_alkahest_clients() -> dict:
    from market_storefront.services import alkahest_service

    return alkahest_service.build_clients()


def _build_listing_service(**kwargs):
    from market_storefront.services.listing_service import ListingService

    return ListingService(**kwargs)


def _build_negotiation_service(*, sqlite_client):
    return NegotiationService(
        sqlite_client=sqlite_client,
        continue_negotiation=continue_sync_negotiation,
        stage_event=stage_event,
    )


def _build_system_service(*, sqlite_client):
    from market_storefront.services.system_service import SystemService

    return SystemService(sqlite_client=sqlite_client, agent_id=AGENT_ID)


def _populate_container(
    *,
    sqlite_client,
    alkahest_clients,
    listing_service,
    negotiation_service,
    system_service,
) -> None:
    _container.resolved_sqlite_client = sqlite_client
    _container.resolved_alkahest_clients = alkahest_clients
    _container.resolved_listing_service = listing_service
    _container.resolved_negotiation_service = negotiation_service
    _container.resolved_system_service = system_service


async def _run_startup_tasks() -> None:
    from market_storefront.startup import _startup_tasks

    await _startup_tasks()


lifespan = build_storefront_lifespan(
    StorefrontLifecycleCallbacks(
        get_sqlite_client=get_sqlite_client,
        set_stage_event_db_path=set_stage_event_db_path,
        build_alkahest_clients=_build_alkahest_clients,
        build_listing_service=_build_listing_service,
        build_negotiation_service=_build_negotiation_service,
        build_system_service=_build_system_service,
        populate_container=_populate_container,
        startup_tasks=_run_startup_tasks,
        logger=logger,
    )
)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

# Controller imports after lifespan exists, before app construction.
from market_storefront.controllers.system_controller import router as system_router           # noqa: E402
from market_storefront.controllers.admin_controller import router as admin_router          # noqa: E402
from market_storefront.controllers.listings_controller import router as listings_router, admin_router as admin_listings_router       # noqa: E402
from market_storefront.controllers.negotiations_controller import router as negotiations_router  # noqa: E402
from market_storefront.controllers.negotiate_controller import router as negotiate_router     # noqa: E402
from market_storefront.controllers.settle_controller import router as settle_router, admin_settle_router           # noqa: E402
from market_storefront.controllers.deals_controller import router as deals_router  # noqa: E402


app = build_storefront_app(
    config=default_storefront_app_config(root_path=settings.gateway.root_path),
    domain=get_market_domain_contract(),
    lifespan=lifespan,
    routers=(
        system_router,
        admin_router,
        listings_router,
        admin_listings_router,
        negotiations_router,
        negotiate_router,
        settle_router,
        deals_router,
        admin_settle_router,
    ),
)
