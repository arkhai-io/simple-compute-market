"""The storefront's dependency container.

The selling bundle and the parts composed over it are fixed for the process; the
``resolved_*`` services are set once by the lifespan in ``server.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

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
from arkhai_api_selling.publication import QuotaPublication, RegistryPublication
from arkhai_api_selling.publish_route import PublishFromQuotaRequest as QuotaPublishRequest
from arkhai_api_selling.system import SystemService
from arkhai_apicredits.label import API_CREDITS_LABEL
from arkhai_apicredits.schema import API_CREDITS_SCHEMA_KIND, ApiCreditsListing
from core_storefront.multi_registry_client import MultiRegistryClient
from market_storefront_kit import LifecycleRouteError, TradingPause

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
    from apicredits_storefront.settlement_composition import (
        ApiCreditsSettlementComposition,
    )
    from market_identity import Signer
    from market_storefront_kit import StorefrontLoopController

    from apicredits_storefront.utils.sqlite_client import SQLiteClient


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
PAYMENT_RECONCILIATION = "payment_reconciliation"


def _payment_service() -> Any | None:
    composition = resolved_settlement_composition
    if composition is None:
        return None
    if resolved_sqlite_client is None:
        raise LifecycleRouteError(503, "storefront persistence is not initialized")
    return composition.payment_service(resolved_sqlite_client)


async def payment_reconciliation_step() -> Mapping[str, Any]:
    service = _payment_service()
    if service is None:
        return {"loop": PAYMENT_RECONCILIATION, "attempted": 0, "failed": 0}
    done = await service.reconcile_once()
    return {"loop": PAYMENT_RECONCILIATION, "attempted": done.attempted, "failed": done.failed}


def _payment_loops() -> tuple[ContributedLoop, ...]:
    """Payment reconciliation, a loop only while Arkhai payments is composed."""
    if _payment_service() is None:
        return ()
    return (
        ContributedLoop(
            PAYMENT_RECONCILIATION,
            route="payment-reconciliation",
            step=payment_reconciliation_step,
            interval_seconds=config.seconds_setting("payment_reconciliation_interval", 30),
        ),
    )


STOREFRONT_LOOPS = StorefrontLoops(
    sqlite_client=lambda: resolved_sqlite_client,
    settlement_worker=lambda: resolved_settlement_worker,
    capacity=QUOTA_CAPACITY,
    settings=config.LOOP_SETTINGS,
    contributed_loops=_payment_loops,
)

resolved_market_domain: "MarketDomainContract | None" = None
resolved_sqlite_client: "SQLiteClient | None" = None
resolved_settlement_repository: "SettlementSQLiteRepository | None" = None
resolved_settlement_runtime: "SettlementRuntime | None" = None
resolved_settlement_worker: "SettlementServicingWorker | None" = None
resolved_settlement_coordinator: "SettlementJobCoordinator | None" = None
resolved_failure_policy: "FailurePolicy | None" = None
resolved_settlement_composition: "ApiCreditsSettlementComposition | None" = None
resolved_issuance_evidence_service: "IssuanceEvidenceService | None" = None
resolved_private_result_repository: "PrivateResultRepository | None" = None
resolved_alkahest_clients: dict[str, Any] = {}
resolved_listing_service: "ListingService | None" = None
resolved_negotiation_service: "NegotiationService | None" = None
resolved_negotiation_runtime: "NegotiationRuntime | None" = None
resolved_system_service: "SystemService | None" = None
resolved_marketplace_signer: "Signer | None" = None
resolved_loop_controller: "StorefrontLoopController | None" = None

#: Whether this process opens new negotiations. Process-local and kept across
#: lifespans: a restarted process trades again, and a lifespan does not reset it.
trading_pause = TradingPause()


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
    global resolved_alkahest_clients
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
    resolved_alkahest_clients = {}
    resolved_listing_service = None
    resolved_negotiation_service = None
    resolved_system_service = None
    resolved_marketplace_signer = None
    if resolved_loop_controller is not None:
        resolved_loop_controller.clear_loops()
    resolved_loop_controller = None


def get_alkahest_client(chain_name: str) -> Any | None:
    """Return the AlkahestClient for ``chain_name``, or ``None`` if absent."""
    return resolved_alkahest_clients.get(chain_name)


def configured_chain_names() -> list[str]:
    """Return the chains that have a live AlkahestClient available."""
    return list(resolved_alkahest_clients.keys())
