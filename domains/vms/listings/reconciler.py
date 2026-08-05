from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Mapping


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


def _projected_pool_row(
    pool: Mapping[str, Any],
    *,
    site_id: str,
    home_site: str,
    local_pricing: Mapping[str, sqlite3.Row],
    member_availability: dict[tuple[str | None, str], int] | None,
) -> dict[str, Any] | None:
    """Build one pool_rows entry from one projected pool, or None if it
    has no pool_id or (site_id != home_site, or no matching local row)
    no pricing -- see `_local_pool_pricing`.
    """
    pool_id = str(pool.get("resource_pool_id") or "").strip()
    if not pool_id:
        return None
    pricing = local_pricing.get(pool_id) if site_id == home_site else None
    if pricing is None:
        return None

    total_gpu_count = 0
    available_gpu_count = 0
    max_member_available = 0
    member_count = 0
    single_resource_id: str | None = None
    gpu_model: str | None = None
    for resource in pool.get("resources") or []:
        if not resource.get("enabled", True):
            continue
        usage = _projected_resource_usage(
            resource, site_id=site_id, member_availability=member_availability,
        )
        if usage is None:
            continue
        if gpu_model is None and usage.gpu_model:
            gpu_model = usage.gpu_model
        total_gpu_count += usage.total
        available_gpu_count += usage.available
        max_member_available = max(max_member_available, usage.available)
        member_count += 1
        single_resource_id = usage.resource_id if member_count == 1 else None

    return {
        "site_id": site_id,
        "pool_id": pool_id,
        "gpu_model": gpu_model or pricing["gpu_model"],
        "region": pricing["region"],
        "sla": pricing["sla"] if pricing["sla"] is not None else 0.0,
        "total_gpu_count": total_gpu_count,
        "available_gpu_count": available_gpu_count,
        "max_member_available_gpu_count": max_member_available,
        "min_price": pricing["min_price"],
        "token": pricing["token"],
        "accepted_escrows": pricing["accepted_escrows"],
        "max_duration_seconds": pricing["max_duration_seconds"],
        "single_resource_id": single_resource_id,
        "member_count": member_count,
    }


def _pool_rows_from_projection(
    conn: sqlite3.Connection,
    site_pool_projection: Mapping[str, list[dict[str, Any]]],
    *,
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None,
) -> list[dict[str, Any]]:
    """Build pool_rows from a site_resource_pools projection.

    Structure (which pools/resources exist, GPU model) comes from the
    projection, for every site present in it. Pricing/region/sla do not
    exist in the projection at all (the provisioning service doesn't
    track them) and are only ever looked up locally for home_site's own
    pools -- see `_local_pool_pricing`. A non-home_site pool, or a
    home_site pool with no local pricing row, is skipped entirely: no
    price means no listing, matching the "priceless" handling other
    publish flows already support rather than inventing a new one.
    """
    local_pricing = _local_pool_pricing(conn)
    pool_rows: list[dict[str, Any]] = []
    for site_id, pools in site_pool_projection.items():
        for pool in pools:
            row = _projected_pool_row(
                pool, site_id=site_id, home_site=home_site,
                local_pricing=local_pricing, member_availability=member_availability,
            )
            if row is not None:
                pool_rows.append(row)
    return pool_rows

def available_compute_slices(
    db_path: str,
    *,
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]] | None = None,
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
    ``home_site`` -- but pricing, ``region``, and ``sla`` are only ever
    looked up from the local ``compute_capacity_pools`` table for
    ``home_site``'s own pools. A non-``home_site`` pool has no pricing
    source yet (no cross-site lookup is attempted, so no cross-site
    ``pool_id`` collision is possible by construction) and is filtered
    out rather than published without a price -- matching the existing
    "priceless" handling other publish flows already support, not a new
    failure mode.
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        if site_pool_projection:
            pool_rows = _pool_rows_from_projection(
                conn, site_pool_projection,
                home_site=home_site, member_availability=member_availability,
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
            })
    return out


def current_available_resource_keys(
    db_path: str,
    *,
    home_site: str,
    member_availability: dict[tuple[str | None, str], int] | None = None,
    site_pool_projection: Mapping[str, list[dict[str, Any]]] | None = None,
) -> set[str]:
    keys: set[str] = set()
    for row in available_compute_slices(
        db_path, home_site=home_site, member_availability=member_availability,
        site_pool_projection=site_pool_projection,
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
) -> list[str]:
    """Closed derived listing IDs whose requested slice fits capacity again."""
    available_keys = current_available_resource_keys(
        db_path, home_site=home_site, member_availability=member_availability,
        site_pool_projection=site_pool_projection,
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
    use_pool_key = bool(pool_id and (resource_id is None or pool_id != resource_id))
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
    seller: str,
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
            "seller": seller,
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
