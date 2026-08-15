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
from dataclasses import dataclass
from typing import Any

from core_storefront.app_composition import default_storefront_app_config
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import set_stage_event_db_path, stage_event
from market_core import MarketDomainContract
from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontDomainRegistry,
)
from market_capacity_publication import CapacityRuntime
from market_negotiation_runtime import NegotiationRuntime
from market_storefront_kit import (
    AlkahestChain,
    AlkahestClientPolicy,
    StorefrontComposition,
    StorefrontRouteHooks,
    StorefrontServiceHooks,
    build_alkahest_clients,
    build_composed_storefront_app,
)

import market_storefront.container as _container
from market_storefront.domain_runtime import validate_vm_storefront_domain
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
    get_evm_wallet_address,
    get_evm_wallet_private_key,
    get_registry_authorities,
    resolve_marketplace_signer,
    settings,
    storefront_domain_registry,
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


def _build_alkahest_clients() -> dict[str, Any]:
    from market_storefront.utils.config import CHAINS, settlement_config_mapping

    alkahest = settlement_config_mapping().get("alkahest", {})
    if not isinstance(alkahest, dict) or not alkahest:
        return {}
    if not bool(alkahest.get("enabled", False)) and not CHAINS:
        return {}
    missing: list[str] = []
    if not get_evm_wallet_address():
        missing.append("wallet.address")
    private_key = get_evm_wallet_private_key()
    if not private_key:
        missing.append("wallet.private_key")
    return build_alkahest_clients(
        AlkahestClientPolicy(
            private_key=private_key,
            chains=(
                ()
                if missing
                else tuple(
                    AlkahestChain(
                        name=name,
                        rpc_url=chain.rpc_url,
                        address_config_path=chain.alkahest_address_config_path,
                    )
                    for name, chain in CHAINS.items()
                )
            ),
            missing_requirements=tuple(missing),
        ),
        logger=logger,
    )


def _build_listing_service(
    *,
    registry: StorefrontDomainRegistry,
    binding: StorefrontDomainBinding,
    domain: MarketDomainContract,
    capacity_runtime: CapacityRuntime,
    settlement_composition: Any,
    **kwargs: Any,
) -> Any:
    from market_storefront.services.listing_service import ListingService

    return ListingService(
        registry=registry,
        binding=binding,
        domain=domain,
        capacity_runtime=capacity_runtime,
        **kwargs,
        settlement_composition_provider=lambda: settlement_composition,
    )


def _build_negotiation_service(
    *, runtime: NegotiationRuntime, **kwargs: Any
) -> NegotiationService:
    return NegotiationService(
        **kwargs,
        continue_negotiation=runtime.continue_negotiation,
        stage_event=stage_event,
    )


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


@dataclass(frozen=True, slots=True)
class VmStorefrontServices:
    """Lifespan-owned VM services bound to one exact registry registration."""

    registry: StorefrontDomainRegistry
    binding: StorefrontDomainBinding
    domain: MarketDomainContract
    sqlite_client: Any
    marketplace_signer: Any
    alkahest_clients: dict[str, Any]
    capacity_runtime: CapacityRuntime
    listing_service: Any
    negotiation_runtime: NegotiationRuntime
    negotiation_service: Any
    system_service: Any
    settlement_composition: Any


def _build_vm_services(
    *,
    registry: StorefrontDomainRegistry,
    binding: StorefrontDomainBinding,
    domain: MarketDomainContract,
) -> VmStorefrontServices:
    registration = registry.resolve_registration(binding)
    if registration.contract is not domain:
        raise RuntimeError(
            "VM service composition must use the exact registry-owned domain contract"
        )
    sqlite_client = get_sqlite_client(registry=registry)
    marketplace_signer = resolve_marketplace_signer()
    set_stage_event_db_path(sqlite_client.db_path)
    alkahest_clients = _build_alkahest_clients()
    from market_storefront.services.capacity_client import build_capacity_runtime_for

    capacity_runtime = build_capacity_runtime_for(
        lambda: sqlite_client,
        signer=marketplace_signer,
    )
    settlement_composition = _build_settlement_composition(
        domain=domain,
        sqlite_client=sqlite_client,
        alkahest_clients=alkahest_clients,
        marketplace_signer=marketplace_signer,
    )
    negotiation_runtime = build_vm_negotiation_runtime(
        domain,
        registry=registry,
        binding=binding,
        capacity_runtime=capacity_runtime,
    )
    listing_service = _build_listing_service(
        registry=registry,
        binding=binding,
        domain=domain,
        capacity_runtime=capacity_runtime,
        sqlite_client=sqlite_client,
        alkahest_clients=alkahest_clients,
        marketplace_signer=marketplace_signer,
        settlement_composition=settlement_composition,
    )
    negotiation_service = _build_negotiation_service(
        runtime=negotiation_runtime,
        sqlite_client=sqlite_client,
    )
    system_service = _build_system_service(
        sqlite_client=sqlite_client,
        marketplace_signer=marketplace_signer,
    )
    return VmStorefrontServices(
        registry=registry,
        binding=binding,
        domain=domain,
        sqlite_client=sqlite_client,
        marketplace_signer=marketplace_signer,
        alkahest_clients=alkahest_clients,
        capacity_runtime=capacity_runtime,
        listing_service=listing_service,
        negotiation_runtime=negotiation_runtime,
        negotiation_service=negotiation_service,
        system_service=system_service,
        settlement_composition=settlement_composition,
    )

async def _start_vm_services(services: VmStorefrontServices) -> None:
    if (
        _container.resolved_domain_registry is not None
        and _container.resolved_domain_registry is not services.registry
    ):
        raise RuntimeError(
            "dependency container is already owned by a different "
            "storefront domain registry"
        )
    _container.resolved_domain_registry = services.registry
    _container.resolved_sqlite_client = services.sqlite_client
    _container.resolved_marketplace_signer = services.marketplace_signer
    if settings.enable_registry_discovery:
        get_registry_authorities()
    initialize_administrator_identities(services.sqlite_client.db_path)
    initialize_service_peer_identities(services.sqlite_client.db_path)
    _container.resolved_alkahest_clients = services.alkahest_clients
    _container.resolved_listing_service = services.listing_service
    _container.resolved_negotiation_runtime = services.negotiation_runtime
    _container.resolved_negotiation_service = services.negotiation_service
    _container.resolved_system_service = services.system_service
    _container.resolved_settlement_composition = services.settlement_composition
    logger.info("[STARTUP] Singletons initialized")
    await _run_startup_tasks(
        registry=services.registry,
        domain=services.domain,
    )
    logger.info("[STARTUP] Background tasks started")


async def _stop_vm_services(services: VmStorefrontServices) -> None:
    _container.clear_lifespan_state(registry=services.registry)
    logger.info("[SHUTDOWN] Storefront shutting down")


async def _run_startup_tasks(
    *,
    registry: StorefrontDomainRegistry,
    domain: MarketDomainContract,
) -> None:
    from market_storefront.startup import _startup_tasks

    await _startup_tasks(registry=registry, domain=domain)





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

def build_vm_storefront_app(*, registry: StorefrontDomainRegistry):
    """Build the VM HTTP application from one explicit frozen registry."""

    registration = registry.resolve_mode("vm")
    selected_domain = validate_vm_storefront_domain(registration.contract)
    selected_binding = registration.binding

    def build_services(domain: MarketDomainContract) -> VmStorefrontServices:
        if domain is not selected_domain:
            raise RuntimeError(
                "storefront kit supplied a domain outside the selected VM registration"
            )
        return _build_vm_services(
            registry=registry,
            binding=selected_binding,
            domain=domain,
        )

    return build_composed_storefront_app(
        StorefrontComposition(
            registry=registry,
            binding=selected_binding,
            domain=selected_domain,
            app=default_storefront_app_config(
                root_path=settings.gateway.root_path,
            ),
            services=StorefrontServiceHooks(
                build=build_services,
                start=_start_vm_services,
                stop=_stop_vm_services,
            ),
            routes=StorefrontRouteHooks(
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
                middleware=(
                    listing_lifecycle_middleware,
                    service_peer_callback_middleware,
                    administrator_identity_middleware,
                ),
            ),
        )
    )


app = build_vm_storefront_app(registry=storefront_domain_registry())
