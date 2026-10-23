"""A quota-backed listing: its durable binding, its source recheck, and its reconciliation.

Every capacity effect, reconciliation, and recheck reads the listing's durable
binding, never the published listing.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from core_storefront.domain_registry import (
    StorefrontDomainBindingError,
    StorefrontDomainRegistration,
    StorefrontDomainRegistry,
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
    decode_stored,
)

LISTING_SOURCE_SCHEMA_VERSION = 1
ACCEPTED_LISTING_SLOT = "listing"


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

    With ``pool_id`` (a bound listing's recorded pool) the resource must still be
    in that pool. A pool whose declarations do not resolve is refused.
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


def domain_registry(
    contributions: SellingContributions, domain: MarketDomainContract
) -> StorefrontDomainRegistry:
    """The registry a storefront's per-negotiation artifacts are read and written under."""
    return StorefrontDomainRegistry((registration(contributions, domain),))


async def record_accepted_listing(
    contributions: SellingContributions,
    repository: Any,
    *,
    domain: MarketDomainContract,
    negotiation_id: str,
    listing_id: str,
    listing_record: Mapping[str, Any],
) -> None:
    """Record the listing a buyer accepts with the negotiation, before its success is recorded.

    Artifacts are keyed by the thread's domain binding, so the thread first takes
    its listing's binding.
    """
    await repository.copy_listing_binding_to_thread(
        negotiation_id=negotiation_id, listing_id=listing_id
    )
    await repository.save_domain_artifact(
        negotiation_id=negotiation_id,
        artifact_slot=ACCEPTED_LISTING_SLOT,
        value=domain_listing(contributions, listing_record),
        registry=domain_registry(contributions, domain),
    )


async def accepted_listing(
    contributions: SellingContributions,
    repository: Any,
    *,
    domain: MarketDomainContract,
    negotiation_id: str,
    listing_id: str,
) -> dict[str, Any]:
    """The listing the buyer accepted, as the domain's listing schema reads it.

    An unbound thread was accepted before acceptances were recorded and reads
    the stored listing. A bound thread must name ``listing_id`` and carry its
    record; otherwise it is refused.
    """
    try:
        binding = await repository.load_thread_binding(negotiation_id=negotiation_id)
    except StorefrontDomainBindingError:
        return domain_listing(contributions, await repository.load_listing(listing_id=listing_id))
    if binding.listing_id != listing_id:
        raise ValueError(
            f"negotiation {negotiation_id!r} accepted listing {binding.listing_id!r}, not {listing_id!r}"
        )
    recorded = await repository.load_domain_artifact(
        negotiation_id=negotiation_id,
        artifact_slot=ACCEPTED_LISTING_SLOT,
        registry=domain_registry(contributions, domain),
    )
    if recorded is None:
        raise ValueError(f"negotiation {negotiation_id!r} has no record of its accepted listing")
    return domain_listing(contributions, _as_mapping(recorded))


async def accepted_listing_resource(
    contributions: SellingContributions,
    repository: Any,
    *,
    domain: MarketDomainContract,
    negotiation_id: str,
    listing_id: str,
) -> Mapping[str, Any]:
    """The ``listing_resource`` of the listing the buyer accepted."""
    listing = await accepted_listing(
        contributions, repository, domain=domain, negotiation_id=negotiation_id, listing_id=listing_id
    )
    return listing["listing_resource"]


def domain_listing(
    contributions: SellingContributions, record: Mapping[str, Any] | None
) -> dict[str, Any]:
    """A stored listing narrowed to the domain's listing schema and validated by it."""
    if record is None:
        raise ValueError("the listing is gone from the local store")
    values = {
        name: decode_stored(record[name])
        for name in contributions.listing_schema.model_fields
        if record.get(name) is not None
    }
    return contributions.listing_schema.model_validate(values).model_dump(mode="json")


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


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

    A listing whose projection names no quota resource is refused here, before
    anything is published. Several listings may sell one resource, so the
    derivation identity is the listing itself.
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
    """A listing's capacity binding and the pool its durable record names."""

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
    """A check run before every seller decision and acceptance, against the listing's own site.

    It is a declared mismatch when the listing's projection no longer names the
    bound quota resource, or the resource has left the bound pool, or that pool is
    disabled, stops advertising the offering mode, or changes its backing. An
    unreadable source is unverifiable, which the runtime refuses as retryable.
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
        {"listing_resource": decode_stored(record.get("listing_resource"))}
    )
    return listing.listing_resource.model_dump(mode="json")


# Reconciliation: pure functions over listing bindings and an availability view.

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
    """Open listings whose quota resource is exhausted or gone.

    ``availability=None`` (authority unreachable) closes nothing.
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

    ``availability=None`` reopens nothing, and a listing its seller closed stays
    closed.
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
