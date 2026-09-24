from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Mapping, Protocol

from arkhai_vms import DIMENSION_KEYS, length_prefixed

from domains.vms.listings.listing_comparison import REFUSE, compare_listing
from domains.vms.listings.listing_shapes import (
    SHAPE_SOURCE_DEFAULT,
    ResolvedShape,
    resolve_shape,
    resolve_vm_listing_shapes,
)
from domains.vms.listings.listing_cardinality_mode import (
    resolve_vm_listing_cardinality_mode,
)
from domains.vms.listings.pool_descriptors import resolve_region, resolve_sla
from domains.vms.listings.pricing_resolution import (
    GpuPricingFields,
    resolve_gpu_pricing,
)


if TYPE_CHECKING:
    from market_resource_pools import ResolvedPool

logger = logging.getLogger(__name__)

HELD_ALLOCATION_STATES = {
    "reserved",
    "provisioning",
    "leased",
    "releasing",
    "held",
}


def positive_gpu_count(value: Any) -> int | None:
    """A usable enumeration quantity, or ``None``.

    Exactly a positive integer. Nothing here substitutes a count: a listing is
    "N GPUs of this resource", and a missing, zero, or malformed N is not a
    1-GPU slice that happens to be unlabelled.
    """
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _required_gpu_count(gpu_count: Any) -> int:
    count = positive_gpu_count(gpu_count)
    if count is None:
        raise ValueError(f"gpu_count must be a positive integer, not {gpu_count!r}")
    return count


def listing_resource_key(
    site_id: str,
    resource_id: str,
    gpu_count: int,
) -> str:
    if not site_id or not site_id.strip():
        raise ValueError("site_id must be non-empty")
    return (
        f"{length_prefixed(site_id)}:{length_prefixed(resource_id)}"
        f":gpus:{_required_gpu_count(gpu_count)}"
    )


def listing_pool_key(
    site_id: str,
    pool_id: str,
    gpu_count: int,
) -> str:
    if not site_id or not site_id.strip():
        raise ValueError("site_id must be non-empty")
    return (
        f"pool:{length_prefixed(site_id)}:{length_prefixed(pool_id)}"
        f":gpus:{_required_gpu_count(gpu_count)}"
    )


def listing_shape_key(
    site_id: str,
    *,
    shape_digest: str,
    pool_id: str | None = None,
    resource_id: str | None = None,
) -> str:
    """The structural key of one listing shape from a pool or a specific resource.

    A resource names a specific-resource listing and takes precedence over its
    pool, as it does in the capacity claim. The shape enters by digest, so which
    source produced the shape never changes the key.
    """
    if not site_id or not site_id.strip():
        raise ValueError("site_id must be non-empty")
    if not shape_digest:
        raise ValueError("shape_digest must be non-empty")
    if resource_id:
        return f"{length_prefixed(site_id)}:{length_prefixed(resource_id)}:shape:{shape_digest}"
    if pool_id:
        return f"pool:{length_prefixed(site_id)}:{length_prefixed(pool_id)}:shape:{shape_digest}"
    raise ValueError("a listing shape key needs a pool or a resource")


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


def allocation_table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_allocations'"
    ).fetchone()
    return row is not None


def held_gpu_counts(conn: sqlite3.Connection) -> dict[str, int]:
    if not allocation_table_exists(conn):
        return {}
    placeholders = ", ".join("?" for _ in HELD_ALLOCATION_STATES)
    rows = conn.execute(
        f"""
        SELECT resource_id, COALESCE(SUM(gpu_count), 0)
        FROM compute_allocations
        WHERE state IN ({placeholders})
        GROUP BY resource_id
        """,
        tuple(sorted(HELD_ALLOCATION_STATES)),
    ).fetchall()
    return {str(resource_id): int(total or 0) for resource_id, total in rows}


def held_gpu_counts_by_resource(conn: sqlite3.Connection) -> dict[str, int]:
    return held_gpu_counts(conn)


def _member_available_units(
    member_total: int,
    member_key: tuple[str | None, str],
    member_availability: dict[tuple[str | None, str], int] | None,
) -> int:
    """Units of one pool member actually available, capped by both its
    own total and (when known) the aggregated site snapshot's answer for
    that ``(site, resource_id)`` key. ``None`` availability means the
    caller has no consumption information -- treated as fully available,
    corrected authoritatively by the reserve path later. Shared by every
    capacity source (local capacity-pools, legacy resources, and the
    projection's own fallback) so there is exactly one place this cap is
    computed.
    """
    if member_availability is None:
        return member_total
    return max(0, min(member_total, int(member_availability.get(member_key, 0))))


def _capacity_pool_member_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Query compute_capacity_pools JOIN compute_pool_members for active,
    fungible-capable GPU pools -- one row per member, pool columns
    repeated across each of its members' rows."""
    member_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(compute_pool_members)")
    }
    pool_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(compute_capacity_pools)")
    }
    site_select = "m.site" if "site" in member_cols else "NULL AS site"
    settlements_select = (
        "p.settlements" if "settlements" in pool_cols else "NULL AS settlements"
    )
    return conn.execute(
        f"""
        SELECT p.pool_id, p.gpu_model, p.region, p.sla,
               p.total_gpu_count, p.min_price, p.token,
               p.accepted_escrows, {settlements_select}, p.max_duration_seconds,
               m.resource_id, m.gpu_count, m.status, m.attributes,
               {site_select}
        FROM compute_capacity_pools p
        JOIN compute_pool_members m ON m.pool_id = p.pool_id
        WHERE p.resource_type = 'compute.gpu'
          AND p.status = 'active'
          AND m.status = 'active'
        ORDER BY p.pool_id, m.resource_id
        """
    ).fetchall()


def _accumulate_capacity_pool_member(
    pool: dict[str, Any],
    row: sqlite3.Row,
    member_availability: dict[tuple[str | None, str], int] | None,
    *,
    home_site: str,
) -> None:
    """Fold one compute_pool_members row into its pool's running
    aggregate, in place."""
    member_total = int(row["gpu_count"] or 0)
    member_site = str(row["site"]) if row["site"] else home_site
    member_key = (member_site, str(row["resource_id"]))
    member_available = _member_available_units(
        member_total, member_key, member_availability
    )
    pool["total_gpu_count"] += member_total
    pool["available_gpu_count"] += member_available
    pool["max_member_available_gpu_count"] = max(
        int(pool["max_member_available_gpu_count"]),
        member_available,
    )
    pool["member_count"] += 1
    pool["single_resource_id"] = (
        str(row["resource_id"]) if pool["member_count"] == 1 else None
    )


def _pool_rows_from_capacity_pools(
    conn: sqlite3.Connection,
    member_availability: dict[tuple[str | None, str], int] | None,
    *,
    home_site: str,
) -> list[dict[str, Any]]:
    """compute_capacity_pools JOIN compute_pool_members, grouped by pool
    -- the fungible-pool-capable local source, preferred over the legacy
    resources table whenever both tables exist."""
    by_pool: dict[str, dict[str, Any]] = {}
    for row in _capacity_pool_member_rows(conn):
        pool_id = str(row["pool_id"])
        pool = by_pool.setdefault(
            pool_id,
            {
                "pool_id": pool_id,
                "gpu_model": row["gpu_model"],
                "region": row["region"],
                "sla": row["sla"] if row["sla"] is not None else 0.0,
                "total_gpu_count": 0,
                "available_gpu_count": 0,
                "max_member_available_gpu_count": 0,
                "min_price": row["min_price"],
                "token": row["token"],
                "accepted_escrows": row["accepted_escrows"],
                "settlements": row["settlements"],
                "max_duration_seconds": row["max_duration_seconds"],
                "single_resource_id": None,
                "member_count": 0,
                "offering_mode": "vm",
            },
        )
        _accumulate_capacity_pool_member(
            pool, row, member_availability, home_site=home_site
        )
    return list(by_pool.values())


def _legacy_resource_columns(conn: sqlite3.Connection) -> tuple[bool, bool, bool]:
    """Report optional publication columns present on legacy resources."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(resources)").fetchall()}
    return (
        "accepted_escrows" in cols,
        "max_duration_seconds" in cols,
        "settlements" in cols,
    )


def _project_legacy_resource_row(
    row: sqlite3.Row,
    *,
    has_accepted: bool,
    has_max_duration: bool,
    has_settlements: bool = False,
    member_availability: dict[tuple[str | None, str], int] | None,
    home_site: str,
) -> dict[str, Any]:
    """Shape one legacy `resources` row into a pool_rows entry -- each
    such resource is its own single-member "pool" (no fungible grouping
    exists at this schema generation)."""
    try:
        attrs = json.loads(row["attributes"] or "{}")
    except json.JSONDecodeError:
        attrs = {}
    total_gpu_count = int(row["value"]) if row["value"] is not None else 1
    available_gpu_count = _member_available_units(
        total_gpu_count,
        (home_site, str(row["resource_id"])),
        member_availability,
    )
    return {
        "pool_id": str(attrs.get("pool_id") or row["resource_id"]),
        "single_resource_id": str(row["resource_id"]),
        "gpu_model": attrs.get("gpu_model"),
        "region": attrs.get("region"),
        "sla": attrs.get("sla", 0.0),
        "total_gpu_count": total_gpu_count,
        "available_gpu_count": available_gpu_count,
        "max_member_available_gpu_count": available_gpu_count,
        "min_price": row["min_price"],
        "token": row["token"],
        "accepted_escrows": row["accepted_escrows"] if has_accepted else None,
        "settlements": row["settlements"] if has_settlements else None,
        "max_duration_seconds": (
            row["max_duration_seconds"] if has_max_duration else None
        ),
        "offering_mode": "vm",
    }


def _pool_rows_from_legacy_resources(
    conn: sqlite3.Connection,
    member_availability: dict[tuple[str | None, str], int] | None,
    *,
    home_site: str,
) -> list[dict[str, Any]]:
    """Legacy `resources` table fallback, used only when
    compute_capacity_pools/compute_pool_members don't both exist."""
    has_accepted, has_max_duration, has_settlements = _legacy_resource_columns(conn)
    select_extra = ""
    if has_accepted:
        select_extra += ", accepted_escrows"
    if has_max_duration:
        select_extra += ", max_duration_seconds"
    if has_settlements:
        select_extra += ", settlements"
    rows = conn.execute(
        f"""SELECT resource_id, resource_subtype, unit, value, state, attributes,
                  min_price, token{select_extra}
           FROM resources
           WHERE resource_type = 'compute.gpu' AND state = 'available'
           ORDER BY resource_id""",
    ).fetchall()
    return [
        _project_legacy_resource_row(
            row,
            has_accepted=has_accepted,
            has_max_duration=has_max_duration,
            has_settlements=has_settlements,
            member_availability=member_availability,
            home_site=home_site,
        )
        for row in rows
    ]


def _pool_rows_from_local_tables(
    conn: sqlite3.Connection,
    member_availability: dict[tuple[str | None, str], int] | None,
    *,
    home_site: str,
) -> list[dict[str, Any]]:
    """Local-table sourcing: compute_capacity_pools joined with
    compute_pool_members when both exist, else the legacy resources
    table. One of the two capacity sources `available_compute_slices`
    can choose between, alongside `_pool_rows_from_projection`.
    """
    has_pools = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_capacity_pools'"
        ).fetchone()
        is not None
    )
    has_members = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_pool_members'"
        ).fetchone()
        is not None
    )
    if has_pools and has_members:
        return _pool_rows_from_capacity_pools(
            conn, member_availability, home_site=home_site
        )
    return _pool_rows_from_legacy_resources(
        conn, member_availability, home_site=home_site
    )


def _local_pool_pricing(conn: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Home site's own pool pricing/descriptive-fallback config, by pool_id.

    Never looked up for another site's pool -- compute_capacity_pools is
    not site-scoped (``pool_id TEXT PRIMARY KEY``), so a lookup keyed only
    on pool_id would risk the same kind of cross-site collision
    ``derived_compute_listings``' site-scoped derivation keys guard
    against, if it were ever consulted for a pool that isn't home_site's
    own. Scoping every call site to home_site only is what keeps that
    safe without needing to touch this table's schema -- deliberate:
    this table holds pricing and descriptive fallback data the
    projection itself doesn't carry, is intentionally not being made
    multi-site-aware, and a non-home_site pool simply has no pricing
    source through this table at all.
    """
    has_pools = (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_capacity_pools'"
        ).fetchone()
        is not None
    )
    if not has_pools:
        return {}
    pool_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(compute_capacity_pools)")
    }
    settlements_select = (
        "settlements" if "settlements" in pool_cols else "NULL AS settlements"
    )
    return {
        str(row["pool_id"]): row
        for row in conn.execute(
            f"""
            SELECT pool_id, gpu_model, region, sla, min_price, token,
                   accepted_escrows, {settlements_select}, max_duration_seconds
            FROM compute_capacity_pools
            WHERE resource_type = 'compute.gpu' AND status = 'active'
            """
        ).fetchall()
    }


@dataclass(frozen=True)
class _ProjectedResourceUsage:
    resource_id: str
    gpu_model: str | None
    total: int
    available: int


# Why a member yields no usage. Each is handled differently: an absent count is
# reported to the operator, a declared zero is silent, and a malformed count
# makes the member unresolvable, because an unreadable count is not a zero.
_GPU_COUNT_ABSENT = "absent"
_GPU_COUNT_ZERO = "zero"
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
    """Derive one projected resource's identity, GPU model, and usage.

    Returns ``None`` if it has no physical_resource_id to key on, or one of the
    ``_GPU_COUNT_*`` outcomes when its declared GPU count cannot be enumerated.
    Pure and independently testable: no dict mutation, no accumulation, just
    this one resource's own facts.
    """
    resource_id = str(resource.get("physical_resource_id") or "")
    if not resource_id:
        return None
    resource_type = resource.get("resource_type")
    if not isinstance(resource_type, str) or not resource_type.strip():
        return _RESOURCE_TYPE_ABSENT
    attrs = resource.get("attributes") or {}
    gpu_model = attrs.get("gpu_model") or None
    capacity = resource.get("capacity") or {}
    if "gpu_count" not in capacity or capacity.get("gpu_count") is None:
        return _GPU_COUNT_ABSENT
    raw_total = capacity["gpu_count"]
    if isinstance(raw_total, bool) or not isinstance(raw_total, int) or raw_total < 0:
        return _GPU_COUNT_MALFORMED
    if raw_total == 0:
        return _GPU_COUNT_ZERO
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
    return _ProjectedResourceUsage(resource_id, gpu_model, total, available)


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
) -> tuple[int, int, str | None] | None:
    """(max_member_available, available_gpu_count, gpu_model) from this
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
    gpu_model: str | None = None
    saw_matching_entry = False
    saw_usable_entry = False
    for bucket in capacity_buckets:
        if str(bucket.get("resource_pool_id") or "") != pool_id:
            continue
        saw_matching_entry = True
        bucket_available = _bucket_gpu_count(bucket)
        if bucket_available is None:
            continue
        saw_usable_entry = True
        bucket_count = int(bucket.get("resource_count") or 0)
        available_gpu_count += bucket_available * bucket_count
        if bucket_available > max_member_available:
            max_member_available = bucket_available
            gpu_model = (bucket.get("grouping_attributes") or {}).get("gpu_model")
    if saw_usable_entry:
        return max_member_available, available_gpu_count, gpu_model
    if saw_matching_entry:
        # Every matching entry was individually unreadable -- not a
        # confirmed absence, fall back.
        return None
    # No matching entry at all in a loaded family: authoritative zero,
    # not missing data -- see this function's own docstring.
    return 0, 0, None


@dataclass
class _SiteDerivationReport:
    """What one site's latest derivation could not publish, and why.

    Surfaced in the storefront's system status so an operator sees why a pool
    publishes nothing or why its listings are held.
    """

    compatibility_rule: bool = False
    unresolvable_pools: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unresolvable_members: dict[str, str] = field(default_factory=dict)
    members_without_gpu_count: dict[str, str] = field(default_factory=dict)
    members_without_resource_type: dict[str, str] = field(default_factory=dict)
    unreadable_shapes: dict[str, list[str]] = field(default_factory=dict)
    infeasible_shapes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    undeclared_attributes: dict[str, dict[str, Any]] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "compatibility_rule": self.compatibility_rule,
            "unresolvable_pools": {
                pool_id: list(codes)
                for pool_id, codes in sorted(self.unresolvable_pools.items())
            },
            "unresolvable_members": dict(sorted(self.unresolvable_members.items())),
            "members_without_gpu_count": dict(
                sorted(self.members_without_gpu_count.items())
            ),
            "members_without_resource_type": dict(
                sorted(self.members_without_resource_type.items())
            ),
            "unreadable_shapes": dict(sorted(self.unreadable_shapes.items())),
            "infeasible_shapes": dict(sorted(self.infeasible_shapes.items())),
            "undeclared_attributes": dict(sorted(self.undeclared_attributes.items())),
        }


_LATEST_DERIVATION_REPORTS: dict[str, dict[str, Any]] = {}


def derivation_reports() -> dict[str, dict[str, Any]]:
    """Per-site report from the latest projection-path derivation."""
    return {site: dict(report) for site, report in _LATEST_DERIVATION_REPORTS.items()}


def _record_site_report(site_id: str, report: _SiteDerivationReport) -> None:
    # Logged when a site's report changes rather than on every reconcile, so a
    # standing condition is visible once per projection generation instead of
    # on every poll.
    current = report.as_dict()
    if _LATEST_DERIVATION_REPORTS.get(site_id) == current:
        return
    _LATEST_DERIVATION_REPORTS[site_id] = current
    if current["compatibility_rule"]:
        logger.warning(
            "[PUBLICATION] site %s projects no advertisement or backing "
            "declarations; every pool reads as capacity-backed with delivery "
            "authorizing advertisement",
            site_id,
        )
    for pool_id, codes in current["unresolvable_pools"].items():
        logger.warning(
            "[PUBLICATION] site %s pool %s is unresolvable (%s); its listings "
            "are held",
            site_id,
            pool_id,
            ", ".join(codes),
        )
    for resource_id, pool_id in current["unresolvable_members"].items():
        logger.warning(
            "[PUBLICATION] site %s pool %s member %s declares a malformed "
            "gpu_count; its listings are held",
            site_id,
            pool_id,
            resource_id,
        )
    for resource_id, pool_id in current["members_without_gpu_count"].items():
        logger.warning(
            "[PUBLICATION] site %s pool %s member %s declares no gpu_count; "
            "no VM listing is derived from it",
            site_id,
            pool_id,
            resource_id,
        )
    for resource_id, pool_id in current["members_without_resource_type"].items():
        logger.warning(
            "[PUBLICATION] site %s pool %s member %s projects no resource_type; "
            "its listings are held",
            site_id,
            pool_id,
            resource_id,
        )
    for pool_id, problems in current["unreadable_shapes"].items():
        logger.warning(
            "[PUBLICATION] site %s pool %s states listing shapes the VM "
            "vocabulary cannot read (%s); its listings are held",
            site_id,
            pool_id,
            "; ".join(problems),
        )
    for pool_id, shapes in current["infeasible_shapes"].items():
        logger.warning(
            "[PUBLICATION] site %s pool %s states %d shape(s) no member is "
            "feasible for; they publish nothing",
            site_id,
            pool_id,
            len(shapes),
        )
    for pool_id, finding in current["undeclared_attributes"].items():
        logger.warning(
            "[PUBLICATION] site %s pool %s publishes nothing: its listings claim "
            "%s %r and no enabled member declares it",
            site_id,
            pool_id,
            finding.get("attribute"),
            finding.get("value"),
        )


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

    `gpu_pricing_defaults_by_model`/`gpu_pricing_flat_default` are tier 1
    of the pricing precedence chain (see
    `domains.vms.listings.pricing_resolution`) -- no trust decision
    involved, since config defaults are the storefront operator's own
    values, not a site's; defaulted here only so every caller doesn't
    need to construct empty ones.
    """

    accept_pool_declared_sla: bool = False
    default_sla: float = 0.0
    gpu_pricing_defaults_by_model: Mapping[str, Any] = None  # type: ignore[assignment]
    gpu_pricing_flat_default: Any = None

    def __post_init__(self) -> None:
        # dataclass(frozen=True) needs object.__setattr__ to fill in
        # mutable-default-free placeholders after construction, since a
        # bare `{}`/instance can't be a dataclass field default.
        if self.gpu_pricing_defaults_by_model is None:
            object.__setattr__(self, "gpu_pricing_defaults_by_model", {})
        if self.gpu_pricing_flat_default is None:
            object.__setattr__(self, "gpu_pricing_flat_default", GpuPricingFields())


_DEFAULT_POOL_HINT_RESOLUTION_SETTINGS = PoolHintResolutionSettings()


def _projected_pool_rows(
    pool: Mapping[str, Any],
    *,
    site_id: str,
    home_site: str,
    local_pricing: Mapping[str, sqlite3.Row],
    member_availability: dict[tuple[str | None, str], int] | None,
    capacity_buckets: list[Mapping[str, Any]] | None,
    declaration: "ResolvedPool",
    holds: set[tuple[str, str, str]],
    report: _SiteDerivationReport,
    shape_feasible: ShapeFeasibility,
    hint_resolution: PoolHintResolutionSettings = _DEFAULT_POOL_HINT_RESOLUTION_SETTINGS,
    declared_only: bool = False,
) -> list[dict[str, Any]]:
    """Build zero or more pool_rows entries from one projected pool.

    Returns an empty list only if the pool has no `pool_id`. A missing
    local `compute_capacity_pools` row (whether because this is a
    non-home-site pool -- never locally priced by design, see
    `_local_pool_pricing` -- or a home-site pool the storefront simply
    hasn't registered) means no storefront-override tier is available,
    not that the pool can't publish: region/SLA/pricing still resolve
    through their pool-hint and config-default tiers. Whether the
    resulting row ends up genuinely priceless is left to the same
    downstream `publish_priceless` handling every other unpriced
    candidate already goes through, not decided here. Otherwise returns
    exactly one row for a ``fungible`` pool (matching this function's
    original, aggregated shape), or one row per enabled member for a
    ``specific_resource`` pool -- a pool's ``listing_cardinality_mode``
    (from its projected `policy_tags`, domain-resolved by
    `resolve_vm_listing_cardinality_mode`) decides which shape applies. An
    explicit tag always wins; its *absence* falls back to exactly the
    structural heuristic this function used before the tag existed
    (`member_count == 1` -> specific_resource) so an untagged pool's publication shape does not
    change out from under an existing derived-listing mapping.
    """
    pool_id = str(pool.get("resource_pool_id") or "").strip()
    if not pool_id:
        return []
    # A listing may advertise only a mode its pool declares advertisable,
    # backed or not; delivery is rechecked separately by every execution layer.
    # A pool its site declares disabled is a withdrawn source.
    if not declaration.advertises("vm") or not declaration.enabled:
        return []
    # `pricing` (this pool's row in the storefront's own local
    # `compute_capacity_pools` table) is the tier-3 storefront-override
    # source, not a prerequisite for publishing at all -- a pool with a
    # complete pool-declared hint (tier 2) or config default (tier 1) and
    # no local row must still resolve and publish, or the three-tier
    # precedence this section exists to build is unreachable for exactly
    # the pools it was meant to help (any pool the storefront hasn't
    # locally registered, and every non-home-site pool, since
    # `compute_capacity_pools` is intentionally never consulted for a
    # site other than home_site -- see `_local_pool_pricing`'s own
    # cross-site-collision rationale, unaffected by this change: that
    # table still isn't read for a non-home-site pool, it's just no
    # longer required to exist for a home-site one either).
    pricing = local_pricing.get(pool_id) if site_id == home_site else None
    local_region = pricing["region"] if pricing is not None else None
    local_sla = pricing["sla"] if pricing is not None else None
    local_gpu_model = pricing["gpu_model"] if pricing is not None else None

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
        if usage == _GPU_COUNT_ABSENT:
            report.members_without_gpu_count[resource_id] = pool_id
        elif usage == _GPU_COUNT_MALFORMED:
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

    # A stated list the VM vocabulary cannot read holds the pool's listings and
    # never falls back to generated shapes.
    resolution = resolve_vm_listing_shapes(
        policy_tags, [members_by_id[usage.resource_id] for usage in usages]
    )
    if resolution.unreadable:
        report.unreadable_shapes[pool_id] = list(resolution.problems)
        holds.add(("pool", site_id, pool_id))
        return []

    region = resolve_region(policy_tags, fallback=local_region)
    sla = resolve_sla(
        policy_tags,
        accept_pool_declared_sla=hint_resolution.accept_pool_declared_sla,
        storefront_override=local_sla,
        config_default=hint_resolution.default_sla,
    )
    storefront_pricing_override = GpuPricingFields(
        min_price=pricing["min_price"] if pricing is not None else None,
        token=pricing["token"] if pricing is not None else None,
        max_duration_seconds=(
            pricing["max_duration_seconds"] if pricing is not None else None
        ),
        accepted_escrows=pricing["accepted_escrows"] if pricing is not None else None,
        settlements=(
            pricing["settlements"]
            if pricing is not None and "settlements" in pricing.keys()
            else None
        ),
    )

    def _resolved_pricing(gpu_model_for_pricing: str | None) -> GpuPricingFields:
        # Pricing is resolved per GPU model, not once per pool -- the
        # three-tier chain's middle and bottom tiers are both keyed by
        # model, so this can't be folded into base_fields the way
        # region/sla can (region/sla have no per-model dimension).
        return resolve_gpu_pricing(
            policy_tags,
            gpu_model=gpu_model_for_pricing,
            storefront_override=storefront_pricing_override,
            config_defaults_by_model=hint_resolution.gpu_pricing_defaults_by_model,
            flat_default=hint_resolution.gpu_pricing_flat_default,
        )

    base_fields = {
        "site_id": site_id,
        "pool_id": pool_id,
        "region": region,
        "sla": sla,
        "listing_cardinality_mode": mode,
        "offering_mode": "vm",
        "capacity_backing": declaration.capacity_backing,
        "listing_cardinality_mode_explanation": cardinality.fallback_explanation,
        "listing_cardinality_mode_deprecated_key_notice": (
            cardinality.deprecated_key_notice
        ),
    }

    backed = declaration.capacity_backing == "backed" and not declared_only
    pool_buckets = (
        None
        if capacity_buckets is None
        else [
            bucket
            for bucket in capacity_buckets
            if str(bucket.get("resource_pool_id") or "") == pool_id
        ]
    )

    def _judge_members(shape: ResolvedShape, members: list[Mapping[str, Any]]) -> str | None:
        """None when feasible, else what the shape is not feasible against."""
        listing_resource = _shape_listing_resource(
            shape, pool_id=pool_id, region=region, capacity_backing=declaration.capacity_backing,
            resource_id=(
                str(members[0].get("physical_resource_id"))
                if mode == "specific_resource" and members
                else None
            ),
        )
        if not any(
            shape_feasible.member_feasible(
                listing_resource, pool_id=pool_id, member=member, use_available=False
            )
            for member in members
        ):
            return "declared"
        if not backed:
            return None
        readable_buckets = (
            [bucket for bucket in pool_buckets if bucket.get("available")]
            if pool_buckets is not None
            else None
        )
        if mode != "specific_resource" and pool_buckets is not None and (
            readable_buckets or not pool_buckets
        ):
            # A loaded bucket family is authoritative for fungible availability,
            # and a loaded family naming no entry for the pool means none is
            # available. Entries that predate per-resource availability are
            # unreadable, and only when every entry is does the pool fall back
            # to its members.
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

    pricing_by_model = {
        model: _resolved_pricing(model)
        for model in sorted({shape.gpu_model for shape in resolution.shapes})
    }
    served: set[str] = set()
    not_feasible: dict[str, str] = {}

    def _feasible_shapes(members: list[Mapping[str, Any]]) -> tuple[ResolvedShape, ...]:
        feasible: list[ResolvedShape] = []
        for shape in resolution.shapes:
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
        "listing_shapes": resolution.shapes,
        "shape_source": resolution.source,
        "pricing_by_model": pricing_by_model,
    }

    if mode == "specific_resource":
        rows = []
        for usage in usages:
            resolved_gpu_model = usage.gpu_model or local_gpu_model
            resolved_pricing = _resolved_pricing(resolved_gpu_model)
            rows.append(
                {
                    **base_fields,
                    **shape_fields,
                    "gpu_model": resolved_gpu_model,
                    "min_price": resolved_pricing.min_price,
                    "token": resolved_pricing.token,
                    "accepted_escrows": resolved_pricing.accepted_escrows,
                    "settlements": resolved_pricing.settlements,
                    "max_duration_seconds": resolved_pricing.max_duration_seconds,
                    "total_gpu_count": usage.total,
                    "available_gpu_count": usage.available,
                    "max_member_available_gpu_count": usage.available,
                    "max_member_declared_gpu_count": usage.total,
                    "single_resource_id": usage.resource_id,
                    "member_count": 1,
                    "feasible_shapes": _feasible_shapes([members_by_id[usage.resource_id]]),
                }
            )
    else:
        total_gpu_count = sum(usage.total for usage in usages)
        resource_gpu_model = next((u.gpu_model for u in usages if u.gpu_model), None)
        from_buckets = _fungible_availability_from_buckets(pool_id, capacity_buckets)
        if from_buckets is not None:
            max_member_available, available_gpu_count, bucket_gpu_model = from_buckets
            gpu_model = bucket_gpu_model or resource_gpu_model
        else:
            # No usable capacity-bucket data for this pool right now (the
            # family has never loaded for this pool's site, or every
            # matching bucket entry is individually unreadable) -- fall back
            # to a max/sum over this pool's own resource-list entries rather
            # than silently publishing nothing.
            max_member_available = max((usage.available for usage in usages), default=0)
            available_gpu_count = sum(usage.available for usage in usages)
            gpu_model = resource_gpu_model

        resolved_gpu_model = gpu_model or local_gpu_model
        resolved_pricing = _resolved_pricing(resolved_gpu_model)
        rows = [
            {
                **base_fields,
                **shape_fields,
                "gpu_model": resolved_gpu_model,
                "min_price": resolved_pricing.min_price,
                "token": resolved_pricing.token,
                "accepted_escrows": resolved_pricing.accepted_escrows,
                "settlements": resolved_pricing.settlements,
                "max_duration_seconds": resolved_pricing.max_duration_seconds,
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

    unserved = [shape for shape in resolution.shapes if shape.digest not in served]
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
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    hint_resolution: PoolHintResolutionSettings = _DEFAULT_POOL_HINT_RESOLUTION_SETTINGS,
    holds: set[tuple[str, str, str]],
    shape_feasible: ShapeFeasibility,
    declared_only: bool = False,
) -> list[dict[str, Any]]:
    """Build pool_rows from a site_resource_pools projection.

    Structure (which pools/resources exist, GPU model) comes from the
    projection, for every site present in it. Region can come from the
    projection's own `pool_metadata.policy_tags` hint; pricing and SLA's
    storefront-override tier still come from the local
    `compute_capacity_pools` table -- see `_local_pool_pricing` and
    `domains.vms.listings.pool_descriptors`. That local table is only
    ever consulted for home_site's own pools; a non-home_site pool, or a
    home_site pool with no local row, simply has no storefront-override
    tier -- region/SLA/pricing still resolve through the pool's own
    projected hint and the storefront's configured default, the same
    "priceless" fallback other publish flows already support if nothing
    resolves a real price. A missing local row is not, by itself, a
    reason to skip the pool.

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

    local_pricing = _local_pool_pricing(conn)
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
            declaration = declarations.resolved.get(
                str(pool.get("resource_pool_id") or "").strip()
            )
            if declaration is None:
                continue
            pool_rows.extend(
                _projected_pool_rows(
                    pool,
                    site_id=site_id,
                    home_site=home_site,
                    local_pricing=local_pricing,
                    member_availability=member_availability,
                    capacity_buckets=buckets_for_site,
                    declaration=declaration,
                    holds=holds,
                    report=report,
                    hint_resolution=hint_resolution,
                    shape_feasible=shape_feasible,
                    declared_only=declared_only,
                )
            )
        _record_site_report(site_id, report)
    return pool_rows


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


def _local_table_shapes(
    row: Mapping[str, Any], *, declared_range: bool
) -> tuple[ResolvedShape, ...]:
    """GPU-only shapes for a pool read from local tables.

    Local tables hold no projected members or hints, so a pool's shapes are the
    default GPU-only shapes for its one model, ranged over what its members make
    available. A pool with no model has no shape.
    """
    model = row.get("gpu_model")
    if not isinstance(model, str) or not model.strip():
        return ()
    range_field = (
        "max_member_declared_gpu_count"
        if row.get("capacity_backing") == "unbacked" or declared_range
        else "max_member_available_gpu_count"
    )
    return tuple(
        resolve_shape({"gpu": {"count": count, "model": model}})
        for count in range(1, int(row.get(range_field) or 0) + 1)
    )


def available_compute_slices(
    db_path: str,
    *,
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]] | None = None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    hint_resolution: PoolHintResolutionSettings = _DEFAULT_POOL_HINT_RESOLUTION_SETTINGS,
    holds: set[tuple[str, str, str]] | None = None,
    declared_range: bool = False,
    shape_feasible: ShapeFeasibility,
) -> list[dict[str, Any]]:
    """Return publishable compute listing slices from current storefront state.

    Pool membership and market attributes (pricing, escrows) are local —
    the aggregator view. Consumption is the site authorities' answer:
    ``member_availability`` holds available units keyed by
    ``(site, resource_id)`` from the aggregated snapshots (``site=None``
    is the storefront's home site, matching members with no site tag); a
    member the snapshots don't cover is not reservable and counts as 0.
    ``None`` means the caller has no consumption information (publish
    flows when the authority is unreachable) — members are then assumed
    fully available, which the reserve path corrects authoritatively.

    ``home_site`` is the site every returned slice is attributed to when
    reading local tables (``site_pool_projection`` omitted or empty, the
    default). This preserves every existing caller's behavior exactly.

    ``site_pool_projection`` is an optional ``site_id -> resource-pool
    projection rows`` mapping (the same shape
    ``site_projection_cache.projection_caches()[site].resource_pools.view().value``
    already produces). When supplied and non-empty, pool structure and
    GPU model come from the projection for *every* site in it, not just
    ``home_site``. The local ``compute_capacity_pools`` table is only
    ever consulted, for ``home_site``'s own pools, as the top-precedence
    storefront-override tier of region/SLA/pricing resolution -- never
    for a non-``home_site`` pool, avoiding the cross-site ``pool_id``
    collision that table's own lack of site-scoping would otherwise risk.
    A pool with no local override row (a non-``home_site`` pool, or a
    ``home_site`` pool the storefront hasn't locally registered) still
    publishes: region/SLA/pricing fall through to that pool's own
    projected hint, then the storefront's configured default, the same
    "priceless" handling other publish flows already support if nothing
    resolves a real price -- a missing override is advisory-tier
    absence, not a reason to suppress the pool.

    A pool's ``listing_cardinality_mode`` (from its projected
    ``policy_tags``, only available on the ``site_pool_projection`` path)
    decides its row shape:
    ``fungible`` publishes one pool-keyed aggregated row; ``specific_resource``
    publishes one resource-keyed row per enabled member, however many
    members the pool has. ``site_capacity_buckets`` is the matching
    ``site_capacity_buckets`` projection (same per-site-list shape as
    ``site_pool_projection``) and, when supplied, sources a ``fungible``
    pool's per-member availability ceiling instead of a resource-list max
    -- see ``_projected_pool_rows``. Only takes effect on the projection
    path; the local-table fallback has no ``policy_tags``/bucket source
    and is unaffected by either parameter.

    Every slice is one listing shape: the pool's stated ``listing_shapes`` for
    the ``vm`` mode, or the default GPU-only shapes generated from its members.
    A shape yields a slice only where ``shape_feasible`` judges some source
    member able to serve the claim its listing would produce: against declared
    capacity always, and for a capacity-backed pool against current
    availability too, so capacity changes move a backed pool's slices and only
    declaration changes move an unbacked pool's. ``declared_range`` judges every
    pool on declared capacity alone, which is what a listing's source still
    declares regardless of what is currently free. Each slice carries its
    pool's ``capacity_backing``, its canonical shape and digest, and exactly the
    quantities its shape declares.

    ``holds`` collects ``("pool", site, pool_id)`` and
    ``("resource", site, resource_id)`` entries for sources whose declarations
    cannot be read. Their listings must be neither closed nor refreshed, so
    callers that reconcile keep them out of both.

    ``hint_resolution`` controls how much a pool's own
    projected ``region``/``sla`` hints are trusted relative to the
    storefront's local `compute_capacity_pools` fallback/override values
    -- see `domains.vms.listings.pool_descriptors`. Only takes effect on
    the projection path, the same as ``site_pool_projection``/
    ``site_capacity_buckets`` above; the local-table fallback has no hint
    source to resolve against.
    """
    held = holds if holds is not None else set()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        if site_pool_projection:
            pool_rows = _pool_rows_from_projection(
                conn,
                site_pool_projection,
                home_site=home_site,
                member_availability=member_availability,
                site_capacity_buckets=site_capacity_buckets,
                hint_resolution=hint_resolution,
                holds=held,
                shape_feasible=shape_feasible,
                declared_only=declared_range,
            )
        else:
            pool_rows = _pool_rows_from_local_tables(
                conn, member_availability, home_site=home_site
            )
            # Local tables can express only capacity-backed supply: nothing
            # in them declares a pool with no admission authority.
            for row in pool_rows:
                row["capacity_backing"] = "backed"
                row["max_member_declared_gpu_count"] = row.get(
                    "max_member_available_gpu_count"
                )
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for row in pool_rows:
        if row.get("offering_mode") != "vm":
            continue
        site_id = str(row.get("site_id") or home_site)
        accepted_escrows = _parsed_escrows(row.get("accepted_escrows"))
        settlements = _parsed_settlements(row.get("settlements"))
        backing = row["capacity_backing"]
        pool_id = str(row["pool_id"])
        single_resource_id = row.get("single_resource_id")
        shapes = row.get("feasible_shapes")
        if shapes is None:
            shapes = _local_table_shapes(row, declared_range=declared_range)
        pricing_by_model = row.get("pricing_by_model") or {}
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
                "min_price": pricing.min_price if pricing else row.get("min_price"),
                "token": pricing.token if pricing else row.get("token"),
                "accepted_escrows": accepted_escrows,
                "settlements": settlements,
                "max_duration_seconds": (
                    pricing.max_duration_seconds
                    if pricing
                    else row.get("max_duration_seconds")
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
            out.append(candidate)
    return out


def current_available_resource_keys(
    db_path: str,
    *,
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]] | None = None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    holds: set[tuple[str, str, str]] | None = None,
    shape_feasible: ShapeFeasibility,
) -> set[str]:
    # Known, accepted cost, not an oversight: `available_compute_slices`
    # resolves each row's region/SLA/pricing (the full three-tier chain,
    # `PoolHintResolutionSettings` and all) even though only
    # `resource_key` is read below -- everything
    # else is discarded. This is deliberately not worth avoiding here:
    # resolution happens once per pool/member (not per gpu_count slice,
    # since the gpu_count loop only copies already-resolved fields), so
    # the actual cost is bounded by pool/member count, not capacity size.
    # `stale_open_listing_ids` (below) calls this function for exactly this
    # reason -- capacity-delta
    # reconciliation compares structural derivation keys and availability;
    # it never recomputes or republishes commercial listing terms, which
    # is also why none of these three functions take a `hint_resolution`
    # parameter at all (they always resolve with the default, and the
    # result is provably identical regardless -- see
    # `test_resource_keys_are_identical_regardless_of_hint_resolution` in
    # `test_reconciler.py`). A narrower structural-only row builder would
    # avoid the discarded work, but isn't warranted while the cost stays
    # bounded this way; noted as a candidate cleanup, not a defect.
    keys: set[str] = set()
    for row in available_compute_slices(
        db_path,
        home_site=home_site,
        member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
        holds=holds,
        shape_feasible=shape_feasible,
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


def _is_held(
    listing_resource: Mapping[str, Any],
    site_id: str,
    holds: set[tuple[str, str, str]],
) -> bool:
    pool_id = listing_resource.get("pool_id")
    resource_id = listing_resource.get("resource_id")
    return ("pool", str(site_id), str(pool_id)) in holds or (
        resource_id is not None
        and ("resource", str(site_id), str(resource_id)) in holds
    )


@dataclass(frozen=True, slots=True)
class BoundVmListing:
    """One bound VM listing as reconciliation reads it."""

    listing_id: str
    listing_resource: dict[str, Any]
    site_id: str
    capacity_backing: str
    source_envelope: Mapping[str, Any] | None = None

    @property
    def key(self) -> str | None:
        return stored_listing_key(self.source_envelope, self.listing_resource, self.site_id)


def _bound_vm_listings(
    db_path: str,
    *,
    open_listings: bool,
    backed_only: bool,
) -> list[BoundVmListing]:
    """Bound VM listings with their binding's site and backing.

    Closed listings exclude those their seller closed: no reconciliation path
    reopens a listing its seller withdrew. ``backed_only`` restricts the read to
    listings bound as capacity-backed, which is all availability reconciliation
    may act on.
    """
    clauses = [
        "l.status = 'open'"
        if open_listings
        else "l.status != 'open' AND l.closed_by IS NOT 'seller'",
        "b.offering_mode = 'vm'",
    ]
    if backed_only:
        clauses.append("b.capacity_backing = 'backed'")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            f"""
            SELECT l.listing_id, l.listing_resource, b.site_id, b.capacity_backing,
                   b.source_envelope_json
            FROM listings l
            JOIN storefront_listing_bindings b ON b.listing_id = l.listing_id
            WHERE {' AND '.join(clauses)}
            """
        ).fetchall()
    finally:
        conn.close()
    out: list[BoundVmListing] = []
    for listing_id, raw, site_id, capacity_backing, envelope in rows:
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
                    str(capacity_backing),
                    _source_envelope(envelope),
                )
            )
    return out


def open_listing_resource_keys(
    db_path: str,
    *,
    home_site: str,
    configured_site_count: int,
) -> set[str]:
    """Return exact site-scoped keys covered by bound open VM listings."""

    del home_site, configured_site_count
    covered: set[str] = set()
    for listing in _bound_vm_listings(db_path, open_listings=True, backed_only=False):
        key = listing.key
        if key is not None:
            covered.add(key)
    return covered


def stale_open_listing_ids(
    db_path: str,
    *,
    home_site: str,
    configured_site_count: int,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]] | None = None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    backed_only: bool,
    shape_feasible: ShapeFeasibility,
) -> list[str]:
    """Return bound VM listings whose exact site-scoped slice is gone.

    A listing whose source cannot currently be read is held, not stale.
    ``backed_only`` has no default because the two reconciliations differ:
    source reconciliation (the publication loop) closes any listing whose
    source is gone, while availability reconciliation (capacity events, a
    release, a failed deal) acts only on capacity-backed listings, since no
    availability figure describes an unbacked one.
    """

    del configured_site_count
    holds: set[tuple[str, str, str]] = set()
    available_keys = current_available_resource_keys(
        db_path,
        home_site=home_site,
        member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
        holds=holds,
        shape_feasible=shape_feasible,
    )
    stale: list[str] = []
    for listing in _bound_vm_listings(
        db_path, open_listings=True, backed_only=backed_only
    ):
        if _is_held(listing.listing_resource, listing.site_id, holds):
            continue
        key = listing.key
        if key is not None and key not in available_keys:
            stale.append(listing.listing_id)
    return stale


def closed_available_listing_ids(
    db_path: str,
    *,
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]] | None = None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    shape_feasible: ShapeFeasibility,
) -> list[str]:
    """Return closed capacity-backed VM listings that may reopen now.

    This is availability reconciliation: its callers are capacity events, a
    released reservation, and a failed deal, so it reads only listings bound as
    capacity-backed. An unbacked listing is reopened by the publication loop,
    which refreshes its terms from its source as it does.

    A listing may reopen when its exact slice is available again, its seller did
    not close it, its source is not held, and its published identity and its
    binding's backing still match what its source derives. Every availability
    reopen shares this predicate, so a listing closed because its source changed
    is not reopened by a capacity event that happens to free its slice.
    """
    holds: set[tuple[str, str, str]] = set()
    slices: dict[str, dict[str, Any]] = {}
    for row in available_compute_slices(
        db_path,
        home_site=home_site,
        member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
        holds=holds,
        shape_feasible=shape_feasible,
    ):
        if row.get("resource_key"):
            slices[str(row["resource_key"])] = row
    if not slices:
        return []
    available: list[tuple[int, str]] = []
    for listing in _bound_vm_listings(db_path, open_listings=False, backed_only=True):
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
            binding_backing=listing.capacity_backing,
            source_backing=str(fresh.get("capacity_backing")),
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
        available.append((int(listing_resource["gpu_count"]), listing_id))
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
