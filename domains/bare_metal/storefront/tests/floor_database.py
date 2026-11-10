"""A database as the marketplace v0.3.0 release's bare-metal storefront left it.

Built from the floor fixture's stored DDL, which that release's own database
client wrote, with every ID its chain recorded in its ledger: the database an
operator upgrading a v0.3.0 storefront holds, before any store opened. See
``tests/fixtures/v0_3_0_floor/README.md``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

FLOOR = Path(__file__).resolve().parent / "fixtures" / "v0_3_0_floor"

# SQLite records the sequence table it creates for an AUTOINCREMENT key among
# the stored DDL, but refuses to create it by name; the first such table
# creates it again.
_SEQUENCE_TABLE = "CREATE TABLE sqlite_sequence(name,seq);"


def floor_snapshot() -> dict[str, Any]:
    return json.loads((FLOOR / "schema.json").read_text(encoding="utf-8"))


def floor_ids() -> list[str]:
    return json.loads((FLOOR / "floor_ids.json").read_text(encoding="utf-8"))


def create_floor_database(path: str | Path) -> Path:
    """Write a v0.3.0 database at ``path``, holding no rows but its ledger's."""
    ddl = (FLOOR / "ddl.sql").read_text(encoding="utf-8").replace(_SEQUENCE_TABLE, "")
    connection = sqlite3.connect(path)
    try:
        connection.executescript(ddl)
        with connection:
            connection.executemany(
                "INSERT INTO schema_migrations (id) VALUES (?)",
                [(migration_id,) for migration_id in floor_ids()],
            )
    finally:
        connection.close()
    return Path(path)
