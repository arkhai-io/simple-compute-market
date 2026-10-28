from __future__ import annotations

import json
import logging
import enum
import sqlite3
from dataclasses import dataclass, field
from collections.abc import Collection
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from market_capability_admissibility import AdmissibilityProblem, Declaration

from arkhai_vms import (
    DIMENSION_KEYS,
    listing_pool_key,
    listing_resource_key,
    listing_shape_key,
)

from market_resource_pools_contracts.backing import (
    CapacityBacking,
    capacity_backing,
    labels_reconciled_by_availability,
)

from arkhai_vms_listings.asking_rates import resolve_vm_asking_rates
from arkhai_vms_listings.listing_comparison import REFUSE, compare_listing
from arkhai_vms_listings.listing_shapes import (
    SHAPE_SOURCE_DEFAULT,
    SHAPE_SOURCE_OVERRIDE,
    ResolvedShape,
    ShapeResolution,
    resolve_shape,
    resolve_vm_listing_shapes,
)
from arkhai_vms_listings.listing_cardinality_mode import (
    resolve_vm_listing_cardinality_mode,
)
from arkhai_vms_listings.pool_descriptors import resolve_region, resolve_sla
from arkhai_vms_listings.pricing_resolution import (
    RETIRED_PRICING_KEYS,
    GpuPricingFields,
    resolve_family_rates,
    resolve_gpu_pricing,
)


if TYPE_CHECKING:
    from market_resource_pools import ResolvedPool

logger = logging.getLogger(__name__)


def positive_gpu_count(value: Any) -> int | None:
    """A usable enumeration quantity, or ``None``.

    Exactly a positive integer. Nothing here substitutes a count: a listing is
    "N GPUs of this resource", and a missing, zero, or malformed N is not a
    1-GPU slice that happens to be unlabelled.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


class ShapeFeasibility(Protocol):
    """Whether a source could serve the claim a listing would produce.

    Injected by the storefront so this package takes no dependency on the site
    authority's predicate. Resource feasibility only: the site's reservation
    remains the admission boundary.
    """

    def member_feasible(
        self,
        listing_resource: Mapping[str, Any],
        *,
        pool_id: str,
        member: Mapping[str, Any],
        use_available: bool,
    ) -> bool:
        """Judge one projected member against its declared capacity, or, with
        ``use_available``, against its reported availability (declared capacity
        when it reports none)."""

    def bucket_feasible(
        self,
        listing_resource: Mapping[str, Any],
        *,
        bucket: Mapping[str, Any],
    ) -> bool:
        """Judge one capacity bucket's current availability."""


def site_id_for_listing(db_path: str, listing_id: str) -> str | None:
    """Return the exact trusted site from the common listing binding."""

    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        row = conn.execute(
            "SELECT site_id FROM storefront_listing_bindings WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row and row[0] else None


def pool_id_for_listing(db_path: str, listing_id: str) -> str | None:
    """Return the exact pool from the common listing binding."""

    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        row = conn.execute(
            "SELECT pool_id FROM storefront_listing_bindings WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row and row[0] else None


def _member_available_units(
    member_total: int,
    member_key: tuple[str | None, str],
    member_availability: dict[tuple[str | None, str], int] | None,
) -> int:
    """Units of one pool member actually available, capped by both its
    own total and (when known) the aggregated site snapshot's answer for
    that ``(site, resource_id)`` key. ``None`` availability means the
    caller has no consumption information -- treated as fully available,
    corrected authoritatively by the reserve path later.
    """
    if member_availability is None:
        return member_total
    return max(0, min(member_total, int(member_availability.get(member_key, 0))))


VM_OFFERING_MODE = "vm"

#: The VM market's override terms, flattened beside shapes and clauses.
VM_OVERRIDE_TERMS = ("sla", "max_duration_seconds", "pricing")

#: Override terms the VM market does not read. A stored override may carry
#: them; derivation reports them rather than holding the pool.
RETIRED_VM_OVERRIDE_TERMS = RETIRED_PRICING_KEYS


def vm_override_view(
    *,
    listing_shapes: Any = None,
    settlements: Any = None,
    asking_rates: Any = None,
    terms: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """One VM override as derivation reads it: shapes, clauses, asking rates,
    and each VM term at the top level, ``None`` where the override states
    nothing."""
    terms = terms if isinstance(terms, Mapping) else {}
    return {
        "listing_shapes": listing_shapes,
        "settlements": settlements,
        "asking_rates": asking_rates,
        **{name: terms.get(name) for name in VM_OVERRIDE_TERMS},
        "retired_terms": tuple(
            name for name in RETIRED_VM_OVERRIDE_TERMS if name in terms
        ),
    }


def _site_pool_overrides(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str], dict[str, Any]]:
    """The storefront's VM pool overrides, keyed by ``(site_id, pool_id)``.

    The first tier of shape and commercial-term resolution on the projection
    path. Read here, inside the derivation every structural-key caller runs,
    because an override's shapes change listing keys: publication and source
    reconciliation must see the same tier or reconciliation would close every
    listing an override shaped. Only the VM offering mode's overrides are VM
    derivation's; another mode's belong to its own market.

    The store is the pool-override kit's, read through its reader. An override
    the kit could not decode carries its ``problems``, so derivation holds the
    pool rather than falling through to a lower tier.
    """
    # Local import: buyers install this package without the pool-override kit,
    # and only storefront derivation reads overrides.
    from market_pool_overrides import read_pool_overrides

    return {
        (stored.site_id, stored.pool_id): {
            **vm_override_view(
                listing_shapes=stored.listing_shapes,
                settlements=stored.settlements,
                asking_rates=stored.asking_rates,
                terms=stored.terms,
            ),
            "problems": stored.problems,
        }
        for stored in read_pool_overrides(conn, offering_mode=VM_OFFERING_MODE)
    }


@dataclass(frozen=True)
class _ProjectedResourceUsage:
    """One member's identity and GPU usage; zero GPUs when it declares none."""

    resource_id: str
    total: int
    available: int


# Why a member yields no usage. A malformed count makes the member
# unresolvable, because an unreadable count is not a zero. A member declaring no
# GPU count, or a zero, is still a member: its GPU usage is zero, and whether it
# serves a shape is the shape's feasibility to decide.
_GPU_COUNT_MALFORMED = "malformed"
# The projection contract requires every member to state its resource kind. A
# member that does not is malformed rather than incapable, so it is held like
# one with an unreadable count rather than judged infeasible.
_RESOURCE_TYPE_ABSENT = "resource_type_absent"


def _projected_resource_usage(
    resource: Mapping[str, Any],
    *,
    site_id: str,
    member_availability: dict[tuple[str | None, str], int] | None,
) -> "_ProjectedResourceUsage | str | None":
    """Derive one projected resource's identity and GPU usage.

    Returns ``None`` if it has no physical_resource_id to key on,
    ``_GPU_COUNT_MALFORMED`` when its declared GPU count cannot be read, or
    ``_RESOURCE_TYPE_ABSENT`` when it states no resource kind. A member
    declaring no GPU count uses zero GPUs. Pure and independently testable: no
    dict mutation, no accumulation, just this one resource's own facts.
    """
    resource_id = str(resource.get("physical_resource_id") or "")
    if not resource_id:
        return None
    resource_type = resource.get("resource_type")
    if not isinstance(resource_type, str) or not resource_type.strip():
        return _RESOURCE_TYPE_ABSENT
    capacity = resource.get("capacity") or {}
    raw_total = capacity.get("gpu_count")
    if raw_total is None:
        raw_total = 0
    if isinstance(raw_total, bool) or not isinstance(raw_total, int) or raw_total < 0:
        return _GPU_COUNT_MALFORMED
    total = raw_total
    available_field = resource.get("available")
    if available_field is not None:
        # The projection already carries this resource's live
        # availability -- use it directly, regardless of whether a
        # member_availability lookup is also available. This is
        # authoritative data from the projection itself, not a
        # fallback source to be skipped whenever a different fallback
        # (member_availability) happens to be present or absent.
        available = max(
            0, min(total, int((available_field or {}).get("gpu_count") or 0))
        )
    elif member_availability is not None:
        available = _member_available_units(
            total,
            (site_id, resource_id),
            member_availability,
        )
    else:
        available = total
    return _ProjectedResourceUsage(resource_id, total, available)


def _bucket_gpu_count(bucket: Mapping[str, Any]) -> int | None:
    """One capacity bucket's available GPU count, or None if unusable.

    `capacity_bucket_projection` collapses a resource with no `available`
    field at all into an empty `available` dict rather than omitting the
    resource -- so a present-but-empty dict means "this producer predates
    per-resource availability," not "authoritative zero." Distinguishing
    that (None, treated as unusable -- caller falls back) from a bucket
    that genuinely reports zero available units (0, trusted) mirrors
    ``_projected_resource_usage``'s own None-vs-zero handling for the
    per-resource projection.
    """
    available = bucket.get("available") or {}
    if "gpu_count" not in available:
        return None
    try:
        return int(available["gpu_count"])
    except (TypeError, ValueError):
        return None


def _fungible_availability_from_buckets(
    pool_id: str,
    capacity_buckets: list[Mapping[str, Any]] | None,
) -> tuple[int, int] | None:
    """(max_member_available, available_gpu_count) from this
    pool's matching capacity buckets, or None if the caller should fall
    back to the resource-list walk instead.

    ``capacity_buckets`` is ``None`` when the capacity-bucket family has
    never loaded for this pool's site (or the caller has no bucket data
    to offer at all) -- every pool falls back in that case, matching
    "ignorance is not zero." A *loaded* family -- including a genuinely
    empty list -- is trusted: ``capacity_bucket_projection`` is built
    from the site's complete enabled-resource inventory, so a pool with
    any enabled member necessarily contributes at least one matching
    bucket entry once the family has loaded. The absence of any matching
    entry in a loaded family is therefore itself the answer (this pool
    currently has no enabled members with available capacity), not
    missing data -- collapsing that into "fall back" would let a
    resource-pool projection generation fetched at a different moment
    contradict the capacity-bucket family's own authoritative answer.

    A bucket entry that exists for this pool but is individually
    unreadable (predates per-resource `available`, see
    `_bucket_gpu_count`) is different again: excluded from the computed
    totals, and if every matching entry for this pool is unreadable this
    way, treated the same as "no usable data" -- an unreadable entry is
    not the same as a confirmed absence.

    Each readable bucket already represents a group of members with
    identical current availability (``capacity_bucket_projection``'s own
    grouping criteria), so the pool's per-member ceiling is the max
    across matching buckets, not a per-resource max -- cheaper and, once
    bucket data exists, no less precise, since resources are only ever
    split into more than one bucket when their availability genuinely
    differs.
    """
    if capacity_buckets is None:
        return None
    max_member_available = 0
    available_gpu_count = 0
    saw_matching_entry = False
    saw_usable_entry = False
    for bucket in capacity_buckets:
        if str(bucket.get("pool_id") or "") != pool_id:
            continue
        saw_matching_entry = True
        bucket_available = _bucket_gpu_count(bucket)
        if bucket_available is None:
            continue
        saw_usable_entry = True
        bucket_count = int(bucket.get("resource_count") or 0)
        available_gpu_count += bucket_available * bucket_count
        max_member_available = max(max_member_available, bucket_available)
    if saw_usable_entry:
        return max_member_available, available_gpu_count
    if saw_matching_entry:
        # Every matching entry was individually unreadable -- not a
        # confirmed absence, fall back.
        return None
    # No matching entry at all in a loaded family: authoritative zero,
    # not missing data -- see this function's own docstring.
    return 0, 0


@dataclass
class _SiteDerivationReport:
    """What one site's latest derivation could not publish, and why.

    Surfaced in the storefront's system status so an operator sees why a pool
    publishes nothing or why its listings are held.
    """

    compatibility_rule: bool = False
    unresolvable_pools: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unresolvable_members: dict[str, str] = field(default_factory=dict)
    members_without_resource_type: dict[str, str] = field(default_factory=dict)
    pools_without_default_shapes: set[str] = field(default_factory=set)
    unreadable_shapes: dict[str, list[str]] = field(default_factory=dict)
    inadmissible_listing_shapes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    unusable_shape_constraints: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    unreadable_asking_rates: dict[str, list[str]] = field(default_factory=dict)
    unpublished_asking_rates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    infeasible_shapes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    undeclared_attributes: dict[str, dict[str, Any]] = field(default_factory=dict)
    regionless_pools: set[str] = field(default_factory=set)
    retired_pricing_keys: dict[str, list[str]] = field(default_factory=dict)
    unreadable_family_rates: dict[str, list[str]] = field(default_factory=dict)
    families_without_rates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "compatibility_rule": self.compatibility_rule,
            "unresolvable_pools": {
                pool_id: list(codes)
                for pool_id, codes in sorted(self.unresolvable_pools.items())
            },
            "unresolvable_members": dict(sorted(self.unresolvable_members.items())),
            "members_without_resource_type": dict(
                sorted(self.members_without_resource_type.items())
            ),
            "pools_without_default_shapes": sorted(self.pools_without_default_shapes),
            "unreadable_shapes": dict(sorted(self.unreadable_shapes.items())),
            "inadmissible_listing_shapes": dict(
                sorted(self.inadmissible_listing_shapes.items())
            ),
            "unusable_shape_constraints": dict(
                sorted(self.unusable_shape_constraints.items())
            ),
            "unreadable_asking_rates": dict(sorted(self.unreadable_asking_rates.items())),
            "unpublished_asking_rates": dict(sorted(self.unpublished_asking_rates.items())),
            "infeasible_shapes": dict(sorted(self.infeasible_shapes.items())),
            "undeclared_attributes": dict(sorted(self.undeclared_attributes.items())),
            "regionless_pools": sorted(self.regionless_pools),
            "retired_pricing_keys": {
                pool_id: sorted(set(keys))
                for pool_id, keys in sorted(self.retired_pricing_keys.items())
            },
            "unreadable_family_rates": {
                pool_id: sorted(set(problems))
                for pool_id, problems in sorted(self.unreadable_family_rates.items())
            },
            "families_without_rates": dict(sorted(self.families_without_rates.items())),
        }


#: A derivation report's pool-keyed categories, each as the action a
#: publication cycle records and the reason code it records it under, and the
#: name the category's detail is given in the entry. A ``hold`` holds the pool's
#: listings; a ``report`` holds nothing.
_POOL_ENTRIES: dict[str, tuple[str, str, str]] = {
    "unresolvable_pools": ("hold", "pool_unresolvable", "problems"),
    "unreadable_shapes": ("hold", "listing_shapes_unreadable", "problems"),
    "inadmissible_listing_shapes": ("report", "listing_shape_inadmissible", "findings"),
    "unusable_shape_constraints": ("report", "shape_constraints_unusable", "findings"),
    "unreadable_asking_rates": ("hold", "asking_rates_unreadable", "problems"),
    "unpublished_asking_rates": ("report", "asking_rate_shape_unpublished", "shapes"),
    "infeasible_shapes": ("report", "listing_shape_infeasible", "shapes"),
    "retired_pricing_keys": ("report", "retired_pricing_keys", "keys"),
    "unreadable_family_rates": ("hold", "family_rates_unreadable", "problems"),
    "families_without_rates": ("report", "families_without_rates", "entries"),
}

#: The member-keyed categories, as ``_POOL_ENTRIES`` states the pool-keyed ones.
#: A member whose ``gpu_count`` cannot be read holds its listings (a fungible
#: pool's whole range). A member declaring no GPUs is not reported on its own
#: account: it yields no default shape and is judged for any shape stated.
_MEMBER_ENTRIES: dict[str, tuple[str, str]] = {
    "unresolvable_members": ("hold", "member_gpu_count_unreadable"),
    "members_without_resource_type": ("hold", "member_resource_type_missing"),
}

#: What the report of a pool that publishes nothing for want of stated shapes
#: says, so an operator reading system status learns what to change.
POOL_SHAPES_REQUIRED_REASON = "listing_shapes_required"
POOL_SHAPES_REQUIRED_MESSAGE = (
    "the VM default generates GPU shapes only and no enabled member declares a "
    "positive GPU count; state listing_shapes for this pool, on its hint or a "
    "storefront override, to publish it"
)


def site_derivation_entries(report: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """One site's derivation report as the holds and reports a cycle records.

    ``report`` is a site's report as a derivation's ``reports`` receives it.
    Each entry is its action and its reason code with the pool or member it
    concerns and any detail, in a stable order.
    """
    entries: list[tuple[str, dict[str, Any]]] = []
    if report.get("compatibility_rule"):
        # The site predates the pool declarations: every pool reads as
        # capacity-backed, with delivery authorizing advertisement.
        entries.append(("report", {"reason": "legacy_producer_backing"}))
    for category, (action, reason) in _MEMBER_ENTRIES.items():
        for resource_id, pool_id in (report.get(category) or {}).items():
            entries.append(
                (
                    action,
                    {"pool_id": pool_id, "physical_resource_id": resource_id, "reason": reason},
                )
            )
    for pool_id in report.get("regionless_pools") or ():
        entries.append(("hold", {"pool_id": pool_id, "reason": "pool_region_missing"}))
    for pool_id in report.get("pools_without_default_shapes") or ():
        entries.append(
            (
                "report",
                {
                    "pool_id": pool_id,
                    "reason": POOL_SHAPES_REQUIRED_REASON,
                    "message": POOL_SHAPES_REQUIRED_MESSAGE,
                },
            )
        )
    for pool_id, finding in (report.get("undeclared_attributes") or {}).items():
        entries.append(
            (
                "report",
                {
                    "pool_id": pool_id,
                    "reason": "claimed_attribute_undeclared",
                    "attribute": finding.get("attribute"),
                    "value": finding.get("value"),
                },
            )
        )
    for category, (action, reason, detail) in _POOL_ENTRIES.items():
        for pool_id, value in (report.get(category) or {}).items():
            entries.append((action, {"pool_id": pool_id, "reason": reason, detail: value}))
    return entries


def _families_without_rates(
    shape: "ResolvedShape",
    family_rates: Mapping[str, Any],
    clauses: Any,
) -> list[dict[str, Any]]:
    """Per clause asset, the families ``shape`` names that have no rate in it.

    Reported, not refused: a family without a rate is not charged. Only a
    shape-priced listing has anything to report, and only clauses stated as
    mappings name their asset here.
    """
    if not family_rates or not isinstance(clauses, list):
        return []
    assets = sorted(
        {
            str(clause["asset"])
            for clause in clauses
            if isinstance(clause, Mapping) and isinstance(clause.get("asset"), str)
        }
    )
    out: list[dict[str, Any]] = []
    for asset in assets:
        families = sorted(
            family
            for family in shape.shape
            if not any(
                entry.get("asset") == asset for entry in family_rates.get(family, ())
            )
        )
        if families:
            out.append(
                {"shape_digest": shape.digest, "asset": asset, "families": families}
            )
    return out


@dataclass(frozen=True)
class PoolHintResolutionSettings:
    """Storefront-wide policy for how much a projected pool's own
    declared hints are trusted, as opposed to the storefront's own
    configured/overridden values.

    Defaults are the conservative posture for a brand-new trust decision
    with no existing behavior to preserve: `accept_pool_declared_sla`
    defaults `False` (a site's self-reported SLA claim is not published
    unless a storefront operator explicitly opts in), matching this
    being new capability a storefront must choose to enable, not a
    migration of something already trusted today.

    `gpu_pricing_defaults_by_model`/`gpu_pricing_flat_default` and
    `family_rate_defaults` are the lowest tier of the pricing precedence
    chain (see `arkhai_vms_listings.pricing_resolution`) -- no trust
    decision involved, since config defaults are the storefront operator's
    own values, not a site's; defaulted here only so every caller doesn't
    need to construct empty ones. `family_rate_defaults` uses the pricing
    hint's family-grouped nesting.

    `admissibility_default` is the storefront's parsed
    ``[admissibility.defaults.vm]``, the lower tier of every listing's
    admissibility policy and the whole policy of a generated listing; ``None`` when the storefront configures none.
    """

    accept_pool_declared_sla: bool = False
    default_sla: float = 0.0
    gpu_pricing_defaults_by_model: Mapping[str, Any] = None  # type: ignore[assignment]
    gpu_pricing_flat_default: Any = None
    family_rate_defaults: Mapping[str, Any] = None  # type: ignore[assignment]
    admissibility_default: Declaration | None = None

    def __post_init__(self) -> None:
        # dataclass(frozen=True) needs object.__setattr__ to fill in
        # mutable-default-free placeholders after construction, since a
        # bare `{}`/instance can't be a dataclass field default.
        if self.gpu_pricing_defaults_by_model is None:
            object.__setattr__(self, "gpu_pricing_defaults_by_model", {})
        if self.gpu_pricing_flat_default is None:
            object.__setattr__(self, "gpu_pricing_flat_default", GpuPricingFields())
        if self.family_rate_defaults is None:
            object.__setattr__(self, "family_rate_defaults", {})


_DEFAULT_POOL_HINT_RESOLUTION_SETTINGS = PoolHintResolutionSettings()


def _projected_pool_rows(
    pool: Mapping[str, Any],
    *,
    site_id: str,
    member_availability: dict[tuple[str | None, str], int] | None,
    capacity_buckets: list[Mapping[str, Any]] | None,
    declaration: "ResolvedPool",
    holds: set[tuple[str, str, str]],
    report: _SiteDerivationReport,
    shape_feasible: ShapeFeasibility,
    hint_resolution: PoolHintResolutionSettings = _DEFAULT_POOL_HINT_RESOLUTION_SETTINGS,
    declared_only: bool = False,
    override: Mapping[str, Any] | None = None,
    excluded: set[tuple[str, str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Build zero or more pool_rows entries from one projected pool.

    Returns nothing for a pool with no `pool_id`, one its site does not declare
    advertisable for the ``vm`` mode or declares disabled, and one that is
    held. Otherwise returns exactly one row for a ``fungible`` pool, or one row
    per enabled member for a ``specific_resource`` pool -- a pool's
    ``listing_cardinality_mode`` (from its projected `policy_tags`,
    domain-resolved by `resolve_vm_listing_cardinality_mode`) decides which.
    An explicit tag always wins; its *absence* falls back to the structural
    heuristic (`member_count == 1` -> specific_resource) so an untagged pool's
    publication shape does not change out from under an existing
    derived-listing mapping.

    Shapes and commercial terms resolve through the storefront's override
    before the pool's own hints and the storefront's configuration:
    ``override`` is the site-scoped override for this site and pool, if any.
    It is not required: a pool with none still resolves through its hints and
    configured defaults, and a pool that resolves no price is left to the
    downstream ``publish_priceless`` handling.

    Every row carries the pool's resolved shapes, each GPU model's resolved
    terms (``pricing_by_model``, with a shape stating no GPUs under ``None``),
    and the shapes its source members are feasible for (``feasible_shapes``).
    A listing's terms are those of its shape's model.
    """
    pool_id = str(pool.get("pool_id") or "").strip()
    if not pool_id:
        return []
    # A listing may advertise only a mode its pool declares advertisable,
    # backed or not; delivery is rechecked separately by every execution layer.
    # A pool its site declares disabled is a withdrawn source.
    if not declaration.advertises("vm") or not declaration.enabled:
        return []
    usages: list[_ProjectedResourceUsage] = []
    members_by_id: dict[str, Mapping[str, Any]] = {}
    malformed_members: list[str] = []
    enabled_member_count = 0
    for resource in pool.get("resources") or []:
        if not resource.get("enabled", True):
            continue
        usage = _projected_resource_usage(
            resource,
            site_id=site_id,
            member_availability=member_availability,
        )
        if usage is None:
            continue
        enabled_member_count += 1
        resource_id = str(resource.get("physical_resource_id"))
        if usage == _GPU_COUNT_MALFORMED:
            malformed_members.append(resource_id)
            report.unresolvable_members[resource_id] = pool_id
        elif usage == _RESOURCE_TYPE_ABSENT:
            malformed_members.append(resource_id)
            report.members_without_resource_type[resource_id] = pool_id
        elif isinstance(usage, _ProjectedResourceUsage):
            usages.append(usage)
            members_by_id[usage.resource_id] = resource

    metadata = pool.get("pool_metadata") or {}
    policy_tags = metadata.get("policy_tags") or {}

    structural_default = (
        "specific_resource" if enabled_member_count == 1 else "fungible"
    )
    cardinality = resolve_vm_listing_cardinality_mode(
        policy_tags,
        structural_default=structural_default,
    )
    mode = cardinality.mode
    if malformed_members:
        # A fungible pool's range is its largest member's count, which cannot
        # be known while one member's count is unreadable, so the whole pool is
        # held. A specific-resource pool's other members are unaffected.
        if mode != "specific_resource":
            holds.add(("pool", site_id, pool_id))
            return []
        for resource_id in malformed_members:
            holds.add(("resource", site_id, resource_id))

    # An override the store could not decode is unreadable, not absent: it holds
    # the pool rather than letting a lower tier speak for it.
    if override is not None and override.get("problems"):
        report.unreadable_shapes[pool_id] = [
            f"{SHAPE_SOURCE_OVERRIDE}: {problem}" for problem in override["problems"]
        ]
        holds.add(("pool", site_id, pool_id))
        return []

    # A stated list the VM vocabulary cannot read holds the pool's listings and
    # never falls back to a lower source's shapes.
    resolution = resolve_vm_listing_shapes(
        policy_tags,
        [members_by_id[usage.resource_id] for usage in usages],
        configured_default=hint_resolution.admissibility_default,
        override_shapes=override.get("listing_shapes") if override else None,
    )
    if resolution.unreadable:
        report.unreadable_shapes[pool_id] = [
            f"{resolution.source}: {problem}" for problem in resolution.problems
        ]
        holds.add(("pool", site_id, pool_id))
        return []
    # The default generates GPU shapes only, so a pool stating no shapes whose
    # members declare no GPUs publishes nothing; reported once, for the pool,
    # because that is where its operator states the shapes it should sell. A
    # pool with no enabled member publishes nothing for want of members, which
    # stated shapes would not change, so it is not reported.
    if not resolution.stated and usages and not any(usage.total > 0 for usage in usages):
        report.pools_without_default_shapes.add(pool_id)

    # Every declaration was read, so a listing whose policy cannot be computed,
    # or whose offer its own policy excludes, is not derived and an open
    # listing for it closes, while the pool's other listings publish. Holding
    # it instead would keep advertising what the storefront's policy may
    # exclude. See openspec/specs/storefront-publication/spec.md#requirement-a-vm-listing-whose-admissibility-cannot-be-computed-closes.
    shapes = _admissible_shapes(resolution, pool_id=pool_id, report=report)
    # Recorded apart from the pool's listings because a later hold on the whole
    # pool, for an unreadable rate, must not keep an excluded listing open.
    if excluded is not None:
        admitted = {shape.digest for shape in shapes}
        excluded.update(
            (site_id, pool_id, listing.shape.digest)
            for listing in resolution.listings
            if listing.shape.digest not in admitted
        )

    # Asking rates hold the pool on the same terms as shapes: a rate the seller
    # believes they published is not silently dropped to a lower tier.
    rates = resolve_vm_asking_rates(
        policy_tags,
        override_rates=override.get("asking_rates") if override else None,
    )
    if rates.unreadable:
        report.unreadable_asking_rates[pool_id] = [
            f"{rates.source}: {problem}" for problem in rates.problems
        ]
        holds.add(("pool", site_id, pool_id))
        return []
    unpublished_rates = rates.unpublished(shape.digest for shape in shapes)
    if unpublished_rates:
        report.unpublished_asking_rates[pool_id] = [
            {"shape_digest": digest, "shape": shape}
            for digest, shape in sorted(unpublished_rates.items())
        ]

    def _tier(field_name: str) -> Any:
        """The site-scoped override's value for ``field_name``, if it states one."""
        if override is not None and override.get(field_name) is not None:
            return override[field_name]
        return None

    # Region is a physical fact, so no override states it: it is the pool's
    # own hint or nothing. Every VM listing publishes one, so publication
    # publishes and refreshes nothing from a pool stating none. The rows are
    # still derived: region does not bear on capacity, so availability
    # reconciliation keeps closing a sold-out listing of such a pool.
    region = resolve_region(policy_tags)
    if region is None:
        report.regionless_pools.add(pool_id)
    sla = resolve_sla(
        policy_tags,
        accept_pool_declared_sla=hint_resolution.accept_pool_declared_sla,
        storefront_override=_tier("sla"),
        config_default=hint_resolution.default_sla,
    )
    storefront_pricing_override = GpuPricingFields(
        max_duration_seconds=_tier("max_duration_seconds"),
        settlements=_tier("settlements"),
    )
    if override is not None and override.get("retired_terms"):
        report.retired_pricing_keys.setdefault(pool_id, []).extend(
            f"override terms.{name}" for name in override["retired_terms"]
        )

    base_fields = {
        "site_id": site_id,
        "pool_id": pool_id,
        "region": region,
        "sla": sla,
        "listing_cardinality_mode": mode,
        "offering_mode": "vm",
        "capacity_backing": declaration.backing.label,
        "listing_cardinality_mode_explanation": cardinality.fallback_explanation,
        "listing_cardinality_mode_deprecated_key_notice": (
            cardinality.deprecated_key_notice
        ),
    }

    pool_buckets = (
        None
        if capacity_buckets is None
        else [
            bucket
            for bucket in capacity_buckets
            if str(bucket.get("pool_id") or "") == pool_id
        ]
    )

    def _judge_members(shape: ResolvedShape, members: list[Mapping[str, Any]]) -> str | None:
        """None when feasible, else what the shape is not feasible against."""
        listing_resource = _shape_listing_resource(
            shape, pool_id=pool_id, region=region, capacity_backing=declaration.backing.label,
            resource_id=(
                str(members[0].get("physical_resource_id"))
                if mode == "specific_resource" and members
                else None
            ),
        )

        def declared() -> str | None:
            feasible = any(
                shape_feasible.member_feasible(
                    listing_resource, pool_id=pool_id, member=member, use_available=False
                )
                for member in members
            )
            return None if feasible else "declared"

        def available() -> str | None:
            readable_buckets = (
                [bucket for bucket in pool_buckets if bucket.get("available")]
                if pool_buckets is not None
                else None
            )
            if mode != "specific_resource" and pool_buckets is not None and (
                readable_buckets or not pool_buckets
            ):
                # A loaded bucket family is authoritative for fungible
                # availability, and a loaded family naming no entry for the pool
                # means none is available. Entries that predate per-resource
                # availability are unreadable, and only when every entry is does
                # the pool fall back to its members.
                feasible = any(
                    shape_feasible.bucket_feasible(listing_resource, bucket=bucket)
                    for bucket in readable_buckets or []
                )
            else:
                feasible = any(
                    shape_feasible.member_feasible(
                        listing_resource, pool_id=pool_id, member=member, use_available=True
                    )
                    for member in members
                )
            return None if feasible else "available"

        # A declared-only derivation judges declared capacity for every
        # backing; otherwise the pool's backing decides whether availability
        # bounds the shape.
        if declared_only:
            return declared()
        return declaration.backing.judge(declared, available)

    # Terms resolve per GPU model because the hint and configured tiers are
    # keyed by model; a listing takes its shape's model's terms. A shape
    # stating no GPUs groups under ``None``: it resolves only the override's and
    # the flat default's terms and the unkeyed families' rates, so a pool whose
    # only terms are per GPU model leaves it with no settlement option.
    models = sorted(
        {shape.gpu_model for shape in shapes},
        key=lambda model: (model is not None, model or ""),
    )
    pricing_by_model = {
        model: resolve_gpu_pricing(
            policy_tags,
            gpu_model=model,
            storefront_override=storefront_pricing_override,
            config_defaults_by_model=hint_resolution.gpu_pricing_defaults_by_model,
            flat_default=hint_resolution.gpu_pricing_flat_default,
        )
        for model in models
    }
    # Family rates resolve per model for the same reason: the GPU family is
    # keyed by model.
    family_rates_by_model: dict[str | None, Mapping[str, Any]] = {}
    unreadable_rates: list[str] = []
    for model in models:
        family = resolve_family_rates(
            policy_tags,
            gpu_model=model,
            storefront_override=override.get("pricing") if override else None,
            config_defaults=hint_resolution.family_rate_defaults,
        )
        family_rates_by_model[model] = family.rates
        unreadable_rates.extend(family.problems)
        if family.retired_keys:
            report.retired_pricing_keys.setdefault(pool_id, []).extend(
                f"hint {key}" for key in family.retired_keys
            )
    # An unreadable rate holds the pool, as an unreadable asking rate does:
    # pricing from what remains would publish a lower tier's rate, a price
    # nobody stated for this pool. Its listings keep their last-published terms.
    if unreadable_rates:
        report.unreadable_family_rates[pool_id] = sorted(set(unreadable_rates))
        holds.add(("pool", site_id, pool_id))
        return []
    for shape in shapes:
        unrated = _families_without_rates(
            shape,
            family_rates_by_model.get(shape.gpu_model) or {},
            pricing_by_model[shape.gpu_model].settlements,
        )
        if unrated:
            report.families_without_rates.setdefault(pool_id, []).extend(unrated)
    served: set[str] = set()
    not_feasible: dict[str, str] = {}

    def _feasible_shapes(members: list[Mapping[str, Any]]) -> tuple[ResolvedShape, ...]:
        feasible: list[ResolvedShape] = []
        for shape in shapes:
            finding = _judge_members(shape, members)
            if finding is None:
                feasible.append(shape)
                served.add(shape.digest)
            elif not_feasible.get(shape.digest) != "available":
                # A shape some member serves on declaration but none on current
                # availability is reported as unavailable, not undeclared.
                not_feasible[shape.digest] = finding
        return tuple(feasible)

    shape_fields = {
        "listing_shapes": shapes,
        "shape_source": resolution.source,
        "pricing_by_model": pricing_by_model,
        "family_rates_by_model": family_rates_by_model,
        "asking_rates_by_digest": {
            digest: rate.published() for digest, rate in rates.rates.items()
        },
    }

    if mode == "specific_resource":
        rows = [
            {
                **base_fields,
                **shape_fields,
                "total_gpu_count": usage.total,
                "available_gpu_count": usage.available,
                "max_member_available_gpu_count": usage.available,
                "max_member_declared_gpu_count": usage.total,
                "single_resource_id": usage.resource_id,
                "member_count": 1,
                "feasible_shapes": _feasible_shapes([members_by_id[usage.resource_id]]),
            }
            for usage in usages
        ]
    else:
        total_gpu_count = sum(usage.total for usage in usages)
        from_buckets = _fungible_availability_from_buckets(pool_id, capacity_buckets)
        if from_buckets is not None:
            max_member_available, available_gpu_count = from_buckets
        else:
            # No usable capacity-bucket data for this pool right now (the
            # family has never loaded for this pool's site, or every
            # matching bucket entry is individually unreadable) -- fall back
            # to a max/sum over this pool's own resource-list entries rather
            # than silently publishing nothing.
            max_member_available = max((usage.available for usage in usages), default=0)
            available_gpu_count = sum(usage.available for usage in usages)
        rows = [
            {
                **base_fields,
                **shape_fields,
                "total_gpu_count": total_gpu_count,
                "available_gpu_count": available_gpu_count,
                "max_member_available_gpu_count": max_member_available,
                "max_member_declared_gpu_count": max(
                    (usage.total for usage in usages), default=0
                ),
                "single_resource_id": None,
                "member_count": len(usages),
                "feasible_shapes": _feasible_shapes(
                    [members_by_id[usage.resource_id] for usage in usages]
                ),
            }
        ]

    unserved = [shape for shape in shapes if shape.digest not in served]
    if resolution.stated:
        for shape in unserved:
            report.infeasible_shapes.setdefault(pool_id, []).append(
                {
                    "shape_digest": shape.digest,
                    "shape": {family: dict(fields) for family, fields in shape.shape.items()},
                    "not_feasible_against": not_feasible.get(shape.digest, "declared"),
                }
            )
    else:
        # A generated shape comes from a member's own declaration, so failing
        # against declared capacity can only be a categorical mismatch between
        # what the listing claims and what members declare. Failing only on
        # current availability is ordinary unavailability and is not reported.
        undeclared = [s for s in unserved if not_feasible.get(s.digest) == "declared"]
        if undeclared:
            report.undeclared_attributes[pool_id] = _undeclared_attribute(
                undeclared[0],
                region=region,
                members=[members_by_id[usage.resource_id] for usage in usages],
            )
    return rows


def _admissible_shapes(
    resolution: ShapeResolution, *, pool_id: str, report: _SiteDerivationReport
) -> tuple[ResolvedShape, ...]:
    """The base shapes of the listings a pool may publish, reporting the rest.

    A listing whose policy cannot be computed is reported with each problem's
    tier, paths, and any conflicting tiers' values or entries. A stated
    listing whose base shape its policy excludes is reported with its source
    tier and problems. A generated shape is nobody's statement and is never
    reported; the generator yields only what the default-only policy admits.
    """
    admitted: list[ResolvedShape] = []
    for listing in resolution.listings:
        shape = listing.shape
        if listing.policy is None:
            report.unusable_shape_constraints.setdefault(pool_id, []).extend(
                {
                    "tier": problem.tier,
                    "shape_digest": shape.digest,
                    "shape": _shape_dict(shape),
                    "paths": list(problem.paths),
                    "code": problem.code.value,
                    "problem": problem.message,
                    "bounds": [
                        {"tier": bound.tier, "bound": bound.bound, "value": bound.value}
                        for bound in problem.bounds
                    ],
                    "entries": list(problem.entries),
                }
                for problem in listing.policy_problems
            )
            continue
        problems = listing.policy.admissibility_problems(shape.shape)
        if problems:
            if resolution.stated:
                report.inadmissible_listing_shapes.setdefault(pool_id, []).append(
                    {
                        "tier": resolution.source,
                        "shape_digest": shape.digest,
                        "shape": _shape_dict(shape),
                        "problems": [_problem_dict(problem) for problem in problems],
                    }
                )
            continue
        admitted.append(shape)
    return tuple(admitted)


def _shape_dict(shape: ResolvedShape) -> dict[str, dict[str, Any]]:
    return {family: dict(fields) for family, fields in shape.shape.items()}


def _problem_dict(problem: AdmissibilityProblem) -> dict[str, Any]:
    return {
        "tier": problem.tier,
        "paths": list(problem.paths),
        "code": problem.code.value,
        "message": problem.message,
    }


def _shape_listing_resource(
    shape: ResolvedShape,
    *,
    pool_id: str,
    region: str | None,
    capacity_backing: str,
    resource_id: str | None = None,
) -> dict[str, Any]:
    """The listing fields a shape's claim is built from, as publication would
    publish them."""
    listing_resource: dict[str, Any] = {
        "pool_id": pool_id,
        "region": region,
        "offering_mode": "vm",
        "capacity_backing": capacity_backing,
        **dict(shape.attributes),
        **dict(shape.quantities),
    }
    if resource_id:
        listing_resource["resource_id"] = resource_id
    return listing_resource


def _undeclared_attribute(
    shape: ResolvedShape,
    *,
    region: str | None,
    members: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """Name the claimed attribute no enabled member declares with that value."""
    claimed = {"region": region, **dict(shape.attributes)}
    for attribute, value in claimed.items():
        if value is None:
            continue
        if not any((member.get("attributes") or {}).get(attribute) == value for member in members):
            return {"attribute": attribute, "value": value}
    return {"attribute": None, "value": None}


def _pool_rows_from_projection(
    conn: sqlite3.Connection,
    site_pool_projection: Mapping[str, list[dict[str, Any]]],
    *,
    member_availability: dict[tuple[str | None, str], int] | None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    hint_resolution: PoolHintResolutionSettings = _DEFAULT_POOL_HINT_RESOLUTION_SETTINGS,
    holds: set[tuple[str, str, str]],
    shape_feasible: ShapeFeasibility,
    declared_only: bool = False,
    overrides: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
    excluded: set[tuple[str, str, str]] | None = None,
    reports: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build pool_rows from a site_resource_pools projection.

    Structure (which pools/resources exist) comes from the projection, for
    every site present in it. Shapes and terms resolve through the
    storefront's site-scoped overrides (``_site_pool_overrides``, read from
    ``conn`` unless ``overrides`` is given), then each pool's projected hints
    and the storefront's configured defaults -- see `_projected_pool_rows`. A
    pool with no override still resolves through its hints and defaults.

    ``reports``, when given, receives each site's derivation report.

    ``site_capacity_buckets`` is the matching ``site_capacity_buckets``
    projection (same per-site-list shape as ``site_pool_projection``),
    used only for ``fungible``-mode pools' per-member availability ceiling
    -- see ``_projected_pool_rows``. Omitting it (``None``, the default)
    falls back to the pre-existing resource-list computation for every
    fungible pool, not an error.
    """
    # Buyer-side listing helpers import this module without installing the
    # resource-pool authority package; only storefront projection needs it.
    from market_resource_pools import read_site_declarations

    site_overrides = _site_pool_overrides(conn) if overrides is None else overrides
    pool_rows: list[dict[str, Any]] = []
    for site_id, pools in site_pool_projection.items():
        declarations = read_site_declarations(pools or [])
        report = _SiteDerivationReport(
            compatibility_rule=declarations.compatibility_rule,
            unresolvable_pools=dict(declarations.unresolvable),
        )
        for pool_id in declarations.unresolvable:
            holds.add(("pool", site_id, pool_id))
        # None (this site's capacity-bucket family has never loaded, or
        # site_capacity_buckets wasn't supplied at all) must survive
        # distinctly from a loaded, genuinely empty list -- collapsing
        # the two here would make an authoritative "zero buckets"
        # generation for this site indistinguishable from "unknown,"
        # letting every pool fall back to (possibly inconsistent,
        # separately-fetched) resource-list data instead of trusting the
        # bucket family's own answer. See `_fungible_availability_from_buckets`.
        buckets_for_site = (
            site_capacity_buckets.get(site_id)
            if site_capacity_buckets is not None
            else None
        )
        for pool in pools:
            pool_id = str(pool.get("pool_id") or "").strip()
            declaration = declarations.resolved.get(pool_id)
            if declaration is None:
                continue
            pool_rows.extend(
                _projected_pool_rows(
                    pool,
                    site_id=site_id,
                    member_availability=member_availability,
                    capacity_buckets=buckets_for_site,
                    declaration=declaration,
                    holds=holds,
                    report=report,
                    hint_resolution=hint_resolution,
                    shape_feasible=shape_feasible,
                    declared_only=declared_only,
                    override=site_overrides.get((site_id, pool_id)),
                    excluded=excluded,
                )
            )
        if reports is not None:
            reports[site_id] = report.as_dict()
    return pool_rows


def declared_shape_feasibility(
    db_path: str,
    site_pools: list[Mapping[str, Any]],
    *,
    site_id: str,
    pool_id: str,
    override: Mapping[str, Any],
    shape_feasible: ShapeFeasibility,
) -> dict[str, bool]:
    """Whether each of ``override``'s shapes is feasible on one pool's declarations.

    ``site_pools`` is a whole resource-pool projection of ``site_id``, because
    declarations are read site-wide. Judged by the derivation publication
    runs, on declared capacity alone, with ``override`` in place of whatever
    is stored for ``pool_id``, so an override write's report and the next
    publication cycle cannot disagree about feasibility. Keyed by shape
    digest. A pool that would publish nothing -- disabled, not advertisable
    for the ``vm`` mode, held, or with unresolvable declarations -- reports
    every shape infeasible. Records no derivation report.
    """
    if override.get("listing_shapes") is None:
        return {}
    resolution = resolve_vm_listing_shapes(
        {}, (), configured_default=None, override_shapes=override["listing_shapes"]
    )
    feasible: dict[str, bool] = {shape.digest: False for shape in resolution.shapes}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        rows = _pool_rows_from_projection(
            conn,
            {site_id: [dict(pool) for pool in site_pools]},
            member_availability=None,
            holds=set(),
            shape_feasible=shape_feasible,
            declared_only=True,
            overrides={(site_id, pool_id): override},
        )
    finally:
        conn.close()
    for row in rows:
        if row.get("pool_id") != pool_id:
            continue
        for shape in row.get("feasible_shapes") or ():
            if shape.digest in feasible:
                feasible[shape.digest] = True
    return feasible


def _parsed_escrows(raw: Any) -> list[dict[str, Any]] | None:
    """Accepted escrows stored as JSON text, or None when absent or unreadable."""
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, list) else None
    if isinstance(raw, list):
        return raw
    return None


def _parsed_settlements(raw: Any) -> list[dict[str, Any]] | None:
    """Settlement clauses as plain mappings, from JSON text or typed clauses."""
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, list) else None
    if isinstance(raw, (list, tuple)):
        return [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in raw
        ]
    return None


def available_compute_slices(
    db_path: str,
    *,
    site_pool_projection: Mapping[str, list[dict[str, Any]]],
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    hint_resolution: PoolHintResolutionSettings = _DEFAULT_POOL_HINT_RESOLUTION_SETTINGS,
    holds: set[tuple[str, str, str]] | None = None,
    declared_range: bool = False,
    shape_feasible: ShapeFeasibility,
    configured_sites: Collection[str] = (),
    excluded: set[tuple[str, str, str]] | None = None,
    reports: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return publishable compute listing slices from the site projections.

    ``site_pool_projection`` is the ``site_id -> resource-pool projection rows``
    mapping the storefront's per-site projection state holds, a site's last
    generation included while it is stale. It is the only source of listing
    structure: which pools and members exist comes from it for every site in
    it, and a configured site
    absent from it is held (below). Shapes and terms resolve through the
    storefront's site-scoped overrides, read through the pool-override kit, then
    each pool's projected hints, then the storefront's configured defaults --
    see ``_projected_pool_rows``. A pool with no override still publishes
    through its hints and defaults, with the same "priceless" handling other
    publish flows support if nothing resolves a real price.

    Consumption is the site authorities' answer: ``member_availability`` holds
    available units keyed by ``(site, resource_id)`` from the aggregated
    snapshots; a member the snapshots don't cover is not reservable and counts
    as 0. ``None`` means the caller has no consumption information (publish
    flows when the authority is unreachable) — members are then assumed fully
    available, which the reserve path corrects authoritatively.

    A pool's ``listing_cardinality_mode`` (from its projected ``policy_tags``)
    decides its row shape: ``fungible`` publishes one pool-keyed aggregated row;
    ``specific_resource`` publishes one resource-keyed row per enabled member,
    however many members the pool has. ``site_capacity_buckets`` is the
    matching ``site_capacity_buckets`` projection (same per-site-list shape as
    ``site_pool_projection``) and, when supplied, sources a ``fungible`` pool's
    per-member availability ceiling instead of a resource-list max -- see
    ``_projected_pool_rows``.

    Every slice is one listing shape: the storefront override's shapes, else
    the pool's stated ``listing_shapes`` for the ``vm`` mode, else the default
    GPU-only shapes generated from its members.
    A shape yields a slice only where ``shape_feasible`` judges some source
    member able to serve the claim its listing would produce: against declared
    capacity always, and for a capacity-backed pool against current
    availability too, so capacity changes move a backed pool's slices and only
    declaration changes move an unbacked pool's. ``declared_range`` judges every
    pool on declared capacity alone, which is what a listing's source still
    declares regardless of what is currently free. Each slice carries its
    pool's ``capacity_backing``, its canonical shape and digest, and exactly the
    quantities its shape declares.

    An empty mapping derives nothing. A site whose projection is not held is
    unknown, not empty, so it yields nothing and is held.

    ``holds`` collects ``("pool", site, pool_id)`` and
    ``("resource", site, resource_id)`` entries for sources whose declarations
    cannot be read, and a ``("site", site, "")`` entry for each of
    ``configured_sites`` the projection holds no value for. Their listings must
    be neither closed nor refreshed, so callers that reconcile keep them out of
    both.

    ``excluded`` collects ``(site, pool_id, shape_digest)`` for each listing
    whose policy cannot be computed or excludes its offer. Such a listing
    closes even when its pool is held, so callers that reconcile close it
    despite ``holds``.

    ``hint_resolution`` controls how much a pool's own projected
    ``region``/``sla`` hints are trusted relative to the storefront's override
    and configured defaults -- see `arkhai_vms_listings.pool_descriptors`.

    ``reports``, when given, receives each site's derivation report: what it
    could not publish, and why. Deriving records nothing else; a publication
    cycle turns the reports into its holds and reports
    (``site_derivation_entries``).
    """
    held = holds if holds is not None else set()
    for site_id in configured_sites:
        if site_id not in site_pool_projection:
            held.add(_site_hold(str(site_id)))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        pool_rows = _pool_rows_from_projection(
            conn,
            site_pool_projection,
            member_availability=member_availability,
            site_capacity_buckets=site_capacity_buckets,
            hint_resolution=hint_resolution,
            holds=held,
            shape_feasible=shape_feasible,
            declared_only=declared_range,
            excluded=excluded,
            reports=reports,
        )
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for row in pool_rows:
        if row.get("offering_mode") != "vm":
            continue
        site_id = str(row["site_id"])
        backing = row["capacity_backing"]
        pool_id = str(row["pool_id"])
        single_resource_id = row.get("single_resource_id")
        shapes = row.get("feasible_shapes") or ()
        pricing_by_model = row.get("pricing_by_model") or {}
        family_rates_by_model = row.get("family_rates_by_model") or {}
        for shape in shapes:
            pricing = pricing_by_model.get(shape.gpu_model)
            candidate = {
                "offering_mode": "vm",
                "capacity_backing": backing,
                "site_id": site_id,
                "pool_id": pool_id,
                "resource_id": single_resource_id,
                "resource_key": listing_shape_key(
                    site_id,
                    shape_digest=shape.digest,
                    pool_id=pool_id,
                    resource_id=single_resource_id,
                ),
                "listing_shape": {
                    family: dict(fields) for family, fields in shape.shape.items()
                },
                "shape_digest": shape.digest,
                "shape_source": row.get("shape_source", SHAPE_SOURCE_DEFAULT),
                **dict(shape.attributes),
                **dict(shape.quantities),
                "total_gpu_count": row.get("total_gpu_count"),
                "available_gpu_count": row.get("available_gpu_count"),
                "sla": row.get("sla", 0.0),
                "region": row.get("region"),
                "family_rates": {
                    family: [dict(entry) for entry in entries]
                    for family, entries in (
                        family_rates_by_model.get(shape.gpu_model) or {}
                    ).items()
                },
                "accepted_escrows": None,
                "settlements": None,
                "max_duration_seconds": (
                    pricing.max_duration_seconds if pricing else None
                ),
                "listing_cardinality_mode": row.get("listing_cardinality_mode"),
                "listing_cardinality_mode_explanation": row.get(
                    "listing_cardinality_mode_explanation"
                ),
                "listing_cardinality_mode_deprecated_key_notice": row.get(
                    "listing_cardinality_mode_deprecated_key_notice"
                ),
            }
            if pricing is not None:
                candidate["accepted_escrows"] = _parsed_escrows(pricing.accepted_escrows)
                candidate["settlements"] = _parsed_settlements(pricing.settlements)
            # Absent rather than null when nothing prices the shape, so a
            # listing whose rate is withdrawn refreshes to one without the field.
            asking_rate = (row.get("asking_rates_by_digest") or {}).get(shape.digest)
            if asking_rate is not None:
                candidate["asking_rate"] = dict(asking_rate)
            out.append(candidate)
    return out


def current_available_resource_keys(
    db_path: str,
    *,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]],
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    holds: set[tuple[str, str, str]] | None = None,
    shape_feasible: ShapeFeasibility,
    configured_sites: Collection[str] = (),
    admissibility_default: Declaration | None,
    excluded: set[tuple[str, str, str]] | None = None,
) -> set[str]:
    # Keys come from the full derivation, not a structural shortcut, because a
    # listing's key depends on its shape and its shape can come from the
    # storefront's override tier: a reader skipping that tier would derive
    # different keys than publication and close every listing it shaped.
    #
    # The commercial terms derivation also resolves are discarded here. That
    # cost is accepted: terms resolve once per pool and GPU model, not per
    # shape, so it is bounded by pool count rather than capacity. Terms never
    # affect a key, which is why none of the key readers take a
    # `hint_resolution` (see
    # `test_resource_keys_are_identical_regardless_of_hint_resolution`). The
    # configured admissibility default is required instead: it decides which
    # listings exist, so a reader without it would keep open a listing whose
    # offer publication no longer advertises.
    keys: set[str] = set()
    for row in available_compute_slices(
        db_path,
        member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
        hint_resolution=PoolHintResolutionSettings(admissibility_default=admissibility_default),
        holds=holds,
        shape_feasible=shape_feasible,
        configured_sites=configured_sites,
        excluded=excluded,
    ):
        if row.get("resource_key"):
            keys.add(str(row["resource_key"]))
    return keys




LISTING_SOURCE_KIND = "compute.listing_source"
LISTING_SOURCE_SCHEMA_VERSION = 2


def _source_envelope(raw: Any) -> Mapping[str, Any] | None:
    if isinstance(raw, Mapping):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, Mapping) else None
    return None


def _stored_shape_source(
    source_envelope: Any, site_id: str
) -> tuple[str, str, str] | None:
    """A stored listing's ``(site, pool_id, shape_digest)``, or ``None``.

    ``None`` for a listing bound before shapes, one naming no pool, or one
    whose envelope cannot be read.
    """
    envelope = _source_envelope(source_envelope)
    if (
        envelope is None
        or envelope.get("kind") != LISTING_SOURCE_KIND
        or envelope.get("schema_version") != LISTING_SOURCE_SCHEMA_VERSION
    ):
        return None
    payload = envelope.get("payload") or {}
    pool_id = payload.get("pool_id")
    if not pool_id:
        return None
    try:
        digest = resolve_shape(payload.get("listing_shape")).digest
    except ValueError:
        return None
    return (str(site_id), str(pool_id), digest)


def stored_listing_key(
    source_envelope: Any,
    listing_resource: Mapping[str, Any],
    site_id: str,
) -> str | None:
    """The structural key a stored VM listing occupies, or ``None``.

    Read from the listing's binding envelope, never rebuilt from its published
    fields, because flattening a shape is not required to be invertible. A
    listing bound before shapes (envelope version 1) keeps its GPU-count key.
    No derivation produces that key, so such a listing is never reopened and,
    while open, closes as stale.

    ``None`` when the listing names no source or its envelope cannot be read;
    such a listing is excluded from keyed reconciliation rather than guessed at.
    """
    envelope = _source_envelope(source_envelope)
    if envelope is None or envelope.get("kind") != LISTING_SOURCE_KIND:
        return None
    payload = envelope.get("payload") or {}
    pool_id = payload.get("pool_id")
    resource_id = payload.get("resource_id")
    if envelope.get("schema_version") == LISTING_SOURCE_SCHEMA_VERSION:
        try:
            digest = resolve_shape(payload.get("listing_shape")).digest
        except ValueError:
            return None
        if not pool_id and not resource_id:
            return None
        return listing_shape_key(
            str(site_id),
            shape_digest=digest,
            pool_id=str(pool_id) if pool_id else None,
            resource_id=str(resource_id) if resource_id else None,
        )
    if envelope.get("schema_version") == 1:
        gpu_count = positive_gpu_count(payload.get("gpu_count"))
        if gpu_count is None:
            gpu_count = positive_gpu_count(listing_resource.get("gpu_count"))
        if gpu_count is None:
            return None
        if pool_id and resource_id is None:
            return listing_pool_key(str(site_id), str(pool_id), gpu_count)
        if resource_id:
            return listing_resource_key(str(site_id), str(resource_id), gpu_count)
    return None


def _site_hold(site_id: str) -> tuple[str, str, str]:
    """The hold on every listing of a configured site whose projection is unknown."""
    return ("site", site_id, "")


def _is_held(
    listing_resource: Mapping[str, Any],
    site_id: str,
    holds: set[tuple[str, str, str]],
) -> bool:
    pool_id = listing_resource.get("pool_id")
    resource_id = listing_resource.get("resource_id")
    if _site_hold(str(site_id)) in holds:
        return True
    return ("pool", str(site_id), str(pool_id)) in holds or (
        resource_id is not None
        and ("resource", str(site_id), str(resource_id)) in holds
    )


class ReconciliationScope(enum.Enum):
    """Which reconciliation reads the bound listings.

    Source reconciliation (the publication loop) acts on every listing whose
    source changed. Availability reconciliation (capacity events, a release, a
    failed deal, an administrator's reservation) acts only on listings whose
    backing availability bounds, which the backing registry names.
    """

    SOURCE = "source"
    AVAILABILITY = "availability"


@dataclass(frozen=True, slots=True)
class BoundVmListing:
    """One bound VM listing as reconciliation reads it."""

    listing_id: str
    listing_resource: dict[str, Any]
    site_id: str
    backing: CapacityBacking
    source_envelope: Mapping[str, Any] | None = None

    @property
    def key(self) -> str | None:
        return stored_listing_key(self.source_envelope, self.listing_resource, self.site_id)


def _bound_vm_listings(
    db_path: str,
    *,
    open_listings: bool,
    scope: ReconciliationScope,
) -> list[BoundVmListing]:
    """Bound VM listings with their binding's site and backing.

    Closed listings exclude those their seller closed: no reconciliation path
    reopens a listing its seller withdrew. The availability scope reads only
    listings whose bound backing availability reconciliation may touch.
    """
    clauses = [
        "l.status = 'open'"
        if open_listings
        else "l.status != 'open' AND l.closed_by IS NOT 'seller'",
        "b.offering_mode = 'vm'",
    ]
    params: list[str] = []
    if scope is ReconciliationScope.AVAILABILITY:
        labels = sorted(labels_reconciled_by_availability())
        if not labels:
            return []
        clauses.append(f"b.capacity_backing IN ({', '.join('?' for _ in labels)})")
        params.extend(labels)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            f"""
            SELECT l.listing_id, l.listing_resource, b.site_id, b.capacity_backing,
                   b.source_envelope_json
            FROM listings l
            JOIN storefront_listing_bindings b ON b.listing_id = l.listing_id
            WHERE {' AND '.join(clauses)}
            """,
            params,
        ).fetchall()
    finally:
        conn.close()
    out: list[BoundVmListing] = []
    for listing_id, raw, site_id, capacity_backing_label, envelope in rows:
        if not raw or not site_id:
            continue
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            out.append(
                BoundVmListing(
                    str(listing_id),
                    parsed,
                    str(site_id),
                    capacity_backing(capacity_backing_label),
                    _source_envelope(envelope),
                )
            )
    return out


def open_listing_resource_keys(db_path: str) -> set[str]:
    """Return exact site-scoped keys covered by bound open VM listings."""

    covered: set[str] = set()
    for listing in _bound_vm_listings(
        db_path, open_listings=True, scope=ReconciliationScope.SOURCE
    ):
        key = listing.key
        if key is not None:
            covered.add(key)
    return covered


def stale_open_listing_ids(
    db_path: str,
    *,
    configured_sites: Collection[str],
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]],
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    scope: ReconciliationScope,
    shape_feasible: ShapeFeasibility,
    admissibility_default: Declaration | None,
) -> list[str]:
    """Return bound VM listings whose exact site-scoped slice is gone.

    A listing whose source cannot currently be read is held, not stale, and so
    is every listing of a configured site whose projection is unknown. A
    listing whose admissibility policy cannot be computed or excludes its offer
    is stale even when a later check holds the rest of its pool.
    ``scope`` has no default because the two reconciliations differ: source
    reconciliation closes any listing whose source is gone, while availability
    reconciliation acts only on listings availability bounds.
    ``admissibility_default`` is the storefront's configured default, which
    publication applies, so a listing whose offer it excludes is stale here too.
    """

    holds: set[tuple[str, str, str]] = set()
    excluded: set[tuple[str, str, str]] = set()
    available_keys = current_available_resource_keys(
        db_path,
        member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
        holds=holds,
        shape_feasible=shape_feasible,
        configured_sites=configured_sites,
        admissibility_default=admissibility_default,
        excluded=excluded,
    )
    stale: list[str] = []
    for listing in _bound_vm_listings(
        db_path, open_listings=True, scope=scope
    ):
        # Admissibility excluded the listing before a later rate check held
        # its pool, so it closes even though the rest of its pool is held.
        if (
            _is_held(listing.listing_resource, listing.site_id, holds)
            and _stored_shape_source(listing.source_envelope, listing.site_id)
            not in excluded
        ):
            continue
        key = listing.key
        if key is not None and key not in available_keys:
            stale.append(listing.listing_id)
    return stale


def closed_available_listing_ids(
    db_path: str,
    *,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]],
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    shape_feasible: ShapeFeasibility,
    configured_sites: Collection[str] = (),
    admissibility_default: Declaration | None,
) -> list[str]:
    """Return closed VM listings that availability may reopen now.

    This is availability reconciliation: its callers are capacity events, a
    released reservation, and a failed deal, so it reads only listings whose
    backing availability bounds. Any other listing is reopened by the
    publication loop, which refreshes its terms from its source as it does.

    A listing may reopen when its exact slice is available again, its seller did
    not close it, its source is not held, and its published identity and its
    binding's backing still match what its source derives. Every availability
    reopen shares this predicate, so a listing closed because its source changed
    is not reopened by a capacity event that happens to free its slice, nor
    one whose offer ``admissibility_default`` excludes.
    """
    holds: set[tuple[str, str, str]] = set()
    slices: dict[str, dict[str, Any]] = {}
    for row in available_compute_slices(
        db_path,
        member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
        hint_resolution=PoolHintResolutionSettings(admissibility_default=admissibility_default),
        holds=holds,
        shape_feasible=shape_feasible,
        configured_sites=configured_sites,
    ):
        if row.get("resource_key"):
            slices[str(row["resource_key"])] = row
    if not slices:
        return []
    available: list[tuple[int, str]] = []
    for listing in _bound_vm_listings(
        db_path, open_listings=False, scope=ReconciliationScope.AVAILABILITY
    ):
        listing_id = listing.listing_id
        listing_resource = listing.listing_resource
        site_id = listing.site_id
        if _is_held(listing_resource, site_id, holds):
            continue
        key = listing.key
        fresh = slices.get(key) if key is not None else None
        if fresh is None:
            continue
        comparison = compare_listing(
            stored_resource=listing_resource,
            stored_terms={},
            fresh_resource=slice_identity(fresh),
            fresh_terms={},
            binding_backing=listing.backing,
            source_backing=capacity_backing(fresh.get("capacity_backing")),
        )
        if comparison.outcome in REFUSE:
            logger.warning(
                "[PUBLICATION] not reopening listing %s: %s differs from its "
                "source at site %s",
                listing_id,
                list(comparison.differing_fields),
                site_id,
            )
            continue
        # Smallest first, then by id, so the order is deterministic; a listing
        # stating no GPUs orders as zero.
        available.append((int(listing_resource.get("gpu_count") or 0), listing_id))
    return [listing_id for _, listing_id in sorted(available)]


def slice_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    """The identity fields a slice would publish, as the stored listing names them.

    Every dimension the slice's shape declares is identity; a dimension it does
    not declare is not published and so is absent here.
    """
    identity = {
        "offering_mode": row.get("offering_mode"),
        "pool_id": row.get("pool_id"),
        "gpu_model": row.get("gpu_model"),
        "region": row.get("region"),
    }
    for dimension in DIMENSION_KEYS:
        if row.get(dimension) is not None:
            identity[dimension] = row[dimension]
    if row.get("resource_id"):
        identity["resource_id"] = row["resource_id"]
    return identity
