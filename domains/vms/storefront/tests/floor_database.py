"""A database as the marketplace v0.3.0 release's VM storefront left it.

Built from the floor fixture's stored DDL, which that release's own database
client wrote, with every ID its chain recorded in its ledger: the database an
operator upgrading a v0.3.0 storefront holds, before any store opened. See
``tests/fixtures/v0_3_0_floor/README.md``. The upgraded fixture beside it is a
database an earlier release built and v0.3.0 then ran on, built the same way
(``tests/fixtures/v0_3_0_floor/upgraded/README.md``).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

FLOOR = Path(__file__).resolve().parent / "fixtures" / "v0_3_0_floor"
UPGRADED = FLOOR / "upgraded"

# SQLite records the sequence table it creates for an AUTOINCREMENT key among
# the stored DDL, but refuses to create it by name; the first such table
# creates it again.
_SEQUENCE_TABLE = "CREATE TABLE sqlite_sequence(name,seq);"


def floor_snapshot() -> dict[str, Any]:
    return json.loads((FLOOR / "schema.json").read_text(encoding="utf-8"))


def floor_ids() -> list[str]:
    return json.loads((FLOOR / "floor_ids.json").read_text(encoding="utf-8"))


def upgraded_recorded_ids() -> list[str]:
    return json.loads((UPGRADED / "recorded_ids.json").read_text(encoding="utf-8"))


def _build(path: str | Path, ddl: Path, recorded: Sequence[str]) -> Path:
    """Run a fixture's stored DDL on a new file at ``path`` and record ``recorded``."""
    statements = ddl.read_text(encoding="utf-8").replace(_SEQUENCE_TABLE, "")
    connection = sqlite3.connect(path)
    try:
        connection.executescript(statements)
        with connection:
            connection.executemany(
                "INSERT INTO schema_migrations (id) VALUES (?)",
                [(migration_id,) for migration_id in recorded],
            )
    finally:
        connection.close()
    return Path(path)


def create_upgraded_database(path: str | Path) -> Path:
    """Write the upgraded database at ``path``, holding no rows but its ledger's."""
    return _build(path, UPGRADED / "ddl.sql", upgraded_recorded_ids())


def create_floor_database(path: str | Path, *, earlier_records: Sequence[str] = ()) -> Path:
    """Write a v0.3.0 database at ``path``, holding no rows but its ledger's.

    ``earlier_records`` are IDs recorded beside the floor's, as a release
    before v0.3.0 left them on a database v0.3.0 then ran on.
    """
    return _build(path, FLOOR / "ddl.sql", (*floor_ids(), *earlier_records))
