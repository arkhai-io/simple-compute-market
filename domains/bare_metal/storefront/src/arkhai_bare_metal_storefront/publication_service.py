"""Bare-metal hooks and configuration composed onto kit-owned publication.

The kit runtime persists nothing a registry has not first been given a local
record for: a listing and its binding are written before any registry is told,
closes and reopens change the local listing first, and every registry outcome
is recorded so a later pass converges a registry that missed one. See
openspec/specs/storefront-publication/spec.md, "Registries converge on each
listing's local status".
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from core_storefront.multi_registry_client import (
    MultiRegistryClient,
    RegistryAuthorityTrust,
)
from market_capacity_publication import (
    CapacityBindingError,
    PublicationBinding,
    PublicationCandidate,
    PublicationRuntime,
)
from market_identity import Signer
from registry_client import (
    ListingRequest,
    RegistryClient,
    RegistryClientError,
    UpdateListingRequest,
)

from .listing_binding import bare_metal_listing_binding
from .sqlite_client import SQLiteClient

RegistryClientFactory = Callable[[], Any]


def _listing_resource(listing: Mapping[str, Any]) -> Mapping[str, Any]:
    raw = listing.get("listing_resource")
    value = json.loads(raw) if isinstance(raw, str) else raw
    return value if isinstance(value, Mapping) else {}


class BareMetalPublicationHooks:
    """Bare-metal candidate check and durable binding lookup for the kit runtime."""

    def __init__(self, sqlite_client: SQLiteClient) -> None:
        self._db = sqlite_client

    def validate_candidate(
        self, candidate: PublicationCandidate[dict[str, Any]]
    ) -> None:
        offering_mode = _listing_resource(candidate.payload).get("offering_mode")
        if offering_mode != candidate.binding.offering_mode:
            raise CapacityBindingError(
                "bare-metal listing_resource offering_mode does not match its "
                "capacity binding"
            )

    async def binding_for_listing(self, listing_id: str) -> PublicationBinding | None:
        return await bare_metal_listing_binding(self._db, listing_id)


async def bare_metal_publication_candidate(
    sqlite_client: SQLiteClient,
    listing_id: str,
) -> PublicationCandidate[dict[str, Any]]:
    """The persisted listing, as the kit runtime publishes it, with its binding."""
    binding = await bare_metal_listing_binding(sqlite_client, listing_id)
    listing = await sqlite_client.load_listing(listing_id=listing_id)
    if binding is None or listing is None:
        raise CapacityBindingError(
            f"listing {listing_id!r} has no complete durable capacity binding"
        )
    return PublicationCandidate(listing_id, binding, listing)


def build_publication_runtime(
    sqlite_client: SQLiteClient,
    registry_client_factory: RegistryClientFactory,
    *,
    registry_urls: Sequence[str],
    storefront_url: str,
) -> PublicationRuntime[dict[str, Any]]:
    """Compose the bare-metal hooks with the injected registry transport."""
    return PublicationRuntime(
        repository=sqlite_client,
        hooks=BareMetalPublicationHooks(sqlite_client),
        enabled=True,
        registry_urls=tuple(registry_urls),
        registry_client_factory=registry_client_factory,
        listing_request_factory=ListingRequest,
        update_listing_request_factory=UpdateListingRequest,
        storefront_url=storefront_url,
    )


@dataclass(frozen=True)
class BareMetalRegistryConfiguration:
    """Every registry a bare-metal storefront publishes to, each with its pin.

    ``authorities`` maps each configured registry URL, normalized and in
    configured order, to the authority and principals its responses must carry.
    """

    authorities: Mapping[str, RegistryAuthorityTrust]

    @property
    def urls(self) -> tuple[str, ...]:
        return tuple(self.authorities)

    def client_factory(self, signer: Signer) -> RegistryClientFactory:
        """A fan-out over every configured registry, opened per operation."""

        def factory() -> MultiRegistryClient:
            return MultiRegistryClient(
                list(self.urls),
                signer=signer,
                caller_role="seller",
                expected_registries=dict(self.authorities),
            )

        return factory

    async def reachability(
        self,
        signer: Signer,
        *,
        timeout: float = 2.0,
        transport: Any | None = None,
    ) -> str:
        """``ok`` when every registry answers a signed health read, else why the
        first that does not.

        Read for the administrator's status, never the ``/health`` probe: it
        makes a network call per registry, and the timeout keeps the status
        route fast while one is down.
        """
        for url, trust in self.authorities.items():
            try:
                async with RegistryClient(
                    url,
                    signer=signer,
                    caller_role="seller",
                    expected_registries=trust.principals,
                    registry_authority=trust.authority,
                    timeout=timeout,
                    transport=transport,
                ) as client:
                    await client.get_health()
            except RegistryClientError as exc:
                return f"http_{exc.status_code}"
            except Exception as exc:
                return f"error: {type(exc).__name__}"
        return "ok"


__all__ = [
    "BareMetalPublicationHooks",
    "BareMetalRegistryConfiguration",
    "bare_metal_publication_candidate",
    "build_publication_runtime",
]
