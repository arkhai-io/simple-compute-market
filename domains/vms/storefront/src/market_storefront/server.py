"""Storefront FastAPI application.

Mirrors provisioning/compute/service/src/compute_provisioning_service/main.py:

* ``FastAPI(lifespan=lifespan)`` — resolves singletons, starts background tasks.
* ``app.include_router()`` for every controller router.
* Admin auth via FastAPI Security() on individual routers — no middleware.
* X-Admin-Key OpenAPI security scheme registered so Swagger renders the
  Authorize button.

Global pause state is read through the VM hook set injected into the shared
negotiation runtime.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from functools import partial

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
from market_core import MarketDomainContract

import market_storefront.container as _container
from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    validate_vm_storefront_domain,
)
from market_storefront.middleware.admin_identity import (
    administrator_identity_middleware,
    initialize_administrator_identities,
)
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from market_storefront.middleware.service_peer_auth import (
    initialize_service_peer_identities,
    service_peer_callback_middleware,
)
from market_storefront.utils.config import (
    AGENT_ID,
    get_registry_authorities,
    resolve_marketplace_signer,
    settings,
)
from market_storefront.utils.sqlite_client import get_sqlite_client
from market_storefront.negotiation_runtime import build_vm_negotiation_runtime

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
    uvicorn.run(
        app, host=host, port=resolved_port, root_path=settings.gateway.root_path
    )


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


def _build_alkahest_clients() -> dict:
    from market_storefront.utils.config import CHAINS, settlement_config_mapping

    alkahest = settlement_config_mapping().get("alkahest", {})
    if not isinstance(alkahest, dict) or not alkahest:
        return {}
    if not bool(alkahest.get("enabled", False)) and not CHAINS:
        return {}
    from market_storefront.services import alkahest_service

    return alkahest_service.build_clients()


def _build_listing_service(*, domain: MarketDomainContract, **kwargs):
    from market_storefront.services.listing_service import ListingService

    return ListingService(
        domain=domain,
        **kwargs,
        settlement_composition_provider=lambda: (
            _container.resolved_settlement_composition
        ),
    )


def _build_negotiation_service(*, domain: MarketDomainContract, **kwargs):
    runtime = build_vm_negotiation_runtime(domain)
    service = NegotiationService(
        **kwargs,
        continue_negotiation=runtime.continue_negotiation,
        stage_event=stage_event,
    )
    service._market_domain_contract = domain
    service._negotiation_runtime = runtime
    return service


def _build_system_service(**kwargs):
    from market_storefront.services.system_service import SystemService

    return SystemService(agent_id=AGENT_ID, **kwargs)


def _build_settlement_composition(
    *,
    domain: MarketDomainContract,
    sqlite_client,
    alkahest_clients,
    marketplace_signer,
):
    from market_storefront.domain_runtime import build_settlement_runtime

    return build_settlement_runtime(
        domain=domain,
        sqlite_client=sqlite_client,
        alkahest_clients=alkahest_clients,
        marketplace_signer=marketplace_signer,
    )


def _populate_container(
    domain: MarketDomainContract,
    *,
    sqlite_client,
    alkahest_clients,
    listing_service,
    negotiation_service,
    system_service,
    marketplace_signer,
) -> None:
    if (
        _container.resolved_market_domain is not None
        and _container.resolved_market_domain is not domain
    ):
        raise RuntimeError(
            "dependency container is already owned by a different "
            "market-domain contract"
        )
    collaborators = (
        ("SQLite repository", getattr(sqlite_client, "market_domain", None)),
        ("listing service", getattr(listing_service, "market_domain", None)),
        (
            "negotiation runtime",
            getattr(negotiation_service, "_market_domain_contract", None),
        ),
    )
    for label, collaborator_domain in collaborators:
        if collaborator_domain is not domain:
            raise RuntimeError(
                f"{label} is not bound to the app-selected market-domain "
                "contract object"
            )
    settlement_composition = _build_settlement_composition(
        domain=domain,
        sqlite_client=sqlite_client,
        alkahest_clients=alkahest_clients,
        marketplace_signer=marketplace_signer,
    )
    _container.resolved_market_domain = domain
    _container.resolved_sqlite_client = sqlite_client
    _container.resolved_marketplace_signer = marketplace_signer
    _container.resolved_negotiation_runtime = (
        negotiation_service._negotiation_runtime
    )
    if settings.enable_registry_discovery:
        get_registry_authorities()
    initialize_administrator_identities(sqlite_client.db_path)
    initialize_service_peer_identities(sqlite_client.db_path)
    _container.resolved_alkahest_clients = alkahest_clients
    _container.resolved_listing_service = listing_service
    _container.resolved_negotiation_service = negotiation_service
    _container.resolved_system_service = system_service
    _container.resolved_settlement_composition = settlement_composition


async def _run_startup_tasks(*, domain: MarketDomainContract) -> None:
    from market_storefront.startup import _startup_tasks

    await _startup_tasks(domain=domain)


def build_vm_storefront_lifespan(*, domain: MarketDomainContract):
    """Bind every VM lifespan callback to one selected contract object."""
    shared_lifespan = build_storefront_lifespan(
        StorefrontLifecycleCallbacks(
            get_sqlite_client=partial(get_sqlite_client, domain=domain),
            resolve_identity_signer=resolve_marketplace_signer,
            set_stage_event_db_path=set_stage_event_db_path,
            build_alkahest_clients=_build_alkahest_clients,
            build_listing_service=partial(_build_listing_service, domain=domain),
            build_negotiation_service=partial(
                _build_negotiation_service,
                domain=domain,
            ),
            build_system_service=_build_system_service,
            populate_container=partial(_populate_container, domain=domain),
            startup_tasks=partial(_run_startup_tasks, domain=domain),
            logger=logger,
        )
    )

    @asynccontextmanager
    async def lifespan(application):
        if getattr(application.state, "market_domain", None) is not domain:
            raise RuntimeError(
                "FastAPI app is not bound to its lifespan market-domain "
                "contract object"
            )
        try:
            async with shared_lifespan(application):
                yield
        finally:
            _container.clear_lifespan_state(domain=domain)

    return lifespan


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

# Controller imports after lifespan exists, before app construction.
from market_storefront.controllers.admin_controller import (  # noqa: E402
    router as admin_router,
)
from market_storefront.controllers.deals_controller import (  # noqa: E402
    router as deals_router,
)
from market_storefront.controllers.listings_controller import (  # noqa: E402
    admin_router as admin_listings_router,
)
from market_storefront.controllers.listings_controller import (  # noqa: E402
    router as listings_router,
)
from market_storefront.controllers.negotiate_controller import (  # noqa: E402
    router as negotiate_router,
)
from market_storefront.controllers.negotiations_controller import (  # noqa: E402
    router as negotiations_router,
)
from market_storefront.controllers.settle_controller import (  # noqa: E402
    admin_settle_router,
    settlements_router,
)
from market_storefront.controllers.settle_controller import (  # noqa: E402
    router as settle_router,
)
from market_storefront.controllers.system_controller import (  # noqa: E402
    router as system_router,
)

def build_vm_storefront_app(*, domain: MarketDomainContract):
    """Build the VM HTTP application around one validated contract."""
    selected_domain = validate_vm_storefront_domain(domain)
    application = build_storefront_app(
        config=default_storefront_app_config(root_path=settings.gateway.root_path),
        domain=selected_domain,
        lifespan=build_vm_storefront_lifespan(domain=selected_domain),
        routers=(
            system_router,
            admin_router,
            listings_router,
            admin_listings_router,
            negotiations_router,
            negotiate_router,
            settle_router,
            settlements_router,
            deals_router,
            admin_settle_router,
        ),
    )
    application.middleware("http")(listing_lifecycle_middleware)
    application.middleware("http")(service_peer_callback_middleware)
    application.middleware("http")(administrator_identity_middleware)
    return application


app = build_vm_storefront_app(domain=build_vm_storefront_domain())
