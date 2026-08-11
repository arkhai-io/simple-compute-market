"""Storefront dependency container.

``resolved_*`` module-level variables are populated once during the
FastAPI lifespan in ``server.py``. Controllers retrieve services via
``Depends(lambda: _c.resolved_X)`` — the same pattern as the VM
storefront and the services.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core_storefront.services.negotiation_service import NegotiationService
    from market_policy import NegotiationCatalogue

    from apicredits_storefront.services.listing_service import ListingService
    from apicredits_storefront.services.system_service import SystemService
    from apicredits_storefront.utils.sqlite_client import SQLiteClient

resolved_sqlite_client: SQLiteClient | None = None
resolved_alkahest_clients: dict[str, Any] = {}
resolved_listing_service: ListingService | None = None
resolved_negotiation_service: NegotiationService | None = None
resolved_system_service: SystemService | None = None

# The negotiation policy catalogue this role composed. Resolved once during
# lifespan startup, so a source that cannot load, a malformed middleware, or a
# name two sources both offer fails before the application serves traffic rather
# than on the first negotiation that reaches it. Immutable once built.
resolved_policy_catalogue: NegotiationCatalogue | None = None


def policy_catalogue() -> NegotiationCatalogue:
    """The composed negotiation policy catalogue.

    Raises rather than composing on demand: a catalogue built here would be
    built from whatever configuration happened to be loaded, and would move the
    failure this design exists to surface at startup back into a request.
    """
    if resolved_policy_catalogue is None:
        raise RuntimeError(
            "negotiation policy catalogue is unresolved — the storefront "
            "composes it during lifespan startup; a caller reaching this "
            "before startup has bypassed application composition"
        )
    return resolved_policy_catalogue


def get_alkahest_client(chain_name: str) -> Any | None:
    """Return the AlkahestClient for ``chain_name``, or ``None`` if absent."""
    return resolved_alkahest_clients.get(chain_name)


def configured_chain_names() -> list[str]:
    """Return the chains that have a live AlkahestClient available."""
    return list(resolved_alkahest_clients.keys())
