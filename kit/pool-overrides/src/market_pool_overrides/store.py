"""The durable pool override store, its migrations, and its reader.

One row per override, keyed by site, pool, and offering mode. Pool identifiers
are site-local, so a key without the site could apply one site's terms to
another site's identically named pool, and a pool sold in several modes carries
an independent override per mode.

The table and its encoding are this kit's own. A market's listing derivation
loads its mode's overrides through ``read_pool_overrides``, over the connection
it already holds, inside the derivation every structural-key reader runs, so
publication and reconciliation always resolve the same shapes.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from market_pool_overrides.records import PoolOverrideAddress, PoolOverrideRecord

POOL_OVERRIDES_TABLE = "pool_overrides"
POOL_OVERRIDES_MIGRATION_ID = "20260925_001_pool_overrides"

_ADDRESS = ("site_id", "pool_id", "offering_mode")
_JSON_COLUMNS = ("listing_shapes", "settlements", "terms")
_COLUMNS = (*_ADDRESS, *_JSON_COLUMNS, "created_at", "updated_at")


@dataclass(frozen=True)
class PoolOverrideMigration:
    """One migration, in the shape a storefront's migration runner applies."""

    id: str
    apply: Callable[[sqlite3.Connection], None]


def _create_pool_overrides(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {POOL_OVERRIDES_TABLE} (
          site_id TEXT NOT NULL,
          pool_id TEXT NOT NULL,
          offering_mode TEXT NOT NULL,
          listing_shapes TEXT,
          settlements TEXT,
          terms TEXT,
          created_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          updated_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')),
          PRIMARY KEY (site_id, pool_id, offering_mode)
        )
        """
    )


def pool_override_migrations() -> tuple[PoolOverrideMigration, ...]:
    """The store's migrations, for a storefront to compose into its own chain."""
    return (PoolOverrideMigration(POOL_OVERRIDES_MIGRATION_ID, _create_pool_overrides),)


@dataclass(frozen=True)
class StoredPoolOverride:
    """One stored override as a market's derivation reads it.

    ``listing_shapes``, ``settlements``, and ``terms`` are decoded, or ``None``
    where the override states nothing. A field whose stored value cannot be
    decoded is kept as its raw text and named in ``problems``: an unreadable
    override is not an absent one, so a reader holds what it governs rather than
    falling through to a lower tier.
    """

    site_id: str
    pool_id: str
    offering_mode: str
    listing_shapes: Any = None
    settlements: Any = None
    terms: Any = None
    problems: tuple[str, ...] = field(default=())


def read_pool_overrides(
    conn: sqlite3.Connection, *, offering_mode: str
) -> list[StoredPoolOverride]:
    """Every stored override for ``offering_mode``, over the caller's connection.

    Synchronous, because derivation reads inside its own read-only connection. A
    database the store's migration has not reached holds no overrides.
    """
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (POOL_OVERRIDES_TABLE,),
    ).fetchone()
    if exists is None:
        return []
    overrides: list[StoredPoolOverride] = []
    for row in conn.execute(
        f"SELECT site_id, pool_id, {', '.join(_JSON_COLUMNS)} FROM {POOL_OVERRIDES_TABLE} "
        "WHERE offering_mode = ? ORDER BY site_id, pool_id",
        (offering_mode,),
    ).fetchall():
        site_id, pool_id, *raw_values = tuple(row)
        values: dict[str, Any] = {}
        problems: list[str] = []
        for column, raw in zip(_JSON_COLUMNS, raw_values):
            if raw is None:
                values[column] = None
                continue
            try:
                values[column] = json.loads(raw)
            except (TypeError, ValueError):
                values[column] = raw
                problems.append(f"{column}: the stored value is not JSON")
        overrides.append(
            StoredPoolOverride(
                site_id=str(site_id),
                pool_id=str(pool_id),
                offering_mode=offering_mode,
                problems=tuple(problems),
                **values,
            )
        )
    return overrides


def _row(row: tuple[Any, ...]) -> dict[str, Any]:
    record = dict(zip(_COLUMNS, row))
    for column in _JSON_COLUMNS:
        if record[column] is not None:
            record[column] = json.loads(record[column])
    return record


class SQLitePoolOverrideStore:
    """The store over one storefront database. Every method is async; each call
    opens its own connection, as the storefront's other repositories do."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    def _select(self, where: str = "", params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        try:
            rows = conn.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM {POOL_OVERRIDES_TABLE} {where} "
                "ORDER BY site_id, pool_id, offering_mode",
                params,
            ).fetchall()
        finally:
            conn.close()
        return [_row(row) for row in rows]

    async def replace(self, record: PoolOverrideRecord) -> dict[str, Any]:
        """Store ``record`` as the whole override at its address.

        Every field the record leaves unset is cleared, so a replacement keeps
        nothing from the record it replaces except ``created_at``.
        """
        values: dict[str, Any] = {name: getattr(record, name) for name in _ADDRESS}
        for column in _JSON_COLUMNS:
            value = getattr(record, column)
            values[column] = None if value is None else json.dumps(value, sort_keys=True)

        def _save() -> dict[str, Any]:
            columns = list(values)
            updates = ", ".join(f"{column} = excluded.{column}" for column in _JSON_COLUMNS)
            conn = sqlite3.connect(self.db_path)
            try:
                with conn:
                    conn.execute(
                        f"INSERT INTO {POOL_OVERRIDES_TABLE} ({', '.join(columns)}) "
                        f"VALUES ({', '.join('?' for _ in columns)}) "
                        "ON CONFLICT(site_id, pool_id, offering_mode) DO UPDATE SET "
                        f"{updates}, updated_at = STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')",
                        [values[column] for column in columns],
                    )
            finally:
                conn.close()
            (stored,) = self._select(
                "WHERE site_id = ? AND pool_id = ? AND offering_mode = ?",
                tuple(values[name] for name in _ADDRESS),
            )
            return stored

        return await asyncio.to_thread(_save)

    async def get(self, address: PoolOverrideAddress) -> dict[str, Any] | None:
        rows = await asyncio.to_thread(
            self._select,
            "WHERE site_id = ? AND pool_id = ? AND offering_mode = ?",
            (address.site_id, address.pool_id, address.offering_mode),
        )
        return rows[0] if rows else None

    async def list(
        self, *, site_id: str | None = None, pool_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Every override, or one site's, or one site pool's across its modes."""
        clauses, params = [], []
        for column, value in (("site_id", site_id), ("pool_id", pool_id)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return await asyncio.to_thread(self._select, where, tuple(params))

    async def delete(self, address: PoolOverrideAddress) -> bool:
        """Remove one override; return whether it existed. Idempotent."""

        def _delete() -> bool:
            conn = sqlite3.connect(self.db_path)
            try:
                with conn:
                    cursor = conn.execute(
                        f"DELETE FROM {POOL_OVERRIDES_TABLE} "
                        "WHERE site_id = ? AND pool_id = ? AND offering_mode = ?",
                        (address.site_id, address.pool_id, address.offering_mode),
                    )
            finally:
                conn.close()
            return cursor.rowcount > 0

        return await asyncio.to_thread(_delete)


__all__ = [
    "POOL_OVERRIDES_MIGRATION_ID",
    "POOL_OVERRIDES_TABLE",
    "PoolOverrideMigration",
    "SQLitePoolOverrideStore",
    "StoredPoolOverride",
    "pool_override_migrations",
    "read_pool_overrides",
]
