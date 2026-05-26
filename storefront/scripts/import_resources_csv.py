#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path


# Best-effort: add the repo root to sys.path so imports resolve when
# the script is run from a host checkout. Inside the container the
# market_storefront wheel is already on the venv path, so this is a
# no-op — and the path math overflows (the script lives at /app/scripts/),
# so we tolerate the out-of-range index.
try:
    repo_root = Path(__file__).resolve().parents[3]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
except IndexError:
    pass

from market_storefront.utils.sqlite_client import SQLiteClient


def _load_env_file(env_file: str | None) -> None:
    if not env_file:
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(env_file)
    except Exception:
        return


def _resolve_db_path(cli_db_path: str | None) -> str:
    if cli_db_path:
        return cli_db_path
    env_path = os.getenv("STOREFRONT_DB_PATH")
    if env_path:
        return env_path
    # Fall back to the same path the server reads — ensures the CSV importer
    # and the running storefront always write/read the same database when no
    # explicit path is supplied.
    from market_storefront.utils.config import settings
    return settings.db_path


async def _run(csv_path: str, db_path: str, dry_run: bool) -> int:
    client = SQLiteClient(db_path=db_path)
    report = await client.upsert_resources_from_csv(csv_path=csv_path, dry_run=dry_run)

    summary = {
        "csv_path": report.get("csv_path"),
        "dry_run": report.get("dry_run"),
        "total_rows": report.get("total_rows"),
        "imported_count": report.get("imported_count"),
        "failed_count": report.get("failed_count"),
        "matched_count": report.get("matched_count"),
        "unrecognized_count": report.get("unrecognized_count"),
        "invalid_count": report.get("invalid_count"),
    }
    print(json.dumps(summary, indent=2))

    if report.get("failed_count", 0) > 0:
        print("\nRow errors:")
        for row in report.get("rows", []):
            errors = row.get("errors") or []
            if errors:
                rid = row.get("resource_id") or "-"
                print(f"- row={row.get('row_number')} resource_id={rid}: {errors[0]}")
        return 1
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Import resource portfolio rows from CSV into the storefront DB.")
    parser.add_argument("--csv", required=True, help="Path to CSV file.")
    parser.add_argument("--db-path", default=None, help="Path to storefront SQLite DB. Defaults to STOREFRONT_DB_PATH or /tmp/agent.db.")
    parser.add_argument("--env-file", default=".env", help="Optional env file to load before resolving STOREFRONT_DB_PATH.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing to DB.")
    args = parser.parse_args()

    _load_env_file(args.env_file)
    db_path = _resolve_db_path(args.db_path)
    return asyncio.run(_run(args.csv, db_path, args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
