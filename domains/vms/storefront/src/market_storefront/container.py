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
    from core_storefront.services.negotiation_service import NegotiationService
    from market_policy import NegotiationCatalogue

    from market_storefront.services.listing_service import ListingService
    from market_storefront.services.system_service import SystemService
    from market_storefront.utils.sqlite_client import SQLiteClient

# ---------------------------------------------------------------------------
# Resolved service instances — populated during FastAPI lifespan startup.
# ---------------------------------------------------------------------------

resolved_sqlite_client: SQLiteClient | None = None

# AlkahestClient instances keyed by chain name. Populated from
# AlkahestService.build_clients(). May be empty if no chains are
# configured or all clients failed to initialise.
resolved_alkahest_clients: dict[str, Any] = {}

resolved_listing_service: ListingService | None = None
resolved_negotiation_service: NegotiationService | None = None
resolved_system_service: SystemService | None = None

resolved_storefront_service = None

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
