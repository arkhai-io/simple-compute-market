from __future__ import annotations

import json
import sqlite3
from typing import Any


HELD_ALLOCATION_STATES = {
    "reserved",
    "provisioning",
    "leased",
    "releasing",
    "held",
}


def listing_resource_key(resource_id: str, gpu_count: int | str | None) -> str:
    return f"{resource_id}:gpus:{int(gpu_count or 1)}"


def listing_pool_key(pool_id: str, gpu_count: int | str | None) -> str:
    return f"pool:{pool_id}:gpus:{int(gpu_count or 1)}"


def ensure_derived_compute_listings_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS derived_compute_listings (
          listing_id TEXT PRIMARY KEY,
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


def available_compute_slices(
    db_path: str,
    *,
    held_by_resource: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Return publishable compute listing slices from current storefront state.

    ``held_by_resource`` overrides the locally computed held counts — in
    remote-capacity mode the holds ledger lives in the site authority, so
    the caller supplies consumption from a site snapshot while totals and
    market attributes stay local (the aggregator view).
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        has_pools = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_inventory_pools'"
        ).fetchone() is not None
        has_members = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='compute_pool_members'"
        ).fetchone() is not None
        if held_by_resource is None:
            held_by_resource = held_gpu_counts_by_resource(conn)
        if has_pools and has_members:
            rows = conn.execute(
                """
                SELECT p.pool_id, p.gpu_model, p.region, p.sla,
                       p.total_gpu_count, p.min_price, p.token,
                       p.accepted_escrows, p.max_duration_seconds,
                       m.resource_id, m.gpu_count, m.status, m.attributes
                FROM compute_inventory_pools p
                JOIN compute_pool_members m ON m.pool_id = p.pool_id
                WHERE p.resource_type = 'compute.gpu'
                  AND p.status = 'active'
                  AND m.status = 'active'
                ORDER BY p.pool_id, m.resource_id
                """
            ).fetchall()
            by_pool: dict[str, dict[str, Any]] = {}
            for row in rows:
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
                member_total = int(row["gpu_count"] or 0)
                member_available = max(
                    0,
                    member_total - held_by_resource.get(str(row["resource_id"]), 0),
                )
                pool["total_gpu_count"] += member_total
                pool["available_gpu_count"] += member_available
                pool["max_member_available_gpu_count"] = max(
                    int(pool["max_member_available_gpu_count"]),
                    member_available,
                )
                pool["member_count"] += 1
                pool["single_resource_id"] = (
                    str(row["resource_id"])
                    if pool["member_count"] == 1
                    else None
                )
            pool_rows = list(by_pool.values())
        else:
            cols = {r[1] for r in conn.execute("PRAGMA table_info(resources)").fetchall()}
            has_accepted = "accepted_escrows" in cols
            has_max_duration = "max_duration_seconds" in cols
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
            pool_rows = []
            for row in rows:
                try:
                    attrs = json.loads(row["attributes"] or "{}")
                except json.JSONDecodeError:
                    attrs = {}
                total_gpu_count = int(row["value"]) if row["value"] is not None else 1
                available_gpu_count = max(
                    0,
                    total_gpu_count - held_by_resource.get(str(row["resource_id"]), 0),
                )
                pool_rows.append({
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
                })
    finally:
        conn.close()

    out: list[dict[str, Any]] = []
    for row in pool_rows:
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
                "pool_id": pool_id,
                "resource_id": single_resource_id,
                "resource_key": (
                    listing_pool_key(pool_id, gpu_count)
                    if is_fungible_pool
                    else listing_resource_key(str(single_resource_id), gpu_count)
                ),
                "legacy_resource_key": (
                    listing_resource_key(single_resource_id, gpu_count)
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
    held_by_resource: dict[str, int] | None = None,
) -> set[str]:
    keys: set[str] = set()
    for row in available_compute_slices(db_path, held_by_resource=held_by_resource):
        if row.get("resource_key"):
            keys.add(str(row["resource_key"]))
        if row.get("legacy_resource_key"):
            keys.add(str(row["legacy_resource_key"]))
    return keys


def open_listing_resource_keys(db_path: str) -> set[str]:
    """Return ``resource_id:gpus:N`` keys already covered by open listings."""
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT offer_resource FROM listings WHERE status = 'open'",
        ).fetchall()
    finally:
        conn.close()

    covered: set[str] = set()
    for (raw,) in rows:
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        pool_id = parsed.get("pool_id")
        if pool_id:
            covered.add(listing_pool_key(str(pool_id), parsed.get("gpu_count")))
            continue
        rid = parsed.get("resource_id")
        if rid:
            covered.add(listing_resource_key(str(rid), parsed.get("gpu_count")))
    return covered


def stale_open_listing_ids(
    db_path: str,
    *,
    held_by_resource: dict[str, int] | None = None,
) -> list[str]:
    """Open listing IDs whose requested slice no longer fits capacity."""
    available_keys = current_available_resource_keys(
        db_path, held_by_resource=held_by_resource,
    )
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&nolock=1", uri=True, timeout=5)
    try:
        rows = conn.execute(
            "SELECT listing_id, offer_resource FROM listings WHERE status = 'open'",
        ).fetchall()
    finally:
        conn.close()

    stale: list[str] = []
    for listing_id, raw in rows:
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(parsed, dict):
            continue
        pool_id = parsed.get("pool_id")
        if pool_id:
            key = listing_pool_key(str(pool_id), parsed.get("gpu_count"))
            if key not in available_keys:
                stale.append(str(listing_id))
            continue
        rid = parsed.get("resource_id")
        if not rid:
            continue
        if listing_resource_key(str(rid), parsed.get("gpu_count")) not in available_keys:
            stale.append(str(listing_id))
    return stale


def closed_available_listing_ids(
    db_path: str,
    *,
    held_by_resource: dict[str, int] | None = None,
) -> list[str]:
    """Closed derived listing IDs whose requested slice fits capacity again."""
    available_keys = current_available_resource_keys(
        db_path, held_by_resource=held_by_resource,
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
        listing_pool_key(resolved_pool_id, gpu_count)
        if use_pool_key
        else listing_resource_key(str(resource_id or resolved_pool_id), gpu_count)
    )
    conn = sqlite3.connect(db_path)
    try:
        ensure_derived_compute_listings_table(conn)
        conn.execute(
            """
            INSERT INTO derived_compute_listings(
              listing_id, pool_id, resource_id, gpu_count, status, derivation_key, last_reconciled_at
            )
            VALUES (?, ?, ?, ?, ?, ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(derivation_key) DO UPDATE SET
              listing_id=excluded.listing_id,
              pool_id=excluded.pool_id,
              resource_id=excluded.resource_id,
              gpu_count=excluded.gpu_count,
              status=excluded.status,
              last_reconciled_at=excluded.last_reconciled_at
            """,
            (
                listing_id,
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
    gpu_count: int,
    resource_id: str | None = None,
    pool_id: str | None = None,
) -> dict[str, Any] | None:
    derivation_keys: list[str] = []
    if pool_id:
        derivation_keys.append(listing_pool_key(pool_id, gpu_count))
    if resource_id:
        derivation_keys.append(listing_resource_key(resource_id, gpu_count))
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
        placeholders = ", ".join("?" for _ in derivation_keys)
        row = conn.execute(
            f"""
            SELECT d.listing_id, {pool_select}, d.resource_id, d.gpu_count, d.status,
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
              listing_id, pool_id, resource_id, gpu_count, status, derivation_key, last_reconciled_at
            )
            VALUES (?, ?, ?, ?, 'open', ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
            ON CONFLICT(derivation_key) DO UPDATE SET
              listing_id=excluded.listing_id,
              pool_id=excluded.pool_id,
              status='open',
              last_reconciled_at=excluded.last_reconciled_at
            """,
            (
                listing_id,
                pool_id or resource_id,
                resource_id or pool_id,
                int(gpu_count),
                listing_pool_key(pool_id, gpu_count)
                if pool_id and (resource_id is None or pool_id != resource_id)
                else listing_resource_key(str(resource_id or pool_id), gpu_count),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mark_derived_listings_closed(db_path: str, listing_ids: list[str]) -> None:
    if not listing_ids:
        return
    conn = sqlite3.connect(db_path)
    try:
        ensure_derived_compute_listings_table(conn)
        placeholders = ", ".join("?" for _ in listing_ids)
        rows = conn.execute(
            f"""
            SELECT listing_id, offer_resource
            FROM listings
            WHERE listing_id IN ({placeholders})
            """,
            tuple(listing_ids),
        ).fetchall()
        for listing_id, raw_offer in rows:
            if not raw_offer:
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
                listing_pool_key(str(pool_id), gpu_count)
                if pool_id and (resource_id is None or str(pool_id) != str(resource_id))
                else listing_resource_key(str(resource_id), gpu_count)
            )
            conn.execute(
                """
                INSERT INTO derived_compute_listings(
                  listing_id, pool_id, resource_id, gpu_count, status, derivation_key,
                  last_reconciled_at
                )
                VALUES (?, ?, ?, ?, 'closed', ?, STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(derivation_key) DO UPDATE SET
                  listing_id=excluded.listing_id,
                  pool_id=excluded.pool_id,
                  resource_id=excluded.resource_id,
                  gpu_count=excluded.gpu_count
                """,
                (
                    str(listing_id),
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
