"""Inference storefront FastAPI application.

The lifespan resolves the container's singletons and starts the background tasks.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

import injected_time
import uvicorn
from arkhai_api_selling.lifecycle import (
    ListingSeed,
    loop_controller,
    seed_site,
    start_background_tasks,
    stop_background_tasks,
)
from arkhai_api_selling.listings import ListingService
from arkhai_api_selling.migrations import require_compatible_storefront_database
from arkhai_api_selling.negotiation import build_negotiation_runtime
from arkhai_api_selling.persistence import refuse_unbound_listings
from arkhai_api_selling.quota_listing import build_listing_source_check, registration
from arkhai_api_selling.system import SystemService
from arkhai_api_selling.settlement_composition import (
    SellingSettlementComposition,
    fulfill_settlement,
    persist_settlement_outcome,
    prepare_settlement,
    reserve_settlement,
)
from arkhai_inference.listings import INFERENCE_OFFERING_MODE
from core_storefront.app_composition import StorefrontAppConfig
from core_storefront.domain_registry import (
    StorefrontDomainRegistry,
)
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import set_stage_event_db_path, stage_event
from market_alkahest import (
    ALKAHEST_CONFIG_KEY,
    AlkahestChainProbe,
    JsonRpcCall,
    ProbedChain,
    json_rpc_call,
)
from market_core import MarketDomainContract
from market_settlement_runtime import SettlementJobCoordinator
from market_storefront_kit import (
    AlkahestChain,
    AlkahestClientPolicy,
    StorefrontComposition,
    StorefrontRouteHooks,
    StorefrontServiceHooks,
    StorefrontTimeRouteService,
    alkahest_client_constructor,
    announce_time_source,
    build_composed_storefront_app,
    install_time_source,
)

import inference_storefront.container as _container
from inference_storefront.container import (
    get_sqlite_client,
    mechanism_health,
    mechanism_startup_steps,
)
from inference_storefront.domain_runtime import get_market_domain_contract
from inference_storefront.migrate import CHAIN
from inference_storefront.services.fulfillment_service import (
    build_inference_failure_policy,
)
from inference_storefront.services.keys_lookup import lookup_key_record
from inference_storefront.startup_refusal import require_startable_storefront
from inference_storefront.settlement_composition import (
    build_inference_settlement_composition,
    build_storefront_settlement_registry,
    validate_mechanism_configuration,
)
from inference_storefront.utils.config import (
    BASE_URL_OVERRIDE,
    CHAINS,
    chain_address_books,
    capacity_sites,
    configured_time_source,
    resolve_admin_identities,
    resolve_identity_signer,
    resolve_registry_authorities,
    round_settings,
    seed_settings,
    settings,
    settlement_config_mapping,
    settlement_publication_defaults,
    system_settings,
)

logger = logging.getLogger(__name__)

def run_serve(host: str = "0.0.0.0", port: int | None = None) -> None:
    """Launch uvicorn. Called by ``inference-storefront serve``."""
    resolved_port = port if port is not None else settings.port
    uvicorn.run(
        app,
        host=host,
        port=resolved_port,
        root_path=settings.gateway.root_path,
    )


AlkahestClientConstructor = Callable[
    [AlkahestClientPolicy], Callable[[str], Any] | None
]


@dataclass(frozen=True, slots=True)
class InferenceCompositionSeams:
    """What the composition root reaches its Alkahest chains through.

    The defaults are production's: the SDK's per-chain client construction and
    JSON-RPC over each chain's ``rpc_url``. A test of the root's wiring supplies
    compatible objects instead of patching the module.
    """

    alkahest_client_constructor: AlkahestClientConstructor = alkahest_client_constructor
    alkahest_json_rpc: JsonRpcCall = json_rpc_call


@dataclass(frozen=True, slots=True)
class InferenceStorefrontServices:
    """Lifespan-owned inference services bound to one domain contract."""

    domain: MarketDomainContract
    sqlite_client: Any
    marketplace_signer: Any
    alkahest_clients: dict[str, Any]
    alkahest_chain_probe: AlkahestChainProbe | None
    settlement_repository: Any
    settlement_runtime: Any
    settlement_worker: Any
    settlement_coordinator: Any
    settlement_composition: SellingSettlementComposition
    issuance_evidence_service: Any
    private_result_repository: Any
    failure_policy: Any
    listing_service: Any
    negotiation_runtime: Any
    negotiation_service: Any
    system_service: Any


def build_inference_negotiation_runtime(
    domain: MarketDomainContract,
    *,
    accepted_obligation_dispatch: Any = None,
    settlement_artifacts_builder: Any = None,
    seller_round_hook: Any = None,
    listing_source_check: Any = None,
) -> Any:
    return build_negotiation_runtime(
        _container.SELLING_CONTRIBUTIONS,
        domain,
        stages=_container.SELLER_STAGES,
        round_settings=round_settings,
        capacity_client=lambda repository: _container.QUOTA_CAPACITY.client(lambda: repository),
        key_lookup=lookup_key_record,
        storefront_is_paused=lambda: _container.trading_pause.paused,
        listing_source_check=listing_source_check
        or build_listing_source_check(
            _container.SELLING_CONTRIBUTIONS,
            lambda repository: _container.QUOTA_CAPACITY.client(lambda: repository),
        ),
        escrow=_container.ALKAHEST_STAGE.escrow_acceptance,
        seller_round_hook=seller_round_hook,
        accepted_obligation_dispatch=accepted_obligation_dispatch,
        settlement_artifacts_builder=settlement_artifacts_builder,
    )


def build_listing_service(
    domain: MarketDomainContract,
    *,
    sqlite_client: Any,
    seller_principal: Any,
    settlement_composition: Any,
) -> ListingService:
    return ListingService(
        _container.SELLING_CONTRIBUTIONS,
        sqlite_client=sqlite_client,
        seller_principal=seller_principal,
        settlement_composition=settlement_composition,
        domain=domain,
        capacity=_container.QUOTA_CAPACITY,
        publish=lambda listing: _container.QUOTA_PUBLICATION.publish(sqlite_client, listing),
        close=lambda listing_id: _container.QUOTA_PUBLICATION.close(sqlite_client, listing_id),
        settlement_defaults=settlement_publication_defaults,
        storefront_url=BASE_URL_OVERRIDE,
        escrow_mechanism=_container.ALKAHEST_STAGE.mechanism,
        release_conditions=partial(
            _container.ALKAHEST_STAGE.release_conditions, settlement_composition
        ),
    )


def build_system_service(sqlite_client: Any) -> SystemService:
    return SystemService(
        sqlite_client=sqlite_client,
        settings=system_settings,
        mechanism_checks=lambda: mechanism_health(_container.SELLER_STAGES),
        signer=lambda: _container.resolved_marketplace_signer,
        settlement_composition=lambda: _container.resolved_settlement_composition,
    )


def listing_seed() -> ListingSeed:
    return ListingSeed(
        _container.SELLING_CONTRIBUTIONS,
        sqlite_client=lambda: _container.resolved_sqlite_client,
        listing_service=lambda: _container.resolved_listing_service,
        signer=lambda: _container.resolved_marketplace_signer,
        site=lambda: seed_site(
            capacity_sites()[0], str(settings.get("capacity.seed_site", "") or "")
        ),
        accepted_escrows=_container.ALKAHEST_STAGE.seed_accepted_escrows,
        settlement_settings=_container.ALKAHEST_STAGE.seed_escrow_settings,
        # The inference authority seeds its quota pool as `default`.
        pool_id="default",
    )


async def _startup_tasks(
    *, domain: MarketDomainContract, capacity_runtime: Any | None = None
) -> None:
    """Start the background tasks for the exact app-selected domain."""
    if _container.resolved_market_domain is not domain:
        raise RuntimeError(
            "inference startup is not bound to the app-selected "
            "market-domain contract object"
        )
    loops = _container.resolved_loop_controller
    if loops is None:
        raise RuntimeError("loop controller is not initialized")
    if _container.resolved_settlement_worker is None:
        raise RuntimeError("settlement servicing worker is not initialized")
    await start_background_tasks(
        _container.STOREFRONT_LOOPS,
        loops,
        sqlite_client=_container.resolved_sqlite_client,
        storefront_url=BASE_URL_OVERRIDE or f"http://localhost:{settings.port}",
        startup_steps=mechanism_startup_steps(_container.SELLER_STAGES),
        capacity_runtime=capacity_runtime,
    )


def _alkahest_client_policy() -> AlkahestClientPolicy:
    private_key = (settings.wallet.private_key or "").strip()
    missing = () if private_key else ("wallet.private_key",)
    books = chain_address_books()
    return AlkahestClientPolicy(
        private_key=private_key,
        chains=tuple(
            AlkahestChain(
                name=name,
                rpc_url=chain.rpc_url,
                address_book=books[name],
            )
            for name, chain in CHAINS.items()
        ),
        missing_requirements=missing,
    )


def _build_alkahest_chain_probe(
    section: Any,
    alkahest_clients: dict[str, Any],
    *,
    constructor: AlkahestClientConstructor,
    json_rpc: JsonRpcCall,
) -> AlkahestChainProbe:
    """The chain probe over every configured chain, owning ``alkahest_clients``.

    ``constructor`` and ``json_rpc`` are its two boundaries, the SDK and the
    chain's JSON-RPC endpoint.
    """
    books = chain_address_books()
    return AlkahestChainProbe(
        [
            ProbedChain.from_config(name, chain, address_book=books[name])
            for name, chain in CHAINS.items()
        ],
        build_client=constructor(_alkahest_client_policy()),
        clients=alkahest_clients,
        interval_seconds=section.probe_interval_seconds,
        rpc_timeout_seconds=section.rpc_timeout_seconds,
        json_rpc=json_rpc,
    )


def _build_inference_services(
    domain: MarketDomainContract,
    seams: InferenceCompositionSeams = InferenceCompositionSeams(),
) -> InferenceStorefrontServices:
    require_startable_storefront()
    validate_mechanism_configuration()
    marketplace_signer = resolve_identity_signer()
    resolve_admin_identities()
    if settings.enable_registry_discovery:
        resolve_registry_authorities()
    settlement_registry = build_storefront_settlement_registry()
    settlement_config = settlement_registry.resolve(
        settlement_config_mapping(),
        role="seller",
    )
    # A configured section services the deals accepted under it whether or not
    # it publishes, so its chain probe is composed either way. The probe owns
    # the client map, empty until its first step constructs each client,
    # bounded: a websocket client connects while it is built, and startup must
    # not wait on a chain. Every consumer below is handed this one dict, which
    # the probe updates in place.
    alkahest_section = settlement_config.mechanism_config(ALKAHEST_CONFIG_KEY)
    alkahest_clients: dict[str, Any] = {}
    alkahest_chain_probe: AlkahestChainProbe | None = None
    if alkahest_section is not None:
        alkahest_chain_probe = _build_alkahest_chain_probe(
            alkahest_section,
            alkahest_clients,
            constructor=seams.alkahest_client_constructor,
            json_rpc=seams.alkahest_json_rpc,
        )
    # `inference-storefront-migrate` builds the database and nothing here
    # issues DDL, so one not exactly at the chain is refused before it is
    # opened. The unbound-listing refusal reads data, so it follows the check.
    require_compatible_storefront_database(CHAIN, settings.db_path)
    refuse_unbound_listings(settings.db_path, _container.SELLING_CONTRIBUTIONS)
    sqlite_client = get_sqlite_client()
    set_stage_event_db_path(sqlite_client.db_path)
    failure_policy = build_inference_failure_policy()
    settlement_composition = build_inference_settlement_composition(
        domain=domain,
        sqlite_client=sqlite_client,
        chain_clients=alkahest_clients,
        marketplace_signer=marketplace_signer,
        failure_policy=failure_policy,
        chain_probe=alkahest_chain_probe,
    )
    negotiation_runtime = build_inference_negotiation_runtime(
        domain,
        accepted_obligation_dispatch=(
            settlement_composition.accepted_obligation_dispatch()
        ),
        settlement_artifacts_builder=settlement_composition.accepted_settlement_artifacts,
    )
    settlement_runtime = settlement_composition.runtime
    settlement_worker = settlement_composition.worker
    settlement_repository = settlement_composition.repository
    settlement_coordinator = SettlementJobCoordinator(
        settlement_runtime,
        prepare=partial(
            prepare_settlement,
            _container.SELLER_STAGES,
            sqlite_client=sqlite_client,
            local_principal=marketplace_signer.identity,
            composition=settlement_composition,
        ),
        reserve_start=partial(
            reserve_settlement,
            sqlite_client,
            settlement_runtime=settlement_runtime,
            wake_servicing=settlement_worker.wake,
        ),
        fulfill=partial(fulfill_settlement, _container.SELLER_STAGES),
        persist_outcome=partial(
            persist_settlement_outcome,
            sqlite_client,
        ),
        wake_servicing=settlement_worker.wake,
    )
    return InferenceStorefrontServices(
        domain=domain,
        sqlite_client=sqlite_client,
        marketplace_signer=marketplace_signer,
        alkahest_clients=alkahest_clients,
        alkahest_chain_probe=alkahest_chain_probe,
        settlement_repository=settlement_repository,
        settlement_runtime=settlement_runtime,
        settlement_worker=settlement_worker,
        settlement_coordinator=settlement_coordinator,
        settlement_composition=settlement_composition,
        issuance_evidence_service=settlement_composition.evidence_service,
        private_result_repository=settlement_composition.private_results,
        failure_policy=failure_policy,
        listing_service=build_listing_service(
            domain,
            sqlite_client=sqlite_client,
            seller_principal=marketplace_signer.identity,
            settlement_composition=settlement_composition,
        ),
        negotiation_runtime=negotiation_runtime,
        negotiation_service=NegotiationService(
            sqlite_client=sqlite_client,
            continue_negotiation=negotiation_runtime.continue_negotiation,
            stage_event=stage_event,
        ),
        system_service=build_system_service(sqlite_client),
    )


async def _start_inference_services(
    services: InferenceStorefrontServices,
) -> None:

    _container.resolved_market_domain = services.domain
    _container.resolved_sqlite_client = services.sqlite_client
    _container.resolved_alkahest_chain_probe = services.alkahest_chain_probe
    _container.resolved_settlement_repository = services.settlement_repository
    _container.resolved_settlement_runtime = services.settlement_runtime
    _container.resolved_settlement_worker = services.settlement_worker
    _container.resolved_settlement_coordinator = services.settlement_coordinator
    _container.resolved_settlement_composition = services.settlement_composition
    _container.resolved_issuance_evidence_service = services.issuance_evidence_service
    _container.resolved_private_result_repository = services.private_result_repository
    _container.resolved_marketplace_signer = services.marketplace_signer
    _container.resolved_failure_policy = services.failure_policy
    _container.resolved_listing_service = services.listing_service
    # The seed is created by its loop step, never here: the authority it
    # registers with, or a mechanism it uses, may not have been reached yet.
    _container.resolved_listing_seed = listing_seed().progress(seed_settings())
    _container.resolved_negotiation_runtime = services.negotiation_runtime
    _container.resolved_negotiation_service = services.negotiation_service
    _container.resolved_system_service = services.system_service
    loops = loop_controller()
    _container.STOREFRONT_LOOPS.register_steps(loops)
    _container.resolved_loop_controller = loops
    # This storefront services no Arkhai payments section.
    announce_time_source(injected_time.installed(), payments_livemode=False, logger=logger)
    logger.info("[STARTUP] Singletons initialized")
    await _startup_tasks(domain=services.domain)
    logger.info("[STARTUP] Background tasks started")


async def _stop_inference_services(
    services: InferenceStorefrontServices,
) -> None:
    await stop_background_tasks(_container.resolved_loop_controller)
    _container.clear_lifespan_state(domain=services.domain)
    _container.resolved_negotiation_runtime = None
    logger.info("[SHUTDOWN] inference storefront shutting down")


from inference_storefront.controllers.lifecycle_controller import (  # noqa: E402
    router as lifecycle_router,
)
from inference_storefront.controllers.listings_controller import (  # noqa: E402
    router as listings_router,
)
from inference_storefront.controllers.negotiate_controller import (  # noqa: E402
    router as negotiate_router,
)
from inference_storefront.controllers.negotiations_controller import (  # noqa: E402
    router as negotiations_router,
)
from inference_storefront.controllers.settle_controller import (  # noqa: E402
    admin_settle_router,
)
from inference_storefront.controllers.settle_controller import (  # noqa: E402
    router as settle_router,
)
from inference_storefront.controllers.settle_controller import (  # noqa: E402
    settlements_router,
)
from inference_storefront.controllers.system_controller import (  # noqa: E402
    router as system_router,
)
from inference_storefront.controllers.trading_pause_controller import (  # noqa: E402
    router as trading_pause_router,
)
from inference_storefront.controllers.time_controller import (  # noqa: E402
    router as time_router,
)


def build_inference_storefront_registry(
    *,
    domain: MarketDomainContract,
) -> StorefrontDomainRegistry:
    """Build the explicit one-registration inference storefront registry."""

    return StorefrontDomainRegistry((registration(_container.SELLING_CONTRIBUTIONS, domain),))


def build_inference_storefront_app(
    *,
    registry: StorefrontDomainRegistry,
    seams: InferenceCompositionSeams = InferenceCompositionSeams(),
) -> Any:
    """Build the inference app from one frozen domain registration.

    ``seams`` defaults to production's Alkahest client construction and chain
    transport. The time-setting route is mounted only when the process's
    installed source is injected time.
    """

    registration = registry.resolve_mode(INFERENCE_OFFERING_MODE)
    domain = registration.contract

    def build_services(selected: MarketDomainContract) -> InferenceStorefrontServices:
        if selected is not domain:
            raise RuntimeError(
                "storefront kit supplied a domain outside the inference registration"
            )
        return _build_inference_services(selected, seams)

    return build_composed_storefront_app(
        StorefrontComposition(
            registry=registry,
            binding=registration.binding,
            domain=domain,
            app=StorefrontAppConfig(
                title="Arkhai Inference Storefront",
                description=(
                    "Seller-side storefront for the Arkhai inference "
                    "marketplace.\n\n"
                    "Admin and authenticated endpoints require the shared "
                    "scheme-tagged marketplace request-signature version 2 headers."
                ),
                version="1.0.0",
                root_path=settings.gateway.root_path,
                swagger_ui_parameters={"persistAuthorization": True},
            ),
            services=StorefrontServiceHooks(
                build=build_services,
                start=_start_inference_services,
                stop=_stop_inference_services,
            ),
            routes=StorefrontRouteHooks(
                routers=(
                    system_router,
                    listings_router,
                    negotiate_router,
                    negotiations_router,
                    settle_router,
                    settlements_router,
                    admin_settle_router,
                    lifecycle_router,
                    trading_pause_router,
                    *((time_router,) if StorefrontTimeRouteService().mounted else ()),
                ),
                middleware=(_container.AUTH.sign_responses,),
            ),
        )
    )


# Installed before the application is built: `[Time] source` decides whether
# the time-setting route is mounted.
install_time_source(configured_time_source())
app = build_inference_storefront_app(
    registry=build_inference_storefront_registry(
        domain=get_market_domain_contract(),
    )
)
