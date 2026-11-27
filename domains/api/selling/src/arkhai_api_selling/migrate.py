"""A storefront root's migration command over the family's chain.

    <storefront>-migrate [--check]

Applies the chain to the configured database, which the storefront refuses to
start without (see
openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history).
It reads only the database path and the log level, from layered settings the
root loads before any of them is resolved, so it runs without the storefront's
chains or identity: the migrations take the connection alone.

Rerunning it changes nothing: applied migrations are recorded in
``schema_migrations``. ``--check`` reports what a run would find — the
database's state and the migration IDs that differ — changes nothing, and
exits successfully only for a compatible database. Either form exits
unsuccessfully naming the reason when the database is refused or a migration
fails.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from market_schema_migrations import (
    Chain,
    MigrationFailed,
    MigrationRefused,
    describe,
    refusal_message,
)

from arkhai_api_selling.migrations import (
    check_storefront_database,
    migrate_storefront_database,
)

logger = logging.getLogger(__name__)


class MigrationSettings(Protocol):
    """The layered settings the command reads ``db_path`` and ``log_level`` from."""

    def get(self, key: str, default: Any = None) -> Any: ...


def _parse(
    chain: Chain[sqlite3.Connection], argv: Sequence[str] | None
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=chain.command,
        description=f"Apply {chain.service}'s migration chain to its database.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report the database's state and the migrations that differ; change nothing",
    )
    return parser.parse_args(argv)


def main(
    chain: Chain[sqlite3.Connection],
    load_settings: Callable[[], MigrationSettings],
    argv: Sequence[str] | None = None,
) -> None:
    arguments = _parse(chain, argv)
    source = load_settings()
    db_path = str(source.get("db_path") or "")
    if not db_path:
        print(f"{chain.service}'s configuration names no db_path.", file=sys.stderr)
        raise SystemExit(1)
    logging.basicConfig(
        level=getattr(logging, str(source.get("log_level", "INFO")).upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    if arguments.check:
        result = check_storefront_database(chain, db_path)
        print(f"{chain.service}: {describe(result)}")
        if not result.compatible:
            print(
                refusal_message(result, service=chain.service, command=chain.command),
                file=sys.stderr,
            )
            raise SystemExit(1)
        return
    logger.info("Applying migrations to %s ...", db_path)
    try:
        report = migrate_storefront_database(chain, db_path)
    except (MigrationRefused, MigrationFailed) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    logger.info(
        "Migrations applied successfully (%s).",
        ", ".join(report.applied) if report.applied else "none pending",
    )
