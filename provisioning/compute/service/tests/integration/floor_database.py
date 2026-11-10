"""A database as the marketplace v0.3.0 release's migration command left it.

Built from the floor fixture's stored DDL, which that release's own
``compute-provisioning-migrate`` wrote, with every ID its chain recorded in its
ledger: the database an operator upgrading a v0.3.0 deployment holds. See
``tests/fixtures/v0_3_0_floor/README.md``.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

FLOOR = Path(__file__).resolve().parents[1] / "fixtures" / "v0_3_0_floor"


def floor_snapshot() -> dict[str, Any]:
    return json.loads((FLOOR / "schema.json").read_text(encoding="utf-8"))


def floor_ids() -> list[str]:
    return json.loads((FLOOR / "floor_ids.json").read_text(encoding="utf-8"))


def create_floor_database(path: Path) -> Path:
    """Write a v0.3.0 database at ``path``, holding no rows but its ledger's."""
    connection = sqlite3.connect(path)
    try:
        connection.executescript((FLOOR / "ddl.sql").read_text(encoding="utf-8"))
        with connection:
            connection.executemany(
                "INSERT INTO schema_migrations (id) VALUES (?)",
                [(migration_id,) for migration_id in floor_ids()],
            )
    finally:
        connection.close()
    return path
