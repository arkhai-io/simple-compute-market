"""API-credits storefront FastAPI application.

Mirrors the VM storefront's shape: ``FastAPI(lifespan=lifespan)``
resolves singletons and starts the background tasks; controllers mount
after the module-level app exists; admin auth via Security() on
individual routers.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from core_storefront.app_composition import StorefrontAppConfig
from core_storefront.domain_registry import (
    StorefrontDomainRegistry,
)
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import set_stage_event_db_path, stage_event
from market_alkahest import (
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
    alkahest_client_constructor,
    build_composed_storefront_app,
)

import apicredits_storefront.container as _container
from apicredits_storefront.domain_runtime import (
    fulfill_api_credit_settlement,
    get_market_domain_contract,
    persist_api_credit_settlement_outcome,
    prepare_api_credit_settlement,
    reserve_api_credit_settlement,
)
from apicredits_storefront.listing_binding import api_credit_registration
from apicredits_storefront.listing_seed import configured_listing_seed
from apicredits_storefront.middleware.response_auth import authenticate_response
from apicredits_storefront.negotiation_runtime import (
    build_api_credit_negotiation_runtime,
)
from apicredits_storefront.services.fulfillment_service import (
    build_api_credit_failure_policy,
)
from apicredits_storefront.services.listing_service import ListingService
from apicredits_storefront.services.system_service import SystemService
from apicredits_storefront.lifecycle_steps import (
    api_credit_loop_controller,
    register_api_credit_lifecycle_steps,
)
from apicredits_storefront.startup_refusal import require_startable_storefront
from apicredits_storefront.startup import _startup_tasks
from apicredits_storefront.settlement_composition import (
    ApiCreditsSettlementComposition,
    build_api_credit_settlement_composition,
    build_storefront_settlement_registry,
    require_coherent_release_model,
)
from apicredits_storefront.utils.config import (
    AGENT_ID,
    BASE_URL_OVERRIDE,
    CHAINS,
    chain_address_books,
    resolve_admin_identities,
    resolve_identity_signer,
    resolve_registry_authorities,
    settings,
    settlement_config_mapping,
)
from apicredits_storefront.utils.sqlite_client import get_sqlite_client

logger = logging.getLogger(__name__)

def run_serve(host: str = "0.0.0.0", port: int | None = None) -> None:
    """Launch uvicorn. Called by ``apicredits-storefront serve``."""
    import uvicorn

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
class ApiCreditCompositionSeams:
    """What the composition root reaches its Alkahest chains through.

    The defaults are production's: the SDK's per-chain client construction and
    JSON-RPC over each chain's ``rpc_url``. A test of the root's wiring supplies
    compatible objects instead of patching the module.
    """

    alkahest_client_constructor: AlkahestClientConstructor = alkahest_client_constructor
    alkahest_json_rpc: JsonRpcCall = json_rpc_call


@dataclass(frozen=True, slots=True)
class ApiCreditsStorefrontServices:
    """Lifespan-owned API-credit services bound to one domain contract."""

    domain: MarketDomainContract
    sqlite_client: Any
    marketplace_signer: Any
    alkahest_clients: dict[str, Any]
    alkahest_chain_probe: AlkahestChainProbe | None
    settlement_repository: Any
    settlement_runtime: Any
    settlement_worker: Any
    settlement_coordinator: Any
    settlement_composition: ApiCreditsSettlementComposition
    issuance_evidence_service: Any
    private_result_repository: Any
    failure_policy: Any
    listing_service: Any
    negotiation_runtime: Any
    negotiation_service: Any
    system_service: Any


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


def _build_api_credit_services(
    domain: MarketDomainContract,
    seams: ApiCreditCompositionSeams = ApiCreditCompositionSeams(),
) -> ApiCreditsStorefrontServices:
    # Before anything is constructed: a renamed or removed setting (the
    # retired credits-service preflight settings among them), an unset
    # `[credits].service_url`, a capacity configuration that cannot be read,
    # or a contradictory Alkahest release model stops startup. A coherent
    # model this storefront cannot deliver makes Alkahest unready instead.
    require_startable_storefront()
    require_coherent_release_model()
    marketplace_signer = resolve_identity_signer()
    resolve_admin_identities()
    if settings.enable_registry_discovery:
        resolve_registry_authorities()
    settlement_registry = build_storefront_settlement_registry()
    settlement_config = settlement_registry.resolve(
        settlement_config_mapping(),
        role="seller",
    )
    alkahest_section = settlement_config.mechanism_config("alkahest")
    alkahest_enabled = bool(
        alkahest_section is not None and getattr(alkahest_section, "enabled", False)
    )
    # The probe owns the client map, empty until its first step constructs each
    # client, bounded: a websocket client connects while it is built, and
    # startup must not wait on a chain. Every consumer below is handed this one
    # dict, which the probe updates in place.
    alkahest_clients: dict[str, Any] = {}
    alkahest_chain_probe: AlkahestChainProbe | None = None
    if alkahest_enabled:
        alkahest_chain_probe = _build_alkahest_chain_probe(
            alkahest_section,
            alkahest_clients,
            constructor=seams.alkahest_client_constructor,
            json_rpc=seams.alkahest_json_rpc,
        )
    sqlite_client = get_sqlite_client(
        local_listing_principal=marketplace_signer.identity,
        expected_legacy_sellers=(BASE_URL_OVERRIDE,),
    )
    set_stage_event_db_path(sqlite_client.db_path)
    failure_policy = build_api_credit_failure_policy()
    settlement_composition = build_api_credit_settlement_composition(
        domain=domain,
        sqlite_client=sqlite_client,
        alkahest_clients=alkahest_clients,
        marketplace_signer=marketplace_signer,
        failure_policy=failure_policy,
        chain_probe=alkahest_chain_probe,
    )
    negotiation_runtime = build_api_credit_negotiation_runtime(
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
            prepare_api_credit_settlement,
            sqlite_client=sqlite_client,
            local_principal=marketplace_signer.identity,
            composition=settlement_composition,
        ),
        reserve_start=partial(
            reserve_api_credit_settlement,
            sqlite_client,
            settlement_runtime=settlement_runtime,
            wake_servicing=settlement_worker.wake,
        ),
        fulfill=fulfill_api_credit_settlement,
        persist_outcome=partial(
            persist_api_credit_settlement_outcome,
            sqlite_client,
        ),
        wake_servicing=settlement_worker.wake,
    )
    return ApiCreditsStorefrontServices(
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
        listing_service=ListingService(
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
        system_service=SystemService(
            sqlite_client=sqlite_client,
            agent_id=AGENT_ID,
        ),
    )


async def _start_api_credit_services(
    services: ApiCreditsStorefrontServices,
) -> None:

    _container.resolved_market_domain = services.domain
    _container.resolved_sqlite_client = services.sqlite_client
    _container.resolved_alkahest_clients = services.alkahest_clients
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
    # The seed is created by its loop step, never here: a mechanism it uses
    # may not have been reached yet.
    _container.resolved_listing_seed = configured_listing_seed(
        listing_service=services.listing_service,
        signer=services.marketplace_signer,
        db=services.sqlite_client,
    )
    _container.resolved_negotiation_runtime = services.negotiation_runtime
    _container.resolved_negotiation_service = services.negotiation_service
    _container.resolved_system_service = services.system_service
    loops = api_credit_loop_controller()
    register_api_credit_lifecycle_steps(loops)
    _container.resolved_loop_controller = loops
    logger.info("[STARTUP] Singletons initialized")
    await _startup_tasks(domain=services.domain)
    logger.info("[STARTUP] Background tasks started")


async def _stop_api_credit_services(
    services: ApiCreditsStorefrontServices,
) -> None:
    _container.clear_lifespan_state(domain=services.domain)
    _container.resolved_negotiation_runtime = None
    logger.info("[SHUTDOWN] API-credits storefront shutting down")


from apicredits_storefront.controllers.lifecycle_controller import (  # noqa: E402
    router as lifecycle_router,
)
from apicredits_storefront.controllers.listings_controller import (  # noqa: E402
    router as listings_router,
)
from apicredits_storefront.controllers.negotiate_controller import (  # noqa: E402
    router as negotiate_router,
)
from apicredits_storefront.controllers.negotiations_controller import (  # noqa: E402
    router as negotiations_router,
)
from apicredits_storefront.controllers.settle_controller import (  # noqa: E402
    admin_settle_router,
)
from apicredits_storefront.controllers.settle_controller import (  # noqa: E402
    router as settle_router,
)
from apicredits_storefront.controllers.settle_controller import (  # noqa: E402
    settlements_router,
)
from apicredits_storefront.controllers.system_controller import (  # noqa: E402
    router as system_router,
)
from apicredits_storefront.controllers.trading_pause_controller import (  # noqa: E402
    router as trading_pause_router,
)


def build_api_credits_storefront_registry(
    *,
    domain: MarketDomainContract,
) -> StorefrontDomainRegistry:
    """Build the explicit one-registration API-credit storefront registry."""

    return StorefrontDomainRegistry((api_credit_registration(domain),))


def build_api_credits_storefront_app(
    *,
    registry: StorefrontDomainRegistry,
    seams: ApiCreditCompositionSeams = ApiCreditCompositionSeams(),
) -> Any:
    """Build the API-credit app from one frozen domain registration.

    ``seams`` defaults to production's Alkahest client construction and chain
    transport.
    """

    registration = registry.resolve_mode("api_credits")
    domain = registration.contract

    def build_services(selected: MarketDomainContract) -> ApiCreditsStorefrontServices:
        if selected is not domain:
            raise RuntimeError(
                "storefront kit supplied a domain outside the API-credit registration"
            )
        return _build_api_credit_services(selected, seams)

    return build_composed_storefront_app(
        StorefrontComposition(
            registry=registry,
            binding=registration.binding,
            domain=domain,
            app=StorefrontAppConfig(
                title="Arkhai API-Credits Storefront",
                description=(
                    "Seller-side storefront for the Arkhai API-credits "
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
                start=_start_api_credit_services,
                stop=_stop_api_credit_services,
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
                ),
                middleware=(authenticate_response,),
            ),
        )
    )


app = build_api_credits_storefront_app(
    registry=build_api_credits_storefront_registry(
        domain=get_market_domain_contract(),
    )
)
