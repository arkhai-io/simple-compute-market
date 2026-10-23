"""A quota-backed listing: its durable binding, its source recheck, and its reconciliation.

A listing is bound at creation to the site and quota resource it sells, the pool
that resource belongs to, and the backing that pool declares. Every capacity
effect, reconciliation, and recheck builds the listing's capacity binding from
that record, never from the published listing. The offering mode, contribution
identifier, and source envelope kind are the domain's, read from its bundle.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core_storefront.domain_registry import (
    StorefrontDomainRegistration,
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from market_capacity_publication import PublicationBinding, backing_changed, publication_binding
from market_core import MarketDomainContract
from market_policy.listing_source import ListingSourceVerdict
from market_resource_pools import ResolvedPool, read_site_declarations

from arkhai_api_selling.contributions import SellingContributions
from arkhai_api_selling.issuance import (
    MissingQuotaResource,
    issuance_subject,
    stored_listing_resource,
)

LISTING_SOURCE_SCHEMA_VERSION = 1


class QuotaPoolUnavailable(ValueError):
    """The quota resource's pool cannot back a listing now."""


@dataclass(frozen=True)
class QuotaPool:
    """The pool a quota resource belongs to, as its site declares it now."""

    pool_id: str
    declaration: ResolvedPool


def quota_pool(
    contributions: SellingContributions,
    resource_pools: Sequence[Mapping[str, Any]],
    *,
    resource_id: str,
    pool_id: str | None = None,
) -> QuotaPool:
    """The enabled pool advertising the domain's offering mode that holds ``resource_id``.

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
    if not declaration.advertises(contributions.offering_mode):
        raise QuotaPoolUnavailable(
            f"pool {pool_id!r} does not advertise {contributions.offering_mode!r}"
        )
    return QuotaPool(pool_id, declaration)


def registration(
    contributions: SellingContributions, domain: MarketDomainContract
) -> StorefrontDomainRegistration:
    """The storefront's one registration: the domain under its offering mode."""
    return StorefrontDomainRegistration(
        offering_mode=contributions.offering_mode,
        contract=domain,
        contribution_id=contributions.contribution_id,
    )


def prepare_listing_binding(
    contributions: SellingContributions,
    *,
    listing_id: str,
    site_id: str,
    listing_resource: Mapping[str, Any],
    pool: QuotaPool,
    domain: MarketDomainContract,
) -> StorefrontListingBinding:
    """The immutable binding recorded with a new listing.

    The quota resource is the one the listing's issuance projection names, so
    a listing whose projection names none is refused here, before anything is
    published. An operator creates each listing, and several may sell one
    quota resource, so the derivation identity is the listing itself: nothing
    derives a listing from its source or looks one up by derivation.
    """
    resource_id = str(
        issuance_subject(contributions, listing_resource, listing_id=listing_id).resource_id
    )
    source = {
        "kind": contributions.listing_source_kind,
        "schema_version": LISTING_SOURCE_SCHEMA_VERSION,
        "payload": {
            "site_id": site_id,
            "pool_id": pool.pool_id,
            "resource_id": resource_id,
            "listing_id": listing_id,
        },
    }
    domain_binding = registration(contributions, domain).binding
    return StorefrontListingBinding.from_source_envelope(
        listing_id=listing_id,
        site_id=site_id,
        pool_id=pool.pool_id,
        physical_resource_id=resource_id,
        binding=domain_binding,
        derivation_key=build_storefront_derivation_key(
            site_id=site_id,
            offering_mode=contributions.offering_mode,
            binding=domain_binding,
            source_identity={"listing_id": listing_id},
        ),
        source_envelope=source,
        last_reconciled_at=datetime.now(UTC).isoformat(),
        capacity_backing=pool.declaration.backing.label,
    )


async def listing_binding(repository: Any, listing_id: str) -> PublicationBinding | None:
    """The listing's capacity binding, built from its durable record alone."""
    durable = await repository.load_listing_binding(listing_id=listing_id)
    if durable is None or not durable.physical_resource_id:
        return None
    return _publication_binding(durable)


@dataclass(frozen=True)
class BoundQuotaSource:
    """A listing's capacity binding and the pool its durable record names.

    The capacity binding carries what every market's effects need; the pool is
    the domain's provenance, which its source checks enforce.
    """

    binding: PublicationBinding
    pool_id: str


async def listing_source(repository: Any, listing_id: str) -> BoundQuotaSource | None:
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


#: Check one listing, by id, against its own source.
ListingSourceCheck = Callable[[Any, str], Awaitable[ListingSourceVerdict]]


def build_listing_source_check(
    contributions: SellingContributions,
    capacity: Callable[[Any], Any],
) -> ListingSourceCheck:
    """A check reading each listing's own site through its trusted site client.

    The negotiation runtime asks before every seller decision and every
    acceptance. The listing itself must name, through the domain's issuance
    projection, the quota resource its durable binding records, so an
    acceptance never stands on a listing issuance could not serve. The declared
    half confirms that the resource is still in the pool the binding records,
    that the pool is enabled and advertises the domain's offering mode, and
    that the pool still declares the backing the listing was bound with.
    Provenance is the domain's to check; the binding's backing delegate decides
    only whether availability is asked. The available half requires at least
    one available unit, the condition listing creation requires. A source the
    storefront cannot read is unverifiable, which the runtime refuses as
    retryable. ``capacity`` returns the aggregate capacity client for a
    repository; the check reads only the site the listing's binding names.
    """

    async def check(repository: Any, listing_id: str) -> ListingSourceVerdict:
        source = await listing_source(repository, listing_id)
        if source is None:
            return ListingSourceVerdict(
                "declared_mismatch", "the listing has no trusted source binding"
            )
        binding = source.binding
        record = await repository.load_listing(listing_id=listing_id)
        try:
            subject = issuance_subject(
                contributions,
                _listing_resource(contributions, record),
                listing_id=listing_id,
            )
        except (MissingQuotaResource, ValueError) as exc:
            return ListingSourceVerdict("declared_mismatch", str(exc))
        if subject.resource_id != binding.source_id:
            return ListingSourceVerdict(
                "declared_mismatch",
                "the listing names a quota resource other than its binding's",
            )
        try:
            site = capacity(repository).site(binding.site_id)
        except KeyError:
            return ListingSourceVerdict(
                "unverifiable", f"site {binding.site_id!r} is not configured"
            )

        async def declared() -> ListingSourceVerdict | None:
            try:
                projection = await site.resource_pool_projection()
            except Exception as exc:  # noqa: BLE001 - any failure leaves the source unknown
                return ListingSourceVerdict(
                    "unverifiable",
                    f"site {binding.site_id!r} could not confirm the listing's source: {exc}",
                )
            try:
                pool = quota_pool(
                    contributions,
                    projection["resource_pools"],
                    resource_id=binding.source_id,
                    pool_id=source.pool_id,
                )
            except QuotaPoolUnavailable as exc:
                return ListingSourceVerdict("declared_mismatch", str(exc))
            if backing_changed(binding, pool.declaration.backing):
                return ListingSourceVerdict(
                    "declared_mismatch",
                    "the pool's backing differs from the listing's",
                    ("capacity_backing",),
                )
            return None

        async def available() -> ListingSourceVerdict | None:
            try:
                rows = await site.snapshot()
            except Exception as exc:  # noqa: BLE001 - any failure leaves the source unknown
                return ListingSourceVerdict(
                    "unverifiable",
                    f"site {binding.site_id!r} capacity could not be read: {exc}",
                )
            units = next(
                (
                    row.get("available_units")
                    for row in rows or ()
                    if row.get("resource_id") == binding.source_id
                ),
                None,
            )
            if units is None or int(units) < 1:
                return ListingSourceVerdict(
                    "unavailable", "the quota resource has no available unit"
                )
            return None

        verdict = await binding.backing.judge_async(declared, available)
        return verdict if verdict is not None else ListingSourceVerdict("matches")

    return check


def _listing_resource(
    contributions: SellingContributions, record: Mapping[str, Any] | None
) -> Mapping[str, Any]:
    """The stored listing's resource, validated as the domain's listing schema."""
    if record is None:
        raise ValueError("the listing is gone from the local store")
    listing = contributions.listing_schema.model_validate(
        {"listing_resource": stored_listing_resource(record.get("listing_resource"))}
    )
    return listing.listing_resource.model_dump(mode="json")


# Reconciliation. Pure functions over each listing's status and binding and an
# availability view, so the storefront's persistence stays out of them. Whether
# availability bounds a listing is its backing's decision, which the caller
# supplies as ``judge``.

AvailabilityView = Mapping[tuple[str, str], int]
"""Available units keyed by exact trusted ``(site_id, resource_id)``."""

Verdict = str | None
"""A reason a listing does not stand, or ``None`` when it does."""


@dataclass(frozen=True)
class QuotaListingSource:
    """One listing as reconciliation reads it: its status and binding.

    ``site_id`` and ``resource_id`` come from the listing's durable binding,
    never from its published payload.
    """

    listing_id: str
    status: str
    closed_by: str | None
    site_id: str
    resource_id: str


Judge = Callable[[QuotaListingSource, Callable[[], Verdict]], Verdict]
"""Judges one listing given its availability half.

The caller asks the listing's backing whether availability bounds it, so a rule
here supplies only what availability says and never decides that itself.
"""


def _available_units(availability: AvailabilityView, source: QuotaListingSource) -> int | None:
    return availability.get((source.site_id, source.resource_id))


def stale_open_listing_ids(
    sources: Iterable[QuotaListingSource],
    *,
    availability: AvailabilityView | None,
    judge: Judge,
) -> list[str]:
    """Open listings whose quota resource is exhausted.

    A listing stays open while its quota resource has any sellable units and
    closes on exhaustion; buyers pick the quantity per deal, and the quota
    guard enforces the per-deal bound. ``availability=None`` (authority
    unreachable) closes nothing — the next delta or reconcile converges. A
    resource missing from the view is treated as exhausted: the ledger is the
    source of sellable truth, and a listing whose resource is gone must not
    stay open.
    """
    if availability is None:
        return []
    stale: list[str] = []
    for source in sources:
        if source.status.strip() != "open":
            continue

        def exhausted(source: QuotaListingSource = source) -> Verdict:
            available = _available_units(availability, source)
            return "exhausted" if available is None or available < 1 else None

        if judge(source, exhausted) is not None:
            stale.append(source.listing_id)
    return stale


def reopenable_listing_ids(
    sources: Iterable[QuotaListingSource],
    *,
    availability: AvailabilityView | None,
    judge: Judge,
) -> list[str]:
    """Closed listings whose quota resource has units again.

    ``availability=None`` reopens nothing: with no consumption information
    everything would look free, and reopening on ignorance over-sells. Only a
    listing reconciliation closed is a candidate; one its seller closed stays
    closed until the seller reopens it, whatever quota returns.
    """
    if availability is None:
        return []
    reopenable: list[str] = []
    for source in sources:
        if source.status.strip() != "closed" or source.closed_by != "reconciliation":
            continue

        def replenished(source: QuotaListingSource = source) -> Verdict:
            available = _available_units(availability, source)
            return None if available is not None and available >= 1 else "exhausted"

        if judge(source, replenished) is None:
            reopenable.append(source.listing_id)
    return reopenable
