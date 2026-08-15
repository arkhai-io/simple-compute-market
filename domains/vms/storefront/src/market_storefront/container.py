"""Storefront dependency container.

``resolved_*`` module-level variables are populated once during the
FastAPI lifespan in ``server.py``. Controllers retrieve services via
``Depends(lambda: _c.resolved_X)``.

For on-chain dispatch, callers go through
:func:`get_alkahest_client(chain_name)` so a missing chain produces a
single error path rather than scattered ``None`` checks.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core_storefront.domain_registry import (
        StorefrontDomainBinding,
        StorefrontDomainRegistry,
    )
    from core_storefront.services.negotiation_service import NegotiationService
    from market_identity import Signer

    from market_storefront.services.listing_service import ListingService
    from market_storefront.services.system_service import SystemService
    from market_storefront.settlement_composition import VmSettlementComposition
    from market_storefront.utils.sqlite_client import SQLiteClient

# ---------------------------------------------------------------------------
# Resolved service instances — populated during FastAPI lifespan startup.
# ---------------------------------------------------------------------------

resolved_domain_registry: StorefrontDomainRegistry | None = None
resolved_sqlite_client: SQLiteClient | None = None
resolved_marketplace_signer: Signer | None = None

# AlkahestClient instances keyed by chain name. Populated from
# AlkahestService.build_clients(). May be empty if no chains are
# configured or all clients failed to initialise.
resolved_alkahest_clients: dict[str, Any] = {}

resolved_listing_service: ListingService | None = None
resolved_negotiation_service: NegotiationService | None = None
resolved_system_service: SystemService | None = None
resolved_settlement_composition: VmSettlementComposition | None = None

resolved_storefront_service = None

def resolve_market_domain(binding: StorefrontDomainBinding):
    """Resolve only from the frozen startup registry and exact durable binding."""

    if resolved_domain_registry is None:
        raise RuntimeError("storefront domain registry is unavailable")
    return resolved_domain_registry.resolve(binding)


def clear_lifespan_state(*, registry: StorefrontDomainRegistry) -> None:
    """Clear state owned by the lifespan bound to ``registry``."""
    global resolved_domain_registry
    global resolved_sqlite_client
    global resolved_marketplace_signer
    global resolved_alkahest_clients
    global resolved_listing_service
    global resolved_negotiation_service
    global resolved_system_service
    global resolved_settlement_composition
    global resolved_storefront_service

    if (
        resolved_domain_registry is not None
        and resolved_domain_registry is not registry
    ):
        raise RuntimeError(
            "cannot clear a dependency container owned by a different "
            "storefront domain registry"
        )
    resolved_domain_registry = None
    resolved_sqlite_client = None
    resolved_marketplace_signer = None
    resolved_alkahest_clients = {}
    resolved_listing_service = None
    resolved_negotiation_service = None
    resolved_system_service = None
    resolved_settlement_composition = None
    resolved_storefront_service = None



def get_alkahest_client(chain_name: str) -> Any | None:
    """Return the AlkahestClient for ``chain_name``, or ``None`` if absent."""
    return resolved_alkahest_clients.get(chain_name)


def configured_chain_names() -> list[str]:
    """Return the chains that have a live AlkahestClient available."""
    return list(resolved_alkahest_clients.keys())
