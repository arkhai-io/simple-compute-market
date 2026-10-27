"""The storefront's schema baseline; the fixture is written once with ``--write``."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from apicredits_storefront.container import storefront_sqlite_client

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "baseline" / "schema.json"


def describe_schema(conn: sqlite3.Connection) -> dict[str, Any]:
    ddl = {
        (str(row[0]), str(row[1])): row[2]
        for row in conn.execute("SELECT type, name, sql FROM sqlite_master")
    }
    tables = sorted(name for kind, name in ddl if kind == "table" and not name.startswith("sqlite_"))
    triggers: dict[str, list[dict[str, Any]]] = {}
    for name, table, sql in conn.execute(
        "SELECT name, tbl_name, sql FROM sqlite_master WHERE type = 'trigger' ORDER BY name"
    ):
        triggers.setdefault(str(table), []).append({"name": str(name), "sql": sql})
    described: dict[str, Any] = {}
    for table in tables:
        columns = [
            {
                "name": row[1],
                "type": row[2],
                "not_null": bool(row[3]),
                "default": row[4],
                "primary_key": row[5],
            }
            for row in conn.execute(f"PRAGMA table_info({table})")
        ]
        indexes = []
        for index in conn.execute(f"PRAGMA index_list({table})"):
            name, unique, origin = index[1], bool(index[2]), index[3]
            indexes.append(
                {
                    "name": name,
                    "unique": unique,
                    "origin": origin,
                    "columns": [row[2] for row in conn.execute(f"PRAGMA index_info({name})")],
                    "sql": ddl.get(("index", name)),
                }
            )
        foreign_keys = [
            {"from": row[3], "table": row[2], "to": row[4]}
            for row in conn.execute(f"PRAGMA foreign_key_list({table})")
        ]
        described[table] = {
            "sql": ddl[("table", table)],
            "columns": columns,
            "indexes": sorted(indexes, key=lambda i: i["name"]),
            "foreign_keys": sorted(foreign_keys, key=lambda f: (f["from"], f["table"])),
            "triggers": triggers.get(table, []),
        }
    migrations = [
        str(row[0]) for row in conn.execute("SELECT id FROM schema_migrations ORDER BY rowid")
    ]
    return {"tables": described, "migrations": migrations}


def fresh_schema(directory: Path) -> dict[str, Any]:
    db = storefront_sqlite_client(db_path=str(directory / "baseline.db"))
    conn = sqlite3.connect(db.db_path)
    try:
        return describe_schema(conn)
    finally:
        conn.close()


def test_the_schema_baseline_diffs_to_zero(tmp_path: Path) -> None:
    if not FIXTURE.exists():
        raise AssertionError(
            f"{FIXTURE} is missing; it is written once by "
            "`python -m tests.integration.test_schema_baseline --write`"
        )
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = fresh_schema(tmp_path)
    assert actual["migrations"] == expected["migrations"]
    assert sorted(actual["tables"]) == sorted(expected["tables"])
    for table in expected["tables"]:
        assert actual["tables"][table] == expected["tables"][table], table


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write the fixture; refuses to overwrite")
    args = parser.parse_args(argv)
    if not args.write:
        parser.error("nothing to do without --write")
    if FIXTURE.exists():
        print(f"{FIXTURE} exists and is never rewritten", file=sys.stderr)
        return 1
    with TemporaryDirectory() as directory:
        schema = fresh_schema(Path(directory))
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {FIXTURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
