"""Storefront dependency container.

``resolved_*`` module-level variables are populated once during the
FastAPI lifespan in ``server.py``. Controllers retrieve services via
``Depends(lambda: _c.resolved_X)``.

For on-chain dispatch, callers go through
:func:`get_alkahest_client(chain_name)` so a missing chain produces a
single error path rather than scattered ``None`` checks.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from core_storefront.services.negotiation_service import NegotiationService
    from market_storefront.services.listing_service import ListingService
    from market_storefront.services.system_service import SystemService
    from market_storefront.utils.sqlite_client import SQLiteClient

# ---------------------------------------------------------------------------
# Resolved service instances — populated during FastAPI lifespan startup.
# ---------------------------------------------------------------------------

resolved_sqlite_client: "SQLiteClient | None" = None

# AlkahestClient instances keyed by chain name. Populated from
# AlkahestService.build_clients(). May be empty if no chains are
# configured or all clients failed to initialise.
resolved_alkahest_clients: dict[str, Any] = {}

resolved_listing_service: "ListingService | None" = None
resolved_negotiation_service: "NegotiationService | None" = None
resolved_system_service: "SystemService | None" = None

resolved_storefront_service = None


def get_alkahest_client(chain_name: str) -> Optional[Any]:
    """Return the AlkahestClient for ``chain_name``, or ``None`` if absent."""
    return resolved_alkahest_clients.get(chain_name)


def configured_chain_names() -> list[str]:
    """Return the chains that have a live AlkahestClient available."""
    return list(resolved_alkahest_clients.keys())
