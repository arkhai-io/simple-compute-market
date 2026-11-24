"""The migration command.

    apicredits-service-migrate [--check]

Applies the service's migration chain to the configured database, which the
application refuses to start without (see
openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history).
It reads only where the database is and how to log, from the layered settings
before the application's secrets are resolved, so it runs without them
mounted; the migrations take the connection alone. Compose runs it before the application in the service's
container, and ``make migrate`` runs it for local development outside Docker.

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
from collections.abc import Sequence

from market_schema_migrations import (
    MigrationFailed,
    MigrationRefused,
    describe,
    refusal_message,
)

from apicredits_service.db.database import (
    check_database,
    create_db_engine,
    migrate_database,
)
from apicredits_service.db.migrations import CHAIN
from apicredits_service.settings_source import load_settings_source

logger = logging.getLogger(__name__)


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=CHAIN.command,
        description=f"Apply {CHAIN.service}'s migration chain to its database.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report the database's state and the migrations that differ; change nothing",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = _parse(argv)
    source = load_settings_source()
    database_url = str(source.database_url)
    logging.basicConfig(
        level=getattr(logging, str(source.log_level).upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    engine = create_db_engine(database_url, database_url.startswith("sqlite"))
    try:
        if arguments.check:
            result = check_database(engine)
            print(f"{CHAIN.service}: {describe(result)}")
            if not result.compatible:
                print(
                    refusal_message(result, service=CHAIN.service, command=CHAIN.command),
                    file=sys.stderr,
                )
                raise SystemExit(1)
            return
        logger.info("Applying migrations to %s ...", database_url)
        try:
            report = migrate_database(engine)
        except (MigrationRefused, MigrationFailed) as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(1) from exc
        logger.info(
            "Migrations applied successfully (%s).",
            ", ".join(report.applied) if report.applied else "none pending",
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
