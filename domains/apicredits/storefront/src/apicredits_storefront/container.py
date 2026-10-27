"""The storefront's dependency container.

The selling bundle and the parts composed over it — the capacity runtime,
publication, the seller stage table, the loops, authentication, and the route
services — are fixed for the process; the ``resolved_*`` services are set once
by the lifespan in ``server.py``, and each composed part reads them when a
request or cycle runs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from arkhai_api_selling.auth import StorefrontAuth
from arkhai_api_selling.capacity import QuotaCapacity
from arkhai_api_selling.contributions import (
    ConsumptionRule,
    IssuanceSubject,
    QuotaSource,
    SellingContributions,
)
from arkhai_api_selling.evidence_store import IssuanceEvidenceService, PrivateResultRepository
from arkhai_api_selling.lifecycle import ContributedLoop, StorefrontLoops
from arkhai_api_selling.listings import ListingService
from arkhai_api_selling.persistence import StorefrontSQLiteClient
from arkhai_api_selling.publication import QuotaPublication, RegistryPublication
from arkhai_api_selling.publish_route import PublishFromQuotaRequest as QuotaPublishRequest
from arkhai_api_selling.route_services import (
    ListingRoutes,
    NegotiateRoutes,
    NegotiationRoutes,
    SettleRoutes,
    SystemRoutes,
)
from arkhai_api_selling.system import SystemService
from arkhai_api_selling_alkahest.stage import AlkahestSellerStage
from arkhai_api_selling_arkhai_payments.stage import ArkhaiPaymentsSellerStage
from arkhai_apicredits.label import API_CREDITS_LABEL
from arkhai_apicredits.schema import API_CREDITS_SCHEMA_KIND, ApiCreditsListing
from core_storefront.escrow_identity import backfill_escrow_obligation_records
from core_storefront.multi_registry_client import MultiRegistryClient
from core_storefront.stage_log import stage_event
from market_alkahest import RECIPIENT_RELEASE
from market_core import SettlementStageTable
from market_identity import Identity
from market_storefront_kit import TradingPause

from apicredits_storefront.utils import config

if TYPE_CHECKING:
    from market_core import MarketDomainContract
    from core_storefront.services.negotiation_service import NegotiationService
    from market_negotiation_runtime import NegotiationRuntime
    from market_settlement_runtime import (
        FailurePolicy,
        SettlementJobCoordinator,
        SettlementRuntime,
        SettlementServicingWorker,
        SettlementSQLiteRepository,
    )
    from arkhai_api_selling.settlement_composition import SellingSettlementComposition
    from market_identity import Signer
    from market_storefront_kit import StorefrontLoopController


def _issuance_subject(listing_resource: Mapping[str, Any]) -> IssuanceSubject:
    """A listing sells its named service, against the quota resource it was created over."""
    resource_id = listing_resource.get("resource_id")
    return IssuanceSubject(
        service=str(listing_resource.get("service_name") or ""),
        resource_id=str(resource_id) if resource_id else None,
        endpoint=listing_resource.get("base_url"),
    )


class PublishFromQuotaRequest(QuotaPublishRequest):
    """Seller's quota-backed publish request."""

    service_name: str
    description: str | None = None
    openapi_url: str | None = None
    base_url: str | None = None


def _listing_resource(request: Mapping[str, Any], source: QuotaSource) -> dict[str, Any]:
    """An operator's named-service listing over its quota resource."""
    return {
        "service_name": request["service_name"],
        "description": request.get("description"),
        "openapi_url": request.get("openapi_url"),
        "base_url": request.get("base_url"),
        "resource_id": source.resource_id,
        "capacity_site_id": source.site_id,
        "offering_mode": source.offering_mode,
    }


SELLING_CONTRIBUTIONS = SellingContributions(
    label=API_CREDITS_LABEL,
    kind=API_CREDITS_SCHEMA_KIND,
    offering_mode="api_credits",
    contribution_id="apicredits",
    table_prefix="api_credit",
    listing_schema=ApiCreditsListing,
    publication_mapping=_listing_resource,
    issuance_projection=_issuance_subject,
    consumption_rule=ConsumptionRule.FIXED_PER_REQUEST,
    refusal_noun="API-credit",
)


def storefront_sqlite_client(db_path: str, **options: Any) -> StorefrontSQLiteClient:
    """The storefront's persistence over ``db_path``, under the API-credits bundle."""
    return StorefrontSQLiteClient(db_path, SELLING_CONTRIBUTIONS, **options)


_sqlite_client: StorefrontSQLiteClient | None = None


def get_sqlite_client(
    *,
    local_listing_principal: Identity | None = None,
    expected_legacy_sellers: tuple[str, ...] | None = None,
) -> StorefrontSQLiteClient:
    """The process's one client over the configured database, composed on first use."""
    global _sqlite_client
    if _sqlite_client is None and (
        local_listing_principal is None or expected_legacy_sellers is None
    ):
        raise RuntimeError(
            "initial SQLite composition requires local listing migration context",
        )
    if _sqlite_client is None:
        _sqlite_client = storefront_sqlite_client(
            config.settings.db_path,
            local_listing_principal=local_listing_principal,
            expected_legacy_sellers=expected_legacy_sellers,
        )
    return _sqlite_client


def _registry_client() -> MultiRegistryClient:
    signer = resolved_marketplace_signer
    if signer is None:
        raise RuntimeError("storefront marketplace signer is not initialized")
    settings = config.settings
    return MultiRegistryClient(
        list(settings.registry.urls),
        caller_role="seller",
        expected_registries=config.resolve_registry_authorities(),
        timeout=settings.registry.discovery_timeout,
        auth=settings.registry.auth,
        signer=signer,
    )


def _registry_publication() -> RegistryPublication:
    return RegistryPublication(
        enabled=config.settings.enable_registry_discovery,
        registry_urls=tuple(config.settings.registry.urls),
        storefront_url=config.BASE_URL_OVERRIDE,
        client_factory=_registry_client,
    )


QUOTA_CAPACITY = QuotaCapacity(
    sites=config.capacity_sites,
    signer=lambda: resolved_marketplace_signer,
    reconciler=lambda factory: QUOTA_PUBLICATION.reconciler(factory),
)
QUOTA_PUBLICATION = QuotaPublication(
    SELLING_CONTRIBUTIONS, capacity=QUOTA_CAPACITY, registry=_registry_publication
)


def alkahest_stage(**collaborators: Any) -> AlkahestSellerStage:
    """This storefront's Alkahest entry, with any of ``collaborators`` in place of its own."""
    defaults: dict[str, Any] = {
        # A credit grant releases to the seller once issued; nothing here
        # judges an oracle's verdict or splits a refund, so only the recipient
        # model is delivered.
        "fulfils_through_capacity": True,
        "release_models": frozenset({RECIPIENT_RELEASE}),
        "chains": lambda: config.CHAINS,
        "seller_wallet": lambda: str(config.settings.get("wallet.address", "") or ""),
        "composition": lambda: resolved_settlement_composition,
        "sqlite_client": lambda: resolved_sqlite_client,
        "backfill_escrows": backfill_escrow_obligation_records,
        "stage_event": stage_event,
    }
    return AlkahestSellerStage(SELLING_CONTRIBUTIONS, **{**defaults, **collaborators})


def payments_stage(**collaborators: Any) -> ArkhaiPaymentsSellerStage:
    """This storefront's Arkhai payments entry, with any of ``collaborators`` in place of its own."""
    defaults: dict[str, Any] = {
        "fulfils_through_capacity": True,
        "capacity": QUOTA_CAPACITY,
        "hold_ttl_seconds": lambda: float(config.settings.get("capacity.hold_ttl_seconds", 0) or 0),
        "composition": lambda: resolved_settlement_composition,
        "sqlite_client": lambda: resolved_sqlite_client,
        "reconciliation_interval": lambda: config.seconds_setting("payment_reconciliation_interval", 30),
        "stage_event": stage_event,
    }
    return ArkhaiPaymentsSellerStage(SELLING_CONTRIBUTIONS, **{**defaults, **collaborators})


ALKAHEST_STAGE = alkahest_stage()
PAYMENTS_STAGE = payments_stage()
SELLER_STAGES = SettlementStageTable({
    ALKAHEST_STAGE.mechanism: ALKAHEST_STAGE,
    PAYMENTS_STAGE.mechanism: PAYMENTS_STAGE,
})


def mechanism_loops(stages: SettlementStageTable) -> tuple[ContributedLoop, ...]:
    """The loops the composed mechanisms contribute."""
    return tuple(loop for stage in stages.values() for loop in stage.contributed_loops())


def mechanism_startup_steps(
    stages: SettlementStageTable,
) -> tuple[Callable[[], Awaitable[None]], ...]:
    """The startup steps the composed mechanisms contribute."""
    return tuple(step for stage in stages.values() for step in stage.startup_steps())


def mechanism_health(stages: SettlementStageTable) -> dict[str, str]:
    """The health checks the composed mechanisms contribute."""
    checks: dict[str, str] = {}
    for stage in stages.values():
        checks.update(stage.health_checks())
    return checks


STOREFRONT_LOOPS = StorefrontLoops(
    sqlite_client=lambda: resolved_sqlite_client,
    settlement_worker=lambda: resolved_settlement_worker,
    capacity=QUOTA_CAPACITY,
    settings=config.LOOP_SETTINGS,
    contributed_loops=lambda: mechanism_loops(SELLER_STAGES),
)

AUTH = StorefrontAuth(
    replay_store=lambda: resolved_sqlite_client,
    signer=lambda: resolved_marketplace_signer,
    admin_principals=lambda: config.resolve_admin_identities(),
    seller_principal=lambda: config.resolve_identity_config().principal,
)

LISTING_ROUTES = ListingRoutes(
    repository=lambda: resolved_sqlite_client,
    listing_service=lambda: resolved_listing_service,
    publication=QUOTA_PUBLICATION,
)
NEGOTIATE_ROUTES = NegotiateRoutes(
    repository=lambda: resolved_sqlite_client,
    runtime=lambda: resolved_negotiation_runtime,
    signer=lambda: resolved_marketplace_signer,
    storefront_url=lambda: config.BASE_URL_OVERRIDE,
)
NEGOTIATION_ROUTES = NegotiationRoutes(
    repository=lambda: resolved_sqlite_client,
    negotiation_service=lambda: resolved_negotiation_service,
    runtime=lambda: resolved_negotiation_runtime,
    signer=lambda: resolved_marketplace_signer,
)
SETTLE_ROUTES = SettleRoutes(
    repository=lambda: resolved_sqlite_client,
    composition=lambda: resolved_settlement_composition,
    coordinator=lambda: resolved_settlement_coordinator,
    signer=lambda: resolved_marketplace_signer,
)

resolved_market_domain: "MarketDomainContract | None" = None
resolved_sqlite_client: "StorefrontSQLiteClient | None" = None
resolved_settlement_repository: "SettlementSQLiteRepository | None" = None
resolved_settlement_runtime: "SettlementRuntime | None" = None
resolved_settlement_worker: "SettlementServicingWorker | None" = None
resolved_settlement_coordinator: "SettlementJobCoordinator | None" = None
resolved_failure_policy: "FailurePolicy | None" = None
resolved_settlement_composition: "SellingSettlementComposition | None" = None
resolved_issuance_evidence_service: "IssuanceEvidenceService | None" = None
resolved_private_result_repository: "PrivateResultRepository | None" = None
resolved_listing_service: "ListingService | None" = None
resolved_negotiation_service: "NegotiationService | None" = None
resolved_negotiation_runtime: "NegotiationRuntime | None" = None
resolved_system_service: "SystemService | None" = None
resolved_marketplace_signer: "Signer | None" = None
resolved_loop_controller: "StorefrontLoopController | None" = None

#: Whether this process opens new negotiations. Process-local and kept across
#: lifespans: a restarted process trades again, and a lifespan does not reset it.
trading_pause = TradingPause()

SYSTEM_ROUTES = SystemRoutes(
    repository=lambda: resolved_sqlite_client,
    system_service=lambda: resolved_system_service,
    trading_pause=trading_pause,
    loops=lambda: resolved_loop_controller,
)


def clear_lifespan_state(*, domain: "MarketDomainContract") -> None:
    """Clear API-credit service state owned by one shared lifespan."""

    global resolved_market_domain
    global resolved_sqlite_client
    global resolved_settlement_repository
    global resolved_settlement_runtime
    global resolved_settlement_worker
    global resolved_settlement_coordinator
    global resolved_failure_policy
    global resolved_settlement_composition
    global resolved_issuance_evidence_service
    global resolved_private_result_repository
    global resolved_listing_service
    global resolved_negotiation_service
    global resolved_system_service
    global resolved_marketplace_signer
    global resolved_loop_controller

    if resolved_market_domain is not None and resolved_market_domain is not domain:
        raise RuntimeError(
            "cannot clear a dependency container owned by a different "
            "market-domain contract"
        )
    resolved_market_domain = None
    resolved_sqlite_client = None
    resolved_settlement_repository = None
    resolved_settlement_runtime = None
    resolved_settlement_worker = None
    resolved_settlement_coordinator = None
    resolved_failure_policy = None
    resolved_settlement_composition = None
    resolved_issuance_evidence_service = None
    resolved_private_result_repository = None
    resolved_listing_service = None
    resolved_negotiation_service = None
    resolved_system_service = None
    resolved_marketplace_signer = None
    if resolved_loop_controller is not None:
        resolved_loop_controller.clear_loops()
    resolved_loop_controller = None
