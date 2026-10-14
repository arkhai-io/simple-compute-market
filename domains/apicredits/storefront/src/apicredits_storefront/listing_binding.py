"""An API-credit listing's durable binding and the pool it reads its backing from.

A listing is bound at creation to the site and quota resource it sells, the pool
that resource belongs to, and the backing that pool declares. Every capacity
effect, reconciliation, and recheck builds the listing's capacity binding from
that record, never from the published listing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core_storefront.domain_registry import (
    StorefrontDomainRegistration,
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from market_capacity_publication import PublicationBinding, publication_binding
from market_core import MarketDomainContract
from market_resource_pools import ResolvedPool, read_site_declarations

API_CREDITS_OFFERING_MODE = "api_credits"
API_CREDITS_CONTRIBUTION_ID = "apicredits"
LISTING_SOURCE_KIND = "api_credits.quota-listing.v1"
LISTING_SOURCE_SCHEMA_VERSION = 1


class QuotaPoolUnavailable(ValueError):
    """The quota resource's pool cannot back a listing now."""


@dataclass(frozen=True)
class QuotaPool:
    """The pool a quota resource belongs to, as its site declares it now."""

    pool_id: str
    declaration: ResolvedPool


def quota_pool(
    resource_pools: Sequence[Mapping[str, Any]],
    *,
    resource_id: str,
    pool_id: str | None = None,
) -> QuotaPool:
    """The enabled pool advertising API credits that holds ``resource_id``.

    ``pool_id`` is the pool a bound listing recorded: the resource must still
    be in that pool, because a listing represents its source as bound, and a
    resource now in another pool is not that source whatever that pool
    declares. Without it, as at listing creation, any projected pool holding
    the resource is the one. Read from the site's resource-pool projection,
    through the one reader of pool declarations, so a pool whose declarations
    do not resolve is refused rather than read as either backing.
    """
    holding = next(
        (
            str(pool.get("pool_id"))
            for pool in resource_pools
            if (pool_id is None or str(pool.get("pool_id")) == pool_id)
            and any(
                str(member.get("physical_resource_id")) == resource_id
                for member in pool.get("resources") or ()
            )
        ),
        None,
    )
    if holding is None:
        raise QuotaPoolUnavailable(
            f"quota resource {resource_id!r} is in no projected pool"
            if pool_id is None
            else f"quota resource {resource_id!r} is no longer in its pool {pool_id!r}"
        )
    pool_id = holding
    declarations = read_site_declarations(resource_pools)
    if pool_id in declarations.unresolvable:
        raise QuotaPoolUnavailable(
            f"pool {pool_id!r} is unresolvable: "
            + ", ".join(declarations.unresolvable[pool_id])
        )
    declaration = declarations.resolved[pool_id]
    if not declaration.enabled:
        raise QuotaPoolUnavailable(f"pool {pool_id!r} is disabled")
    if not declaration.advertises(API_CREDITS_OFFERING_MODE):
        raise QuotaPoolUnavailable(
            f"pool {pool_id!r} does not advertise {API_CREDITS_OFFERING_MODE!r}"
        )
    return QuotaPool(pool_id, declaration)


def api_credit_registration(domain: MarketDomainContract) -> StorefrontDomainRegistration:
    """The storefront's one registration: the API-credit domain under its mode."""
    return StorefrontDomainRegistration(
        offering_mode=API_CREDITS_OFFERING_MODE,
        contract=domain,
        contribution_id=API_CREDITS_CONTRIBUTION_ID,
    )


def prepare_api_credit_listing_binding(
    *,
    listing_id: str,
    site_id: str,
    resource_id: str,
    pool: QuotaPool,
    domain: MarketDomainContract,
) -> StorefrontListingBinding:
    """The immutable binding recorded with a new listing.

    An operator creates each listing, and several may sell one quota resource,
    so the derivation identity is the listing itself: nothing derives a credit
    listing from its source or looks one up by derivation.
    """
    source = {
        "kind": LISTING_SOURCE_KIND,
        "schema_version": LISTING_SOURCE_SCHEMA_VERSION,
        "payload": {
            "site_id": site_id,
            "pool_id": pool.pool_id,
            "resource_id": resource_id,
            "listing_id": listing_id,
        },
    }
    domain_binding = api_credit_registration(domain).binding
    return StorefrontListingBinding.from_source_envelope(
        listing_id=listing_id,
        site_id=site_id,
        pool_id=pool.pool_id,
        physical_resource_id=resource_id,
        binding=domain_binding,
        derivation_key=build_storefront_derivation_key(
            site_id=site_id,
            offering_mode=API_CREDITS_OFFERING_MODE,
            binding=domain_binding,
            source_identity={"listing_id": listing_id},
        ),
        source_envelope=source,
        last_reconciled_at=datetime.now(UTC).isoformat(),
        capacity_backing=pool.declaration.backing.label,
    )


async def api_credit_listing_binding(
    repository: Any, listing_id: str
) -> PublicationBinding | None:
    """The listing's capacity binding, built from its durable record alone."""
    durable = await repository.load_listing_binding(listing_id=listing_id)
    if durable is None or not durable.physical_resource_id:
        return None
    return _publication_binding(durable)


@dataclass(frozen=True)
class BoundQuotaSource:
    """A listing's capacity binding and the pool its durable record names.

    The capacity binding carries what every market's effects need; the pool is
    this domain's provenance, which its source checks enforce.
    """

    binding: PublicationBinding
    pool_id: str


async def api_credit_listing_source(
    repository: Any, listing_id: str
) -> BoundQuotaSource | None:
    """The listing's capacity binding with its bound pool, read once."""
    durable = await repository.load_listing_binding(listing_id=listing_id)
    if durable is None or not durable.physical_resource_id or not durable.pool_id:
        return None
    return BoundQuotaSource(_publication_binding(durable), durable.pool_id)


def _publication_binding(durable: StorefrontListingBinding) -> PublicationBinding:
    return publication_binding(
        capacity_backing=durable.capacity_backing,
        site_id=durable.site_id,
        offering_mode=durable.binding.offering_mode,
        source_id=durable.physical_resource_id,
    )


__all__ = [
    "API_CREDITS_CONTRIBUTION_ID",
    "API_CREDITS_OFFERING_MODE",
    "api_credit_registration",
    "QuotaPool",
    "QuotaPoolUnavailable",
    "BoundQuotaSource",
    "api_credit_listing_binding",
    "api_credit_listing_source",
    "prepare_api_credit_listing_binding",
    "quota_pool",
]
