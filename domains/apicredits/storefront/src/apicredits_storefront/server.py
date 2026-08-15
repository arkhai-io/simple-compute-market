"""API-credits storefront FastAPI application.

Mirrors the VM storefront's shape: ``FastAPI(lifespan=lifespan)``
resolves singletons and starts the background tasks; controllers mount
after the module-level app exists; admin auth via Security() on
individual routers.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from functools import partial

from fastapi import FastAPI

import apicredits_storefront.container as _container
from apicredits_storefront.domain_runtime import (
    fulfill_api_credit_settlement,
    get_market_domain_contract,
    persist_api_credit_settlement_outcome,
    prepare_api_credit_settlement,
    reserve_api_credit_settlement,
)
from apicredits_storefront.utils.config import AGENT_ID, BASE_URL_OVERRIDE, settings
from apicredits_storefront.utils.sqlite_client import get_sqlite_client
from apicredits_storefront.negotiation_runtime import (
    build_api_credit_negotiation_runtime,
)
from core_storefront.openapi import install_marketplace_identity_openapi
from core_storefront.services.negotiation_service import NegotiationService
from core_storefront.stage_log import set_stage_event_db_path, stage_event
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


@asynccontextmanager
async def lifespan(_: FastAPI):
    from apicredits_storefront.services import alkahest_service
    from apicredits_storefront.services.listing_service import ListingService
    from apicredits_storefront.services.system_service import SystemService
    from apicredits_storefront.startup import _startup_tasks
    from apicredits_storefront.services.fulfillment_service import (
        build_api_credit_failure_policy,
    )
    from apicredits_storefront.utils.config import (
        CHAINS,
        resolve_admin_identities,
        resolve_registry_authorities,
        resolve_evm_wallet,
        resolve_identity_signer,
    )
    from market_alkahest import AlkahestConditionalEscrowClient
    from market_settlement_runtime import (
        SettlementJobCoordinator,
        SettlementRuntime,
        SettlementServicingWorker,
        SettlementSQLiteRepository,
    )

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
    alkahest_clients = alkahest_service.build_clients()
    negotiation_runtime = build_api_credit_negotiation_runtime(
        get_market_domain_contract()
    )
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

    _container.resolved_sqlite_client = sqlite_client
    _container.resolved_alkahest_clients = alkahest_clients
    _container.resolved_settlement_repository = settlement_repository
    _container.resolved_settlement_runtime = settlement_runtime
    _container.resolved_settlement_worker = settlement_worker
    _container.resolved_settlement_coordinator = settlement_coordinator
    _container.resolved_marketplace_signer = marketplace_signer
    _container.resolved_negotiation_runtime = negotiation_runtime
    _container.resolved_failure_policy = build_api_credit_failure_policy()
    _container.resolved_listing_service = ListingService(
        sqlite_client=sqlite_client,
        seller_principal=marketplace_signer.identity,
    )
    _container.resolved_negotiation_service = NegotiationService(
        sqlite_client=sqlite_client,
        continue_negotiation=negotiation_runtime.continue_negotiation,
        stage_event=stage_event,
    )
    _container.resolved_system_service = SystemService(
        sqlite_client=sqlite_client,
        agent_id=AGENT_ID,
    )

    logger.info("[STARTUP] Singletons initialized")
    await _startup_tasks()
    logger.info("[STARTUP] Background tasks started")

    yield

    logger.info("[SHUTDOWN] API-credits storefront shutting down")


app = FastAPI(
    title="Arkhai API-Credits Storefront",
    description=(
        "Seller-side storefront for the Arkhai API-credits marketplace.\n\n"
        "Admin and authenticated endpoints require the shared scheme-tagged "
        "marketplace request-signature version 2 headers."
    ),
    version="1.0.0",
    lifespan=lifespan,
    root_path=settings.gateway.root_path,
    swagger_ui_parameters={"persistAuthorization": True},
)
app.state.market_domain = get_market_domain_contract()
app.middleware("http")(authenticate_response)


install_marketplace_identity_openapi(app, root_path=settings.gateway.root_path)

# Controller imports after module-level app exists.
from apicredits_storefront.controllers.system_controller import router as system_router  # noqa: E402
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

app.include_router(system_router)
app.include_router(listings_router)
app.include_router(negotiate_router)
app.include_router(negotiations_router)
app.include_router(settle_router)
app.include_router(admin_settle_router)
