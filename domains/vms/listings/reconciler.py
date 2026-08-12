from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping

from domains.vms.listings.listing_mode import resolve_vm_listing_mode
from domains.vms.listings.pool_descriptors import resolve_region, resolve_sla
from domains.vms.listings.pricing_resolution import GpuPricingFields, resolve_gpu_pricing
from market_identity import Identity


HELD_ALLOCATION_STATES = {
    "reserved",
    "provisioning",
    "leased",
    "releasing",
    "held",
}


def _length_prefixed(value: str) -> str:
    """Encode a field so its boundary is unambiguous regardless of its
    own content -- ``site_id``/``pool_id``/``resource_id`` are operator-
    chosen strings with no character restrictions (no validation
    anywhere rejects e.g. a colon), so naive delimiter-joining these
    fields is not collision-free: ``site_id="a", pool_id="b:c"`` and
    ``site_id="a:b", pool_id="c"`` would otherwise produce an identical
    key. A decimal length prefix followed by exactly that many
    characters fixes each field's boundary exactly, independent of its
    contents, making the overall key injective (different inputs always
    produce different keys).
    """
    return f"{len(value)}:{value}"


def listing_resource_key(
    site_id: str, resource_id: str, gpu_count: int | str | None,
) -> str:
    if not site_id or not site_id.strip():
        raise ValueError("site_id must be non-empty")
    return (
        f"{_length_prefixed(site_id)}:{_length_prefixed(resource_id)}"
        f":gpus:{int(gpu_count or 1)}"
    )


def listing_pool_key(
    site_id: str, pool_id: str, gpu_count: int | str | None,
) -> str:
    if not site_id or not site_id.strip():
        raise ValueError("site_id must be non-empty")
    return (
        f"pool:{_length_prefixed(site_id)}:{_length_prefixed(pool_id)}"
        f":gpus:{int(gpu_count or 1)}"
    )


def ensure_derived_compute_listings_table(conn: sqlite3.Connection | sqlite3.Cursor) -> None:
    """Create/upgrade derived_compute_listings and its indexes.

    The single source of truth for this table's schema -- called both
    lazily by this module's own write functions (via a plain
    sqlite3.Connection, for standalone/test use with no SQLiteClient
    involved) and eagerly by SQLiteClient._ensure_domain_tables (via its
    cursor, at every storefront startup) so the table and its current
    columns exist before any request-handling code runs. Both callers
    only need `.execute()`, which Connection and Cursor both provide.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS derived_compute_listings (
          listing_id TEXT PRIMARY KEY,
          site_id TEXT,
          pool_id TEXT,
          resource_id TEXT NOT NULL,
          gpu_count INTEGER NOT NULL,
          status TEXT NOT NULL,
          derivation_key TEXT NOT NULL UNIQUE,
          last_reconciled_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )
    cols = {
        row[1] for row in conn.execute("PRAGMA table_info(derived_compute_listings)")
    }
    if "pool_id" not in cols:
        conn.execute("ALTER TABLE derived_compute_listings ADD COLUMN pool_id TEXT")
    if "site_id" not in cols:
        conn.execute("ALTER TABLE derived_compute_listings ADD COLUMN site_id TEXT")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_compute_listings_resource "
        "ON derived_compute_listings(resource_id, gpu_count)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_compute_listings_pool "
        "ON derived_compute_listings(pool_id, gpu_count)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_compute_listings_status "
        "ON derived_compute_listings(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_derived_compute_listings_site "
        "ON derived_compute_listings(site_id)"
    )


def site_id_for_listing(db_path: str, listing_id: str) -> str | None:
    """The site a listing is mapped to, or None if unmapped.

    `derived_compute_listings` is the single source of truth for this --
    callers needing a listing's site (to build a site-scoped derivation
    key, or to pin a capacity reservation) resolve it here rather than
    reading it off the listing's own public offer, which never carries
    it.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        if not _has_derived_listings_site_column(conn):
            return None
        row = conn.execute(
            "SELECT site_id FROM derived_compute_listings WHERE listing_id = ?",
            (listing_id,),
        ).fetchone()
    finally:
        conn.close()
    return str(row[0]) if row and row[0] else None


def pool_id_for_listing(db_path: str, listing_id: str) -> str | None:
    """The pool a listing is mapped to, or None if unmapped.

    Mirrors ``site_id_for_listing`` -- ``derived_compute_listings`` is the
    single source of truth for this mapping too.

    For a listing recorded with only a ``resource_id`` (no genuine pool),
    ``record_derived_listing`` backfills its ``pool_id`` column to the
    resource_id itself (its own ``resolved_pool_id`` fallback, needed
    because that column is used as a not-null join key) -- storage alone
    cannot distinguish that case from a genuine pool, since both produce
    an identical stored row shape. Callers looking up a *pool's*
    ``policy_tags`` in the projection cache don't need that distinction
    made here: a resource id looked up against the cache's
    ``resource_pool_id`` field will not match any real pool in practice
    (pool ids and physical resource ids are different id namespaces
    throughout this system), so it naturally falls through to "no
    policy_tags found" with no special-casing required.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        if not _has_derived_listings_site_column(conn):
            return None
        row = conn.execute(
            "SELECT pool_id FROM derived_compute_listings WHERE listing_id = ?",
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
    site_select = "m.site" if "site" in member_cols else "NULL AS site"
    return conn.execute(
        f"""
        SELECT p.pool_id, p.gpu_model, p.region, p.sla,
               p.total_gpu_count, p.min_price, p.token,
               p.accepted_escrows, p.max_duration_seconds,
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
) -> None:
    """Fold one compute_pool_members row into its pool's running
    aggregate, in place."""
    member_total = int(row["gpu_count"] or 0)
    member_site = str(row["site"]) if row["site"] else None
    member_key = (member_site, str(row["resource_id"]))
    member_available = _member_available_units(member_total, member_key, member_availability)
    pool["total_gpu_count"] += member_total
    pool["available_gpu_count"] += member_available
    pool["max_member_available_gpu_count"] = max(
        int(pool["max_member_available_gpu_count"]), member_available,
    )
    pool["member_count"] += 1
    pool["single_resource_id"] = (
        str(row["resource_id"]) if pool["member_count"] == 1 else None
    )


def _pool_rows_from_capacity_pools(
    conn: sqlite3.Connection,
    member_availability: dict[tuple[str | None, str], int] | None,
) -> list[dict[str, Any]]:
    """compute_capacity_pools JOIN compute_pool_members, grouped by pool
    -- the fungible-pool-capable local source, preferred over the legacy
    resources table whenever both tables exist."""
    by_pool: dict[str, dict[str, Any]] = {}
    for row in _capacity_pool_member_rows(conn):
        pool_id = str(row["pool_id"])
        pool = by_pool.setdefault(pool_id, {
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
            "max_duration_seconds": row["max_duration_seconds"],
            "single_resource_id": None,
            "member_count": 0,
        })
        _accumulate_capacity_pool_member(pool, row, member_availability)
    return list(by_pool.values())


def _legacy_resource_columns(conn: sqlite3.Connection) -> tuple[bool, bool]:
    """Whether the legacy resources table has the optional
    accepted_escrows/max_duration_seconds columns -- older schemas may
    predate one or both."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(resources)").fetchall()}
    return "accepted_escrows" in cols, "max_duration_seconds" in cols


def _project_legacy_resource_row(
    row: sqlite3.Row,
    *,
    has_accepted: bool,
    has_max_duration: bool,
    member_availability: dict[tuple[str | None, str], int] | None,
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
        total_gpu_count, (None, str(row["resource_id"])), member_availability,
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
        "max_duration_seconds": (
            row["max_duration_seconds"] if has_max_duration else None
        ),
    }


def _pool_rows_from_legacy_resources(
    conn: sqlite3.Connection,
    member_availability: dict[tuple[str | None, str], int] | None,
) -> list[dict[str, Any]]:
    """Legacy `resources` table fallback, used only when
    compute_capacity_pools/compute_pool_members don't both exist."""
    has_accepted, has_max_duration = _legacy_resource_columns(conn)
    select_extra = ""
    if has_accepted:
        select_extra += ", accepted_escrows"
    if has_max_duration:
        select_extra += ", max_duration_seconds"
    rows = conn.execute(
        f"""SELECT resource_id, resource_subtype, unit, value, state, attributes,
                  min_price, token{select_extra}
           FROM resources
           WHERE resource_type = 'compute.gpu' AND state = 'available'
           ORDER BY resource_id""",
    ).fetchall()
    return [
        _project_legacy_resource_row(
            row, has_accepted=has_accepted, has_max_duration=has_max_duration,
            member_availability=member_availability,
        )
        for row in rows
    ]


def _pool_rows_from_local_tables(
    conn: sqlite3.Connection,
    member_availability: dict[tuple[str | None, str], int] | None,
) -> list[dict[str, Any]]:
    """Local-table sourcing: compute_capacity_pools joined with
    compute_pool_members when both exist, else the legacy resources
    table. One of the two capacity sources `available_compute_slices`
    can choose between, alongside `_pool_rows_from_projection`.
    """
    has_pools = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_capacity_pools'"
    ).fetchone() is not None
    has_members = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_pool_members'"
    ).fetchone() is not None
    if has_pools and has_members:
        return _pool_rows_from_capacity_pools(conn, member_availability)
    return _pool_rows_from_legacy_resources(conn, member_availability)


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
    has_pools = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_capacity_pools'"
    ).fetchone() is not None
    if not has_pools:
        return {}
    return {
        str(row["pool_id"]): row
        for row in conn.execute(
            """
            SELECT pool_id, gpu_model, region, sla, min_price, token,
                   accepted_escrows, max_duration_seconds
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


def _projected_resource_usage(
    resource: Mapping[str, Any],
    *,
    site_id: str,
    member_availability: dict[tuple[str | None, str], int] | None,
) -> "_ProjectedResourceUsage | None":
    """Derive one projected resource's identity, GPU model, and usage --
    or None if it has no physical_resource_id to key on. Pure and
    independently testable: no dict mutation, no accumulation, just this
    one resource's own facts.
    """
    resource_id = str(resource.get("physical_resource_id") or "")
    if not resource_id:
        return None
    attrs = resource.get("attributes") or {}
    gpu_model = attrs.get("gpu_model") or None
    capacity = resource.get("capacity") or {}
    total = int(capacity.get("gpu_count") or 0)
    available_field = resource.get("available")
    if available_field is not None:
        # The projection already carries this resource's live
        # availability -- use it directly, regardless of whether a
        # member_availability lookup is also available. This is
        # authoritative data from the projection itself, not a
        # fallback source to be skipped whenever a different fallback
        # (member_availability) happens to be present or absent.
        available = max(0, min(total, int((available_field or {}).get("gpu_count") or 0)))
    elif member_availability is not None:
        available = _member_available_units(
            total, (site_id, resource_id), member_availability,
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
    pool_id: str, capacity_buckets: list[Mapping[str, Any]] | None,
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
    hint_resolution: PoolHintResolutionSettings = _DEFAULT_POOL_HINT_RESOLUTION_SETTINGS,
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
    ``specific_resource`` pool -- a pool's ``listing_mode`` (from its
    projected `policy_tags`, domain-resolved by `resolve_vm_listing_mode`)
    decides which shape applies. An explicit tag always wins; its
    *absence* falls back to exactly the structural heuristic this
    function used before `listing_mode` existed (`member_count == 1` ->
    specific_resource) so an untagged pool's publication shape does not
    change out from under an existing derived-listing mapping.
    """
    pool_id = str(pool.get("resource_pool_id") or "").strip()
    if not pool_id:
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
    for resource in pool.get("resources") or []:
        if not resource.get("enabled", True):
            continue
        usage = _projected_resource_usage(
            resource, site_id=site_id, member_availability=member_availability,
        )
        if usage is not None:
            usages.append(usage)

    metadata = pool.get("pool_metadata") or {}
    policy_tags = metadata.get("policy_tags") or {}

    structural_default = "specific_resource" if len(usages) == 1 else "fungible"
    mode, explanation = resolve_vm_listing_mode(
        policy_tags, structural_default=structural_default,
    )

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
        "listing_mode": mode,
        "listing_mode_explanation": explanation,
    }

    if mode == "specific_resource":
        rows = []
        for usage in usages:
            resolved_gpu_model = usage.gpu_model or local_gpu_model
            resolved_pricing = _resolved_pricing(resolved_gpu_model)
            rows.append({
                **base_fields,
                "gpu_model": resolved_gpu_model,
                "min_price": resolved_pricing.min_price,
                "token": resolved_pricing.token,
                "accepted_escrows": resolved_pricing.accepted_escrows,
                "max_duration_seconds": resolved_pricing.max_duration_seconds,
                "total_gpu_count": usage.total,
                "available_gpu_count": usage.available,
                "max_member_available_gpu_count": usage.available,
                "single_resource_id": usage.resource_id,
                "member_count": 1,
            })
        return rows

    # fungible: exactly one aggregated row.
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

    return [{
        **base_fields,
        "gpu_model": resolved_gpu_model,
        "min_price": resolved_pricing.min_price,
        "token": resolved_pricing.token,
        "accepted_escrows": resolved_pricing.accepted_escrows,
        "max_duration_seconds": resolved_pricing.max_duration_seconds,
        "total_gpu_count": total_gpu_count,
        "available_gpu_count": available_gpu_count,
        "max_member_available_gpu_count": max_member_available,
        "single_resource_id": None,
        "member_count": len(usages),
    }]


def _pool_rows_from_projection(
    conn: sqlite3.Connection,
    site_pool_projection: Mapping[str, list[dict[str, Any]]],
    *,
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    hint_resolution: PoolHintResolutionSettings = _DEFAULT_POOL_HINT_RESOLUTION_SETTINGS,
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
    local_pricing = _local_pool_pricing(conn)
    pool_rows: list[dict[str, Any]] = []
    for site_id, pools in site_pool_projection.items():
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
            pool_rows.extend(
                _projected_pool_rows(
                    pool, site_id=site_id, home_site=home_site,
                    local_pricing=local_pricing, member_availability=member_availability,
                    capacity_buckets=buckets_for_site,
                    hint_resolution=hint_resolution,
                )
            )
    return pool_rows

def available_compute_slices(
    db_path: str,
    *,
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]] | None = None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
    hint_resolution: PoolHintResolutionSettings = _DEFAULT_POOL_HINT_RESOLUTION_SETTINGS,
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

    A pool's ``listing_mode`` (from its projected ``policy_tags``, only
    available on the ``site_pool_projection`` path) decides its row shape:
    ``fungible`` publishes one pool-keyed aggregated row; ``specific_resource``
    publishes one resource-keyed row per enabled member, however many
    members the pool has. ``site_capacity_buckets`` is the matching
    ``site_capacity_buckets`` projection (same per-site-list shape as
    ``site_pool_projection``) and, when supplied, sources a ``fungible``
    pool's per-member availability ceiling instead of a resource-list max
    -- see ``_projected_pool_rows``. Only takes effect on the projection
    path; the local-table fallback has no ``policy_tags``/bucket source
    and is unaffected by either parameter.

    ``hint_resolution`` controls how much a pool's own
    projected ``region``/``sla`` hints are trusted relative to the
    storefront's local `compute_capacity_pools` fallback/override values
    -- see `domains.vms.listings.pool_descriptors`. Only takes effect on
    the projection path, the same as ``site_pool_projection``/
    ``site_capacity_buckets`` above; the local-table fallback has no hint
    source to resolve against.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        if site_pool_projection:
            pool_rows = _pool_rows_from_projection(
                conn, site_pool_projection,
                home_site=home_site, member_availability=member_availability,
                site_capacity_buckets=site_capacity_buckets,
                hint_resolution=hint_resolution,
            )
        else:
            pool_rows = _pool_rows_from_local_tables(conn, member_availability)
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for row in pool_rows:
        site_id = str(row.get("site_id") or home_site)
        accepted_escrows: list[dict[str, Any]] | None = None
        raw = row.get("accepted_escrows")
        if isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    accepted_escrows = parsed
            except json.JSONDecodeError:
                accepted_escrows = None
        max_slice = int(row.get("max_member_available_gpu_count") or 0)
        for gpu_count in range(1, max_slice + 1):
            pool_id = str(row["pool_id"])
            single_resource_id = row.get("single_resource_id")
            is_fungible_pool = not single_resource_id
            out.append({
                "site_id": site_id,
                "pool_id": pool_id,
                "resource_id": single_resource_id,
                "resource_key": (
                    listing_pool_key(site_id, pool_id, gpu_count)
                    if is_fungible_pool
                    else listing_resource_key(site_id, str(single_resource_id), gpu_count)
                ),
                "legacy_resource_key": (
                    listing_resource_key(site_id, single_resource_id, gpu_count)
                    if single_resource_id
                    else None
                ),
                "gpu_model": row.get("gpu_model"),
                "gpu_count": gpu_count,
                "total_gpu_count": row.get("total_gpu_count"),
                "available_gpu_count": row.get("available_gpu_count"),
                "sla": row.get("sla", 0.0),
                "region": row.get("region"),
                "min_price": row.get("min_price"),
                "token": row.get("token"),
                "accepted_escrows": accepted_escrows,
                "max_duration_seconds": row.get("max_duration_seconds"),
                "listing_mode": row.get("listing_mode"),
                "listing_mode_explanation": row.get("listing_mode_explanation"),
            })
    return out


def current_available_resource_keys(
    db_path: str,
    *,
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]] | None = None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
) -> set[str]:
    # Known, accepted cost, not an oversight: `available_compute_slices`
    # resolves each row's region/SLA/pricing (the full three-tier chain,
    # `PoolHintResolutionSettings` and all) even though only
    # `resource_key`/`legacy_resource_key` are read below -- everything
    # else is discarded. This is deliberately not worth avoiding here:
    # resolution happens once per pool/member (not per gpu_count slice,
    # since the gpu_count loop only copies already-resolved fields), so
    # the actual cost is bounded by pool/member count, not capacity size.
    # `stale_open_listing_ids`/`closed_available_listing_ids` (below) call
    # this function for exactly this reason -- capacity-delta
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
        db_path, home_site=home_site, member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
    ):
        if row.get("resource_key"):
            keys.add(str(row["resource_key"]))
        if row.get("legacy_resource_key"):
            keys.add(str(row["legacy_resource_key"]))
    return keys


def _has_derived_listings_site_column(conn: sqlite3.Connection) -> bool:
    """Whether derived_compute_listings exists AND has its site_id column.

    Table existence alone is not enough to prove the column is there --
    an existing on-disk database can predate this column even though
    `ensure_derived_compute_listings_table` is now the single place this
    table's schema is defined (`SQLiteClient` delegates to it rather
    than keeping its own copy); the column only appears once that
    function has actually run against this specific file. Checking the
    specific column here, not just the table, is what protects a query
    against reading that pre-migration state.
    """
    if conn.execute(
        "SELECT 1 FROM sqlite_master "
        "WHERE type='table' AND name='derived_compute_listings'"
    ).fetchone() is None:
        return False
    cols = {row[1] for row in conn.execute("PRAGMA table_info(derived_compute_listings)")}
    return "site_id" in cols


def open_listing_resource_keys(
    db_path: str, *, home_site: str, configured_site_count: int,
) -> set[str]:
    """Return site-scoped keys already covered by open listings.

    See ``stale_open_listing_ids`` for the full rationale: a listing's
    own mapping is used when it has one; an unmapped listing falls back
    to ``home_site`` only when exactly one site is currently configured
    (``configured_site_count == 1``), never assumed.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        has_derived = _has_derived_listings_site_column(conn)
        site_select = "d.site_id" if has_derived else "NULL AS site_id"
        join_clause = (
            "LEFT JOIN derived_compute_listings d ON d.listing_id = l.listing_id"
            if has_derived else ""
        )
        rows = conn.execute(
            f"""
            SELECT l.offer_resource, {site_select}
            FROM listings l
            {join_clause}
            WHERE l.status = 'open'
            """
        ).fetchall()
    finally:
        conn.close()

    covered: set[str] = set()
    for raw, mapped_site_id in rows:
        if not raw:
            continue
        if mapped_site_id:
            site_id = str(mapped_site_id)
        elif configured_site_count == 1:
            site_id = home_site
        else:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        pool_id = parsed.get("pool_id")
        if pool_id:
            covered.add(listing_pool_key(site_id, str(pool_id), parsed.get("gpu_count")))
            continue
        rid = parsed.get("resource_id")
        if rid:
            covered.add(listing_resource_key(site_id, str(rid), parsed.get("gpu_count")))
    return covered


def stale_open_listing_ids(
    db_path: str,
    *,
    home_site: str,
    configured_site_count: int,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]] | None = None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
) -> list[str]:
    """Open listing IDs whose requested slice no longer fits capacity.

    A listing's own site mapping is used when it has one. A listing with
    no ``derived_compute_listings`` row at all falls back to
    ``home_site`` only when ``configured_site_count == 1`` -- the caller
    must pass the actual number of sites configured *right now*, not an
    assumption baked into this function. With exactly one site, the
    fallback is exact (there is no other site the listing could belong
    to); with more than one, an unmapped listing is genuinely ambiguous
    and is skipped instead, matching the same quarantine-rather-than-guess
    principle a backfill migration also applies to legacy rows. This is
    deliberately not a permanent single-site invariant -- the moment a
    second site is configured, this function's own behavior changes
    without needing a code change.
    """
    available_keys = current_available_resource_keys(
        db_path, home_site=home_site, member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
    )
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        has_derived = _has_derived_listings_site_column(conn)
        site_select = "d.site_id" if has_derived else "NULL AS site_id"
        join_clause = (
            "LEFT JOIN derived_compute_listings d ON d.listing_id = l.listing_id"
            if has_derived else ""
        )
        rows = conn.execute(
            f"""
            SELECT l.listing_id, l.offer_resource, {site_select}
            FROM listings l
            {join_clause}
            WHERE l.status = 'open'
            """
        ).fetchall()
    finally:
        conn.close()

    stale: list[str] = []
    for listing_id, raw, mapped_site_id in rows:
        if not raw:
            continue
        if mapped_site_id:
            site_id = str(mapped_site_id)
        elif configured_site_count == 1:
            site_id = home_site
        else:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        pool_id = parsed.get("pool_id")
        if pool_id:
            key = listing_pool_key(site_id, str(pool_id), parsed.get("gpu_count"))
            if key not in available_keys:
                stale.append(str(listing_id))
            continue
        rid = parsed.get("resource_id")
        if not rid:
            continue
        if listing_resource_key(site_id, str(rid), parsed.get("gpu_count")) not in available_keys:
            stale.append(str(listing_id))
    return stale


def closed_available_listing_ids(
    db_path: str,
    *,
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]] | None = None,
    site_capacity_buckets: Mapping[str, list[dict[str, Any]]] | None = None,
) -> list[str]:
    """Closed derived listing IDs whose requested slice fits capacity again."""
    available_keys = current_available_resource_keys(
        db_path, home_site=home_site, member_availability=member_availability,
        site_pool_projection=site_pool_projection,
        site_capacity_buckets=site_capacity_buckets,
    )
    if not available_keys:
        return []
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        table_exists = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='derived_compute_listings'"
        ).fetchone()
        if table_exists is None:
            return []
        placeholders = ", ".join("?" for _ in available_keys)
        rows = conn.execute(
            f"""
            SELECT d.listing_id
            FROM derived_compute_listings d
            LEFT JOIN listings l ON l.listing_id = d.listing_id
            WHERE d.derivation_key IN ({placeholders})
              AND (d.status != 'open' OR l.status != 'open')
            ORDER BY d.gpu_count
            """,
            tuple(sorted(available_keys)),
        ).fetchall()
    finally:
        conn.close()
    return [str(row[0]) for row in rows]


def record_derived_listing(
    db_path: str,
    *,
    listing_id: str,
    site_id: str,
    resource_id: str | None,
    gpu_count: int,
    pool_id: str | None = None,
    status: str = "open",
) -> None:
    resolved_pool_id = pool_id or resource_id
    if not resolved_pool_id:
        raise ValueError("pool_id or resource_id is required")
    # A resource-keyed candidate is any call that supplies a resource_id --
    # pool_id's mere presence is not signal: pool_id and resource_id are
    # always different id spaces (operator pool slug vs. physical resource
    # id), so `pool_id != resource_id` is true whenever both are supplied,
    # regardless of listing_mode. This must key on `resource_id is None`,
    # matching `available_compute_slices`' own `is_fungible_pool` meaning
    # exactly, or multiple specific_resource listings from the same pool
    # collide onto one derivation_key and silently overwrite each other.
    use_pool_key = pool_id is not None and resource_id is None
    derivation_key = (
        listing_pool_key(site_id, resolved_pool_id, gpu_count)
        if use_pool_key
        else listing_resource_key(site_id, str(resource_id or resolved_pool_id), gpu_count)
    )
    conn = sqlite3.connect(db_path)
    try:
        ensure_derived_compute_listings_table(conn)
        conn.execute(
            """
            INSERT INTO derived_compute_listings(
              listing_id, site_id, pool_id, resource_id, gpu_count, status, derivation_key, last_reconciled_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(derivation_key) DO UPDATE SET
              listing_id=excluded.listing_id,
              site_id=excluded.site_id,
              pool_id=excluded.pool_id,
              resource_id=excluded.resource_id,
              gpu_count=excluded.gpu_count,
              status=excluded.status,
              last_reconciled_at=excluded.last_reconciled_at
            """,
            (
                listing_id,
                site_id,
                resolved_pool_id,
                resource_id or resolved_pool_id,
                int(gpu_count),
                status,
                derivation_key,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_derived_listing_for_slice(
    db_path: str,
    *,
    site_id: str,
    gpu_count: int,
    resource_id: str | None = None,
    pool_id: str | None = None,
) -> dict[str, Any] | None:
    derivation_keys: list[str] = []
    if pool_id:
        derivation_keys.append(listing_pool_key(site_id, pool_id, gpu_count))
    if resource_id:
        derivation_keys.append(listing_resource_key(site_id, resource_id, gpu_count))
    if not derivation_keys:
        raise ValueError("pool_id or resource_id is required")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        row_exists = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='derived_compute_listings'"
        ).fetchone()
        if row_exists is None:
            return None
        cols = {
            row[1] for row in conn.execute("PRAGMA table_info(derived_compute_listings)")
        }
        pool_select = "d.pool_id" if "pool_id" in cols else "NULL AS pool_id"
        site_select = "d.site_id" if "site_id" in cols else "NULL AS site_id"
        placeholders = ", ".join("?" for _ in derivation_keys)
        row = conn.execute(
            f"""
            SELECT d.listing_id, {site_select}, {pool_select}, d.resource_id, d.gpu_count, d.status,
                   d.derivation_key, l.status AS listing_status
            FROM derived_compute_listings d
            LEFT JOIN listings l ON l.listing_id = d.listing_id
            WHERE d.derivation_key IN ({placeholders})
            ORDER BY CASE d.derivation_key
              WHEN ? THEN 0
              ELSE 1
            END
            LIMIT 1
            """,
            (*derivation_keys, derivation_keys[0]),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    keys = [
        "listing_id",
        "site_id",
        "pool_id",
        "resource_id",
        "gpu_count",
        "status",
        "derivation_key",
        "listing_status",
    ]
    return dict(zip(keys, row))


def reopen_local_derived_listing(
    db_path: str,
    *,
    listing_id: str,
    site_id: str,
    gpu_count: int,
    offer_resource: dict[str, Any],
    accepted_escrows: list[dict[str, Any]],
    demands: list[dict[str, Any]],
    max_duration_seconds: int | None,
    storefront_url: str,
    seller_principal: Identity,
    resource_id: str | None,
    pool_id: str | None = None,
) -> None:
    now = "STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')"
    conn = sqlite3.connect(db_path)
    try:
        ensure_derived_compute_listings_table(conn)
        listing_cols = {
            row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()
        }
        updates = ["status = 'open'"]
        params: list[Any] = []
        if "paused" in listing_cols:
            updates.append("paused = 0")
        if "updated_at" in listing_cols:
            updates.append(f"updated_at = {now}")
        column_values = {
            "offer_resource": json.dumps(offer_resource),
            "accepted_escrows": json.dumps(accepted_escrows),
            "demands": json.dumps(demands),
            "max_duration_seconds": max_duration_seconds,
            "storefront_url": storefront_url,
            "seller_scheme": seller_principal.scheme.value,
            "seller_identifier": seller_principal.identifier,
        }
        for column, value in column_values.items():
            if column in listing_cols:
                updates.append(f"{column} = ?")
                params.append(value)
        params.append(listing_id)
        conn.execute(
            f"""
            UPDATE listings
            SET {", ".join(updates)}
            WHERE listing_id = ?
            """,
            tuple(params),
        )
        conn.execute(
            """
            INSERT INTO derived_compute_listings(
              listing_id, site_id, pool_id, resource_id, gpu_count, status, derivation_key, last_reconciled_at
            )
            VALUES (?, ?, ?, ?, ?, 'open', ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(derivation_key) DO UPDATE SET
              listing_id=excluded.listing_id,
              site_id=excluded.site_id,
              pool_id=excluded.pool_id,
              status='open',
              last_reconciled_at=excluded.last_reconciled_at
            """,
            (
                listing_id,
                site_id,
                pool_id or resource_id,
                resource_id or pool_id,
                int(gpu_count),
                listing_pool_key(site_id, pool_id, gpu_count)
                if pool_id and (resource_id is None or pool_id != resource_id)
                else listing_resource_key(site_id, str(resource_id or pool_id), gpu_count),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mark_derived_listings_closed(
    db_path: str, listing_ids: list[str], *, home_site: str, configured_site_count: int,
) -> None:
    """Mark listings closed, defensively backfilling a missing mapping row.

    The backfill INSERT below fires for a listing that reached this
    function with no prior `derived_compute_listings` row at all -- the
    normal case already has one from publish time. Such a listing's
    site is resolved the same way as everywhere else in this module: its
    own mapping if it has one; ``home_site`` only when exactly one site
    is currently configured (``configured_site_count == 1``); otherwise
    the backfill for that listing is skipped -- an ambiguous mapping is
    not written. The final status UPDATE below still runs for every
    listing_id regardless (it only touches rows that already exist).
    """
    if not listing_ids:
        return
    conn = sqlite3.connect(db_path)
    try:
        ensure_derived_compute_listings_table(conn)
        placeholders = ", ".join("?" for _ in listing_ids)
        rows = conn.execute(
            f"""
            SELECT l.listing_id, l.offer_resource, d.site_id
            FROM listings l
            LEFT JOIN derived_compute_listings d ON d.listing_id = l.listing_id
            WHERE l.listing_id IN ({placeholders})
            """,
            tuple(listing_ids),
        ).fetchall()
        for listing_id, raw_offer, mapped_site_id in rows:
            if not raw_offer:
                continue
            if mapped_site_id:
                site_id = str(mapped_site_id)
            elif configured_site_count == 1:
                site_id = home_site
            else:
                continue
            try:
                offer = json.loads(raw_offer)
            except json.JSONDecodeError:
                continue
            if not isinstance(offer, dict):
                continue
            pool_id = offer.get("pool_id")
            resource_id = offer.get("resource_id")
            if not pool_id and not resource_id:
                continue
            gpu_count = int(offer.get("gpu_count") or 1)
            key = (
                listing_pool_key(site_id, str(pool_id), gpu_count)
                if pool_id and (resource_id is None or str(pool_id) != str(resource_id))
                else listing_resource_key(site_id, str(resource_id), gpu_count)
            )
            conn.execute(
                """
                INSERT INTO derived_compute_listings(
                  listing_id, site_id, pool_id, resource_id, gpu_count, status, derivation_key,
                  last_reconciled_at
                )
                VALUES (?, ?, ?, ?, ?, 'closed', ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(derivation_key) DO UPDATE SET
                  listing_id=excluded.listing_id,
                  site_id=excluded.site_id,
                  pool_id=excluded.pool_id,
                  resource_id=excluded.resource_id,
                  gpu_count=excluded.gpu_count
                """,
                (
                    str(listing_id),
                    site_id,
                    str(pool_id or resource_id),
                    str(resource_id or pool_id),
                    gpu_count,
                    key,
                ),
            )
        conn.execute(
            f"""
            UPDATE derived_compute_listings
            SET status = 'closed',
                last_reconciled_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE listing_id IN ({placeholders})
            """,
            tuple(listing_ids),
        )
        conn.commit()
    finally:
        conn.close()


def mark_derived_listings_open(db_path: str, listing_ids: list[str]) -> None:
    if not listing_ids:
        return
    conn = sqlite3.connect(db_path)
    try:
        ensure_derived_compute_listings_table(conn)
        placeholders = ", ".join("?" for _ in listing_ids)
        conn.execute(
            f"""
            UPDATE derived_compute_listings
            SET status = 'open',
                last_reconciled_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
            WHERE listing_id IN ({placeholders})
            """,
            tuple(listing_ids),
        )
        conn.commit()
    finally:
        conn.close()
