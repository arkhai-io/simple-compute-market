"""Storefront dependency container.

``resolved_*`` module-level variables are populated once during the
FastAPI lifespan in ``server.py``. Controllers retrieve services via
``Depends(lambda: _c.resolved_X)`` — the same pattern as the VM
storefront and the services.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from core_storefront.services.negotiation_service import NegotiationService

    from apitokens_storefront.services.listing_service import ListingService
    from apitokens_storefront.services.system_service import SystemService
    from apitokens_storefront.utils.sqlite_client import SQLiteClient

resolved_sqlite_client: "SQLiteClient | None" = None
resolved_alkahest_clients: dict[str, Any] = {}
resolved_listing_service: "ListingService | None" = None
resolved_negotiation_service: "NegotiationService | None" = None
resolved_system_service: "SystemService | None" = None


def get_alkahest_client(chain_name: str) -> Optional[Any]:
    """Return the AlkahestClient for ``chain_name``, or ``None`` if absent."""
    return resolved_alkahest_clients.get(chain_name)


def configured_chain_names() -> list[str]:
    """Return the chains that have a live AlkahestClient available."""
    return list(resolved_alkahest_clients.keys())
