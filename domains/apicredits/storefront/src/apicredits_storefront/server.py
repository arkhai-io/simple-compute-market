"""API-credits storefront FastAPI application.

Mirrors the VM storefront's shape: ``FastAPI(lifespan=lifespan)``
resolves singletons and starts the background tasks; controllers mount
after the module-level app exists; admin auth via Security() on
individual routers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from typing import Any

from arkhai_api_selling.lifecycle import (
    ListingSeed,
    loop_controller,
    seed_site,
    start_background_tasks,
)
from arkhai_api_selling.listings import ListingService
from arkhai_api_selling.negotiation import build_negotiation_runtime
from arkhai_api_selling.quota_listing import build_listing_source_check, registration
from arkhai_api_selling.system import SystemService
from arkhai_api_selling.settlement_composition import (
    fulfill_settlement,
    persist_settlement_outcome,
    prepare_settlement,
    reserve_settlement,
)
from core_storefront.app_composition import StorefrontAppConfig
from core_storefront.escrow_identity import backfill_escrow_obligation_records
from core_storefront.domain_registry import (
    StorefrontDomainRegistry,
)
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import set_stage_event_db_path, stage_event
from market_alkahest import ALKAHEST_MECHANISM_ID
from market_core import MarketDomainContract
from market_settlement_runtime import SettlementJobCoordinator
from market_storefront_kit import (
    AlkahestChain,
    AlkahestClientPolicy,
    StorefrontComposition,
    StorefrontRouteHooks,
    StorefrontServiceHooks,
    build_alkahest_clients,
    build_composed_storefront_app,
)

import apicredits_storefront.container as _container
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.middleware.response_auth import authenticate_response
from apicredits_storefront.services.fulfillment_service import (
    build_api_credit_failure_policy,
)
from apicredits_storefront.services.keys_lookup import lookup_key_record
from apicredits_storefront.settlement_stages import AlkahestEscrowAcceptance
from apicredits_storefront.startup import preflight_credits_service
from apicredits_storefront.startup_refusal import require_startable_storefront
from apicredits_storefront.settlement_composition import (
    SELLER_STAGES,
    ApiCreditsSettlementComposition,
    build_api_credit_settlement_composition,
    build_storefront_settlement_registry,
    SEED_ESCROW_SETTINGS,
    require_api_credit_release_model,
    seed_accepted_escrows,
)
from apicredits_storefront.utils.config import (
    BASE_URL_OVERRIDE,
    CHAINS,
    capacity_sites,
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


@dataclass(frozen=True, slots=True)
class ApiCreditsStorefrontServices:
    """Lifespan-owned API-credit services bound to one domain contract."""

    domain: MarketDomainContract
    sqlite_client: Any
    marketplace_signer: Any
    alkahest_clients: dict[str, Any]
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


def build_api_credit_negotiation_runtime(
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
        stages=SELLER_STAGES,
        round_settings=round_settings,
        capacity_client=lambda repository: _container.QUOTA_CAPACITY.client(lambda: repository),
        key_lookup=lookup_key_record,
        storefront_is_paused=lambda: _container.trading_pause.paused,
        listing_source_check=listing_source_check
        or build_listing_source_check(
            _container.SELLING_CONTRIBUTIONS,
            lambda repository: _container.QUOTA_CAPACITY.client(lambda: repository),
        ),
        escrow=AlkahestEscrowAcceptance(),
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
        escrow_mechanism=ALKAHEST_MECHANISM_ID,
        release_conditions=settlement_composition.release_conditions,
    )


def _alkahest_check() -> dict[str, str]:
    configured = _container.configured_chain_names()
    return {"alkahest": ",".join(sorted(configured)) if configured else "unconfigured"}


def build_system_service(sqlite_client: Any) -> SystemService:
    return SystemService(
        sqlite_client=sqlite_client,
        settings=system_settings,
        mechanism_checks=_alkahest_check,
        signer=lambda: _container.resolved_marketplace_signer,
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
        accepted_escrows=seed_accepted_escrows,
        settlement_settings=SEED_ESCROW_SETTINGS,
        # The credits authority seeds its quota pool as `default`.
        pool_id="default",
    )


async def _seed_demo_listing() -> None:
    await listing_seed().run(seed_settings())


async def _backfill_escrow_records() -> None:
    runtime = _container.resolved_settlement_runtime
    signer = _container.resolved_marketplace_signer
    if runtime is None or signer is None:
        return
    backfilled = await backfill_escrow_obligation_records(
        sqlite_client=_container.resolved_sqlite_client,
        settlement_runtime=runtime,
        local_principal=signer.identity,
    )
    if backfilled:
        logger.info("[STARTUP] Backfilled %d legacy escrow obligation records", backfilled)


async def _startup_tasks(
    *, domain: MarketDomainContract, capacity_runtime: Any | None = None
) -> None:
    """Start the background tasks for the exact app-selected domain."""
    if _container.resolved_market_domain is not domain:
        raise RuntimeError(
            "API-credit startup is not bound to the app-selected "
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
        preflight=preflight_credits_service,
        seed=_seed_demo_listing,
        startup_steps=(_backfill_escrow_records,),
        capacity_runtime=capacity_runtime,
    )


def _build_alkahest_clients() -> dict[str, Any]:
    private_key = (settings.wallet.private_key or "").strip()
    missing = () if private_key else ("wallet.private_key",)
    return build_alkahest_clients(
        AlkahestClientPolicy(
            private_key=private_key,
            chains=tuple(
                AlkahestChain(
                    name=name,
                    rpc_url=chain.rpc_url,
                    address_config_path=chain.alkahest_address_config_path,
                )
                for name, chain in CHAINS.items()
            ),
            missing_requirements=missing,
            warn_if_no_chains=True,
        ),
        logger=logger,
    )


def _build_api_credit_services(
    domain: MarketDomainContract,
) -> ApiCreditsStorefrontServices:
    # Before anything is constructed: a renamed setting, a capacity
    # configuration that cannot be read, or an Alkahest release model this
    # storefront cannot deliver, stops startup.
    require_startable_storefront()
    require_api_credit_release_model()
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
    if alkahest_enabled:
        alkahest_clients = _build_alkahest_clients()
    else:
        alkahest_clients = {}
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
            prepare_settlement,
            SELLER_STAGES,
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
        fulfill=partial(fulfill_settlement, SELLER_STAGES),
        persist_outcome=partial(
            persist_settlement_outcome,
            sqlite_client,
        ),
        wake_servicing=settlement_worker.wake,
    )
    return ApiCreditsStorefrontServices(
        domain=domain,
        sqlite_client=sqlite_client,
        marketplace_signer=marketplace_signer,
        alkahest_clients=alkahest_clients,
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


async def _start_api_credit_services(
    services: ApiCreditsStorefrontServices,
) -> None:

    _container.resolved_market_domain = services.domain
    _container.resolved_sqlite_client = services.sqlite_client
    _container.resolved_alkahest_clients = services.alkahest_clients
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
    _container.resolved_negotiation_runtime = services.negotiation_runtime
    _container.resolved_negotiation_service = services.negotiation_service
    _container.resolved_system_service = services.system_service
    loops = loop_controller()
    _container.STOREFRONT_LOOPS.register_steps(loops)
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

    return StorefrontDomainRegistry((registration(_container.SELLING_CONTRIBUTIONS, domain),))


def build_api_credits_storefront_app(
    *,
    registry: StorefrontDomainRegistry,
) -> Any:
    """Build the API-credit app from one frozen domain registration."""

    registration = registry.resolve_mode("api_credits")
    domain = registration.contract

    def build_services(selected: MarketDomainContract) -> ApiCreditsStorefrontServices:
        if selected is not domain:
            raise RuntimeError(
                "storefront kit supplied a domain outside the API-credit registration"
            )
        return _build_api_credit_services(selected)

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
