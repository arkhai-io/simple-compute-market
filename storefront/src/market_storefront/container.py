"""Storefront dependency container.

``resolved_*`` module-level variables are populated once during the
FastAPI lifespan in ``server.py``. Controllers retrieve services via
``Depends(lambda: _c.resolved_X)``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from market_storefront.services.listing_service import ListingService
    from market_storefront.services.negotiation_service import NegotiationService
    from market_storefront.services.system_service import SystemService
    from market_storefront.utils.sqlite_client import SQLiteClient

# ---------------------------------------------------------------------------
# Resolved service instances — populated during FastAPI lifespan startup.
# ---------------------------------------------------------------------------

resolved_sqlite_client: "SQLiteClient | None" = None
resolved_alkahest_client = None  # AlkahestClient | None
resolved_alkahest_configured: bool = False

resolved_listing_service: "ListingService | None" = None
resolved_negotiation_service: "NegotiationService | None" = None
resolved_system_service: "SystemService | None" = None

resolved_storefront_service = None
