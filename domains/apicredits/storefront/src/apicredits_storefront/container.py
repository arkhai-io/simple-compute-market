"""Storefront dependency container.

``SELLING_CONTRIBUTIONS`` is the API-credits bundle the selling library
composes, fixed for the process. ``resolved_*`` module-level variables are
populated once during the FastAPI lifespan in ``server.py``. Controllers
retrieve services via ``Depends(lambda: _c.resolved_X)`` — the same pattern as
the VM storefront and the services.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from arkhai_api_selling.contributions import (
    ConsumptionRule,
    IssuanceSubject,
    QuotaSource,
    SellingContributions,
)
from arkhai_api_selling.evidence_store import IssuanceEvidenceService, PrivateResultRepository
from arkhai_apicredits.label import API_CREDITS_LABEL
from arkhai_apicredits.schema import API_CREDITS_SCHEMA_KIND, ApiCreditsListing
from market_storefront_kit import TradingPause

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

    from apicredits_storefront.services.listing_service import ListingService
    from apicredits_storefront.services.system_service import SystemService
    from apicredits_storefront.utils.sqlite_client import SQLiteClient


def _issuance_subject(listing_resource: Mapping[str, Any]) -> IssuanceSubject:
    """A listing sells its named service, against the quota resource it was created over."""
    resource_id = listing_resource.get("resource_id")
    return IssuanceSubject(
        service=str(listing_resource.get("service_name") or ""),
        resource_id=str(resource_id) if resource_id else None,
        endpoint=listing_resource.get("base_url"),
    )


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
