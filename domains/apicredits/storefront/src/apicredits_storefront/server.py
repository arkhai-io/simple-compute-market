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

from core_storefront.app_composition import StorefrontAppConfig

import apicredits_storefront.container as _container
from apicredits_storefront.domain_runtime import (
    fulfill_api_credit_settlement,
    get_market_domain_contract,
    persist_api_credit_settlement_outcome,
    prepare_api_credit_settlement,
    reserve_api_credit_settlement,
)
from apicredits_storefront.services.fulfillment_service import (
    build_api_credit_failure_policy,
)
from apicredits_storefront.services.listing_service import ListingService
from apicredits_storefront.services.system_service import SystemService
from apicredits_storefront.startup import _startup_tasks
from apicredits_storefront.utils.config import (
    AGENT_ID,
    BASE_URL_OVERRIDE,
    CHAINS,
    resolve_admin_identities,
    resolve_evm_wallet,
    resolve_identity_signer,
    resolve_registry_authorities,
    settings,
)
from apicredits_storefront.utils.sqlite_client import get_sqlite_client
from apicredits_storefront.utils.sync_negotiation import continue_sync_negotiation
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import set_stage_event_db_path, stage_event
from market_core import MarketDomainContract
from market_storefront_kit import (
    AlkahestChain,
    AlkahestClientPolicy,
    StorefrontComposition,
    StorefrontRouteHooks,
    StorefrontServiceHooks,
    build_alkahest_clients,
    build_composed_storefront_app,
)
from market_alkahest import AlkahestConditionalEscrowClient
from market_settlement_runtime import (
    SettlementJobCoordinator,
    SettlementRuntime,
    SettlementServicingWorker,
    SettlementSQLiteRepository,
)
from apicredits_storefront.middleware.response_auth import authenticate_response

logger = logging.getLogger(__name__)

_GLOBALLY_PAUSED: bool = False


def is_globally_paused() -> bool:
    return _GLOBALLY_PAUSED


def _set_globally_paused(value: bool) -> None:
    global _GLOBALLY_PAUSED
    _GLOBALLY_PAUSED = value


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
    failure_policy: Any
    listing_service: Any
    negotiation_service: Any
    system_service: Any


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
    marketplace_signer = resolve_identity_signer()
    resolve_admin_identities()
    if settings.enable_registry_discovery:
        resolve_registry_authorities()
    resolve_evm_wallet()
    sqlite_client = get_sqlite_client(
        local_listing_principal=marketplace_signer.identity,
        expected_legacy_sellers=(BASE_URL_OVERRIDE,),
    )
    set_stage_event_db_path(sqlite_client.db_path)
    alkahest_clients = _build_alkahest_clients()
    settlement_repository = SettlementSQLiteRepository(
        sqlite_client.db_path,
        apply_migrations=False,
    )
    escrow_client = AlkahestConditionalEscrowClient(
        get_client=lambda chain: alkahest_clients.get(chain or ""),
        chain_config_paths={
            name: chain.alkahest_address_config_path for name, chain in CHAINS.items()
        },
        default_chain=next(iter(CHAINS), None),
    )
    settlement_runtime = SettlementRuntime(
        settlement_repository,
        {"alkahest.v1": escrow_client},
    )
    settlement_worker = SettlementServicingWorker(
        settlement_runtime,
        settlement_repository,
        worker_id=f"{AGENT_ID}:api-credit-settlement",
        interval_seconds=float(settings.get("claims_sweep_interval", 30)),
        on_event=lambda event, fields: stage_event(
            "settlement",
            event,
            **fields,
        ),
    )
    settlement_coordinator = SettlementJobCoordinator(
        settlement_runtime,
        prepare=partial(
            prepare_api_credit_settlement,
            sqlite_client=sqlite_client,
            local_principal=marketplace_signer.identity,
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
        settlement_repository=settlement_repository,
        settlement_runtime=settlement_runtime,
        settlement_worker=settlement_worker,
        settlement_coordinator=settlement_coordinator,
        failure_policy=build_api_credit_failure_policy(),
        listing_service=ListingService(
            sqlite_client=sqlite_client,
            seller_principal=marketplace_signer.identity,
        ),
        negotiation_service=NegotiationService(
            sqlite_client=sqlite_client,
            continue_negotiation=partial(
                continue_sync_negotiation,
                domain=domain,
            ),
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
    _container.resolved_settlement_repository = services.settlement_repository
    _container.resolved_settlement_runtime = services.settlement_runtime
    _container.resolved_settlement_worker = services.settlement_worker
    _container.resolved_settlement_coordinator = services.settlement_coordinator
    _container.resolved_marketplace_signer = services.marketplace_signer
    _container.resolved_failure_policy = services.failure_policy
    _container.resolved_listing_service = services.listing_service
    _container.resolved_negotiation_service = services.negotiation_service
    _container.resolved_system_service = services.system_service
    logger.info("[STARTUP] Singletons initialized")
    await _startup_tasks(domain=services.domain)
    logger.info("[STARTUP] Background tasks started")


async def _stop_api_credit_services(
    services: ApiCreditsStorefrontServices,
) -> None:
    _container.clear_lifespan_state(domain=services.domain)
    logger.info("[SHUTDOWN] API-credits storefront shutting down")





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
    router as settle_router,
)
from apicredits_storefront.controllers.system_controller import (  # noqa: E402
    router as system_router,
)

def build_api_credits_storefront_app(
    *,
    domain: MarketDomainContract,
) -> Any:
    """Build the API-credit app from immutable shared composition hooks."""

    return build_composed_storefront_app(
        StorefrontComposition(
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
                build=_build_api_credit_services,
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
                    admin_settle_router,
                ),
                middleware=(authenticate_response,),
            ),
        )
    )


app = build_api_credits_storefront_app(domain=get_market_domain_contract())
