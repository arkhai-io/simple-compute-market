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
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from core_storefront.app_composition import default_storefront_app_config
from core_storefront.domain_registry import (
    StorefrontDomainBinding,
    StorefrontDomainRegistry,
)
from core_storefront.service_peers import ServicePeerConfigs, ServicePeerTrust
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import set_stage_event_db_path, stage_event
from market_capacity_publication import CapacityRuntime, SiteProjectionState
from market_core import MarketDomainContract
from market_capability_admissibility import Declaration
from market_negotiation_runtime import NegotiationRuntime
from market_pool_overrides import PoolOverrideService, SQLitePoolOverrideStore
from market_alkahest import ALKAHEST_CONFIG_KEY, AlkahestChainProbe, ProbedChain
from market_storefront_kit import (
    AlkahestChain,
    AlkahestClientPolicy,
    StorefrontComposition,
    StorefrontRouteHooks,
    StorefrontServiceHooks,
    alkahest_client_constructor,
    build_alkahest_clients,
    build_composed_storefront_app,
)

import market_storefront.container as _container
from market_storefront.contact_exchange import (
    build_vm_contact_exchange,
    build_vm_introduction_delivery,
)
from market_storefront.domain_runtime import validate_vm_storefront_domain
from market_storefront.middleware.admin_identity import (
    administrator_identity_middleware,
    initialize_administrator_identities,
)
from market_storefront.middleware.seller_auth import listing_lifecycle_middleware
from market_storefront.middleware.service_peer_auth import (
    service_peer_callback_middleware,
)
from market_storefront.negotiation_runtime import build_vm_negotiation_runtime
from market_storefront.utils.config import (
    AGENT_ID,
    CHAINS,
    get_evm_wallet_address,
    get_evm_wallet_private_key,
    get_service_peer_configs,
    resolve_marketplace_signer,
    settings,
    settlement_config_mapping,
    storefront_domain_registry,
)
from market_storefront.utils.sqlite_client import get_sqlite_client

from market_storefront.services.capacity_client import site_pool_projection
from market_storefront.services.vm_pool_override_contribution import (
    VmPoolOverrideContribution,
)
from market_storefront.services.publication_loop import wake_publication_loop
from market_storefront.services.publication_terms import (
    compile_publication_clauses,
    parse_configured_admissibility_default,
)
from market_storefront.services.shape_feasibility import vm_shape_feasibility
from market_storefront.settlement_composition import require_coherent_release_model
from market_storefront.settlement_registry import build_storefront_settlement_registry
from market_storefront.startup_refusal import require_publishable_storefront

logger = logging.getLogger(__name__)

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


def _alkahest_client_policy() -> AlkahestClientPolicy | None:
    """What the storefront's Alkahest clients are built from; ``None`` when no
    Alkahest section asks for any."""
    alkahest = settlement_config_mapping().get("alkahest", {})
    if not isinstance(alkahest, dict) or not alkahest:
        return None
    if not bool(alkahest.get("enabled", False)) and not CHAINS:
        return None
    missing: list[str] = []
    if not get_evm_wallet_address():
        missing.append("wallet.address")
    private_key = get_evm_wallet_private_key()
    if not private_key:
        missing.append("wallet.private_key")
    return AlkahestClientPolicy(
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
    )


def _build_alkahest_clients() -> dict[str, Any]:
    policy = _alkahest_client_policy()
    if policy is None:
        return {}
    return build_alkahest_clients(policy, logger=logger)


def _build_alkahest_chain_probe(
    alkahest_clients: dict[str, Any],
) -> AlkahestChainProbe | None:
    """The chain probe over every configured chain, owning ``alkahest_clients``.

    Composed whenever ``[Settlement.alkahest]`` is configured, enabled or not:
    a disabled section still services the obligations accepted under it, which
    need their chains' clients.
    """
    section = (
        build_storefront_settlement_registry()
        .resolve(settlement_config_mapping(), role="seller")
        .mechanism_config(ALKAHEST_CONFIG_KEY)
    )
    if section is None:
        return None
    policy = _alkahest_client_policy()
    return AlkahestChainProbe(
        [ProbedChain.from_config(name, chain) for name, chain in CHAINS.items()],
        build_client=(
            alkahest_client_constructor(policy) if policy is not None else None
        ),
        clients=alkahest_clients,
        interval_seconds=section.probe_interval_seconds,
        rpc_timeout_seconds=section.rpc_timeout_seconds,
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


def build_pool_override_service(
    *,
    sqlite_client: Any,
    capacity_runtime: Any,
    site_projections: SiteProjectionState,
    admissibility_default: Declaration | None,
) -> Any:
    """Compose the pool-override kit's service over this storefront's effects.

    The VM market contributes the ``vm`` offering mode, judging each write's
    shapes against ``admissibility_default``, the configured default
    publication also resolves with. A write is checked
    against the named site through the capacity runtime's signed client,
    refreshes only that site's held projections, and wakes the publication
    loop; status is judged against the held resource-pool projection
    publication derives from. The lifespan and the publication test harness
    compose it identically.
    """
    contribution = VmPoolOverrideContribution(
        db_path=sqlite_client.db_path,
        shape_feasible=vm_shape_feasibility(),
        admissibility_default=admissibility_default,
    )
    return PoolOverrideService(
        store=SQLitePoolOverrideStore(sqlite_client.db_path),
        site_ids=lambda: capacity_runtime.site_ids if capacity_runtime is not None else (),
        site_client=lambda site_id: capacity_runtime.site_client(site_id),
        contributions={contribution.offering_mode: contribution},
        compile_clauses=compile_publication_clauses,
        projection_source=partial(site_pool_projection, site_projections),
        refresh_site=site_projections.refresh_site,
        wake_publication=wake_publication_loop,
    )


def _build_settlement_composition(
    *,
    domain: MarketDomainContract,
    sqlite_client,
    alkahest_clients,
    marketplace_signer,
    chain_probe=None,
):
    from market_storefront.domain_runtime import build_settlement_runtime

    return build_settlement_runtime(
        domain=domain,
        sqlite_client=sqlite_client,
        alkahest_clients=alkahest_clients,
        marketplace_signer=marketplace_signer,
        chain_probe=chain_probe,
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
    alkahest_chain_probe: AlkahestChainProbe | None
    capacity_runtime: CapacityRuntime
    site_projections: SiteProjectionState
    service_peer_trust: ServicePeerTrust
    listing_service: Any
    negotiation_runtime: NegotiationRuntime
    negotiation_service: Any
    system_service: Any
    pool_override_service: Any
    admissibility_default: Declaration | None
    settlement_composition: Any
    contact_exchange: Any
    introduction_delivery: Any


@dataclass(frozen=True, slots=True)
class VmCompositionSeams:
    """What the composition root reads its service-peer trust and its startup
    refusal through.

    The defaults are production's: the configured service peers, the durable
    trust over the storefront's database, and the refusal of a configuration
    that states a retired setting or could never publish. A test of the root's
    wiring supplies compatible objects instead of patching the module.
    """

    service_peer_configs: Callable[[], ServicePeerConfigs] = get_service_peer_configs
    service_peer_trust: Callable[[str, ServicePeerConfigs], ServicePeerTrust] = (
        ServicePeerTrust
    )
    startup_refusal: Callable[[], None] = require_publishable_storefront


def _build_vm_services(
    *,
    registry: StorefrontDomainRegistry,
    binding: StorefrontDomainBinding,
    domain: MarketDomainContract,
    seams: VmCompositionSeams = VmCompositionSeams(),
) -> VmStorefrontServices:
    registration = registry.resolve_registration(binding)
    if registration.contract is not domain:
        raise RuntimeError(
            "VM service composition must use the exact registry-owned domain contract"
        )
    # Before anything is constructed: a configured default the storefront
    # cannot read, a contradictory Alkahest release model, or a configuration
    # under which it could never publish stops startup rather than running
    # without it. An Alkahest section that is coherent but cannot settle makes
    # Alkahest unready instead.
    admissibility_default = parse_configured_admissibility_default()
    require_coherent_release_model()
    seams.startup_refusal()
    sqlite_client = get_sqlite_client(registry=registry)
    marketplace_signer = resolve_marketplace_signer()
    set_stage_event_db_path(sqlite_client.db_path)
    alkahest_clients = _build_alkahest_clients()
    # The probe owns the client map from here: every consumer below is handed
    # this one dict, which the probe updates in place as it rebuilds clients.
    alkahest_chain_probe = _build_alkahest_chain_probe(alkahest_clients)
    from market_storefront.services.capacity_client import build_capacity_runtime_for

    # Each site's responses and callbacks are verified against its service
    # peer's principals, which this trust holds once the lifespan seeds it.
    service_peer_trust = seams.service_peer_trust(
        sqlite_client.db_path, seams.service_peer_configs()
    )
    site_projections: SiteProjectionState | None = None
    # Capacity reconciliation reads the state built just below, over this
    # runtime's own aggregate; the provider is read when a delta arrives.
    capacity_runtime = build_capacity_runtime_for(
        lambda: sqlite_client,
        signer=marketplace_signer,
        site_projections=lambda: site_projections,
        service_peer_trust=service_peer_trust,
    )
    # One state per process, over the runtime's own aggregate: every consumer
    # reads it, and a resource-pool change a poll observes wakes publication.
    site_projections = SiteProjectionState(
        capacity_runtime.client(),
        on_resource_pool_change=wake_publication_loop,
    )
    settlement_composition = _build_settlement_composition(
        domain=domain,
        sqlite_client=sqlite_client,
        alkahest_clients=alkahest_clients,
        marketplace_signer=marketplace_signer,
        chain_probe=alkahest_chain_probe,
    )
    negotiation_runtime = build_vm_negotiation_runtime(
        domain,
        registry=registry,
        binding=binding,
        capacity_runtime=capacity_runtime,
        site_projections=site_projections,
        accepted_obligation_dispatch=(
            settlement_composition.accepted_obligation_dispatch()
        ),
        arkhai_payments_stage=settlement_composition.arkhai_payments_stage,
    )
    listing_service = _build_listing_service(
        registry=registry,
        binding=binding,
        domain=domain,
        capacity_runtime=capacity_runtime,
        site_projections=site_projections,
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
        site_projections=site_projections,
    )
    pool_override_service = build_pool_override_service(
        sqlite_client=sqlite_client,
        capacity_runtime=capacity_runtime,
        site_projections=site_projections,
        admissibility_default=admissibility_default,
    )
    known_origins = capacity_runtime.site_ids
    introduction_delivery = build_vm_introduction_delivery(
        known_origins=known_origins,
        signer=marketplace_signer,
    )
    contact_exchange = build_vm_contact_exchange(
        sqlite_client=sqlite_client,
        settlement_composition=settlement_composition,
        known_origins=known_origins,
        delivery=introduction_delivery,
    )
    return VmStorefrontServices(
        registry=registry,
        binding=binding,
        domain=domain,
        sqlite_client=sqlite_client,
        marketplace_signer=marketplace_signer,
        alkahest_clients=alkahest_clients,
        alkahest_chain_probe=alkahest_chain_probe,
        capacity_runtime=capacity_runtime,
        site_projections=site_projections,
        service_peer_trust=service_peer_trust,
        listing_service=listing_service,
        negotiation_runtime=negotiation_runtime,
        negotiation_service=negotiation_service,
        system_service=system_service,
        pool_override_service=pool_override_service,
        admissibility_default=admissibility_default,
        settlement_composition=settlement_composition,
        contact_exchange=contact_exchange,
        introduction_delivery=introduction_delivery,
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
    try:
        _container.resolved_sqlite_client = services.sqlite_client
        _container.resolved_marketplace_signer = services.marketplace_signer
        initialize_administrator_identities(services.sqlite_client.db_path)
        services.service_peer_trust.seed()
        _container.resolved_service_peer_trust = services.service_peer_trust
        _container.resolved_alkahest_clients = services.alkahest_clients
        _container.resolved_alkahest_chain_probe = services.alkahest_chain_probe
        _container.resolved_capacity_runtime = services.capacity_runtime
        _container.resolved_site_projections = services.site_projections
        _container.resolved_listing_service = services.listing_service
        _container.resolved_negotiation_runtime = services.negotiation_runtime
        _container.resolved_negotiation_service = services.negotiation_service
        _container.resolved_system_service = services.system_service
        _container.resolved_pool_override_service = services.pool_override_service
        _container.resolved_admissibility_default = services.admissibility_default
        _container.resolved_settlement_composition = services.settlement_composition
        _container.resolved_contact_exchange = services.contact_exchange
        _container.resolved_introduction_delivery = services.introduction_delivery
        logger.info("[STARTUP] Singletons initialized")
        await _run_startup_tasks(
            registry=services.registry,
            domain=services.domain,
        )
        logger.info("[STARTUP] Background tasks started")
    except BaseException:
        _container.clear_lifespan_state(registry=services.registry)
        raise


async def _stop_vm_services(services: VmStorefrontServices) -> None:
    if services.settlement_composition.payments_coordinator is not None:
        await services.settlement_composition.payments_coordinator.stop()
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
from market_storefront.controllers.introductions_controller import (  # noqa: E402
    router as introductions_router,
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

# Registers every loop's step, which the lifecycle routes run; startup registers
# each loop's timer over the same step and starts it.
import market_storefront.lifecycle_steps  # noqa: E402,F401


def build_vm_storefront_app(
    *,
    registry: StorefrontDomainRegistry,
    seams: VmCompositionSeams = VmCompositionSeams(),
):
    """Build the VM HTTP application from one explicit frozen registry.

    ``seams`` defaults to production's service-peer trust and startup refusal.
    """

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
            seams=seams,
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
                    introductions_router,
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
