"""A service root's migration command over the authority's chain.

    <service>-migrate [--check]

Applies the chain to the configured database, which the application refuses to
start without (see
openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history).
It reads only where the database is and how to log, from settings the root
loads without resolving the application's secrets, so it runs without them
mounted; the migrations take the connection alone.

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
from sqlalchemy import Connection

from arkhai_api_authority.database import (
    check_database,
    create_db_engine,
    migrate_database,
)

logger = logging.getLogger(__name__)


class MigrationSettings(Protocol):
    """The two settings the command reads."""

    database_url: Any
    log_level: Any


def _parse(chain: Chain[Connection], argv: Sequence[str] | None) -> argparse.Namespace:
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
    chain: Chain[Connection],
    load_settings: Callable[[], MigrationSettings],
    argv: Sequence[str] | None = None,
) -> None:
    arguments = _parse(chain, argv)
    source = load_settings()
    database_url = str(source.database_url)
    logging.basicConfig(
        level=getattr(logging, str(source.log_level).upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    engine = create_db_engine(database_url, database_url.startswith("sqlite"))
    try:
        if arguments.check:
            result = check_database(engine, chain)
            print(f"{chain.service}: {describe(result)}")
            if not result.compatible:
                print(
                    refusal_message(result, service=chain.service, command=chain.command),
                    file=sys.stderr,
                )
                raise SystemExit(1)
            return
        logger.info("Applying migrations to %s ...", database_url)
        try:
            report = migrate_database(engine, chain)
        except (MigrationRefused, MigrationFailed) as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        logger.info(
            "Migrations applied successfully (%s).",
            ", ".join(report.applied) if report.applied else "none pending",
        )
    finally:
        engine.dispose()
