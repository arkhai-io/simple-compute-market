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
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from arkhai_bare_metal import BARE_METAL_OFFERING_MODE
from core_storefront.multi_registry_client import (
    MultiRegistryClient,
    RegistryAuthorityTrust,
)
from market_capacity_publication import (
    CapacityBinding,
    CapacityBindingError,
    PublicationBinding,
    PublicationCandidate,
    PublicationRuntime,
)
from market_identity import Identity, Signer, TrustedIdentitySet
from registry_client import ListingRequest, UpdateListingRequest

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
        """The listing's binding, whose source is the Physical Resource it offers.

        A bare-metal listing sells one specific machine, so its binding's source
        is that Physical Resource rather than its pool; the pool stays part of
        the listing's derivation key. Every bare-metal listing is
        capacity-backed, so a binding recording anything else is refused.
        """
        durable = await self._db.load_listing_binding(listing_id=listing_id)
        if durable is None or not durable.physical_resource_id:
            return None
        if durable.binding.offering_mode != BARE_METAL_OFFERING_MODE:
            raise CapacityBindingError(
                f"listing {listing_id!r} is not bound as a bare-metal listing"
            )
        if durable.capacity_backing != CapacityBinding.capacity_backing:
            raise CapacityBindingError(
                f"bare-metal listing {listing_id!r} is not recorded as "
                "capacity-backed"
            )
        return CapacityBinding(
            durable.site_id,
            BARE_METAL_OFFERING_MODE,
            durable.physical_resource_id,
        )


async def bare_metal_publication_candidate(
    sqlite_client: SQLiteClient,
    listing_id: str,
) -> PublicationCandidate[dict[str, Any]]:
    """The persisted listing, as the kit runtime publishes it, with its binding."""
    binding = await BareMetalPublicationHooks(sqlite_client).binding_for_listing(
        listing_id
    )
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
    registry_url: str,
    storefront_url: str,
) -> PublicationRuntime[dict[str, Any]]:
    """Compose the bare-metal hooks with the injected registry transport."""
    return PublicationRuntime(
        repository=sqlite_client,
        hooks=BareMetalPublicationHooks(sqlite_client),
        enabled=True,
        registry_urls=(registry_url,),
        registry_client_factory=registry_client_factory,
        listing_request_factory=ListingRequest,
        update_listing_request_factory=UpdateListingRequest,
        storefront_url=storefront_url,
    )


@dataclass(frozen=True)
class BareMetalRegistryConfiguration:
    """The one registry a bare-metal storefront publishes to, and its pin."""

    url: str
    trust: RegistryAuthorityTrust

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "BareMetalRegistryConfiguration":
        env = os.environ if environ is None else environ
        try:
            raw_principals = json.loads(env["BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "BARE_METAL_STOREFRONT_REGISTRY_PRINCIPALS must contain valid JSON"
            ) from exc
        if not isinstance(raw_principals, list):
            raise RuntimeError("registry principals must be a JSON list")
        try:
            url = env["BARE_METAL_STOREFRONT_REGISTRY_URL"]
            authority = env["BARE_METAL_STOREFRONT_REGISTRY_AUTHORITY"]
        except KeyError as exc:
            raise RuntimeError(f"{exc.args[0]} is required for publication") from exc
        return cls(
            url=url,
            trust=RegistryAuthorityTrust(
                authority=authority,
                principals=TrustedIdentitySet(
                    identities=tuple(
                        Identity.model_validate(item) for item in raw_principals
                    )
                ),
            ),
        )

    def client_factory(self, signer: Signer) -> RegistryClientFactory:
        """A fan-out of one over the configured registry, opened per operation."""

        def factory() -> MultiRegistryClient:
            return MultiRegistryClient(
                [self.url],
                signer=signer,
                caller_role="seller",
                expected_registries={self.url: self.trust},
            )

        return factory


__all__ = [
    "BareMetalPublicationHooks",
    "BareMetalRegistryConfiguration",
    "bare_metal_publication_candidate",
    "build_publication_runtime",
]
