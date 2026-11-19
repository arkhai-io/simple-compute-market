"""The migration command.

    compute-provisioning-migrate [--check]

Applies the service's migration chain to the configured database, which the
application refuses to start without (see
openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history).
It reads only where the database is and how to log: the migrations take the
connection alone. Used by:

  - The Helm init container (same image as the main Deployment container,
    different command) — ``Init:Error`` is an unambiguous signal in
    Kubernetes pod status that migration failed, distinct from an
    application crash.
  - Compose, which runs it before the application in the service's container.
  - ``make migrate`` for local development outside Docker.

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

from compute_provisioning_service.config import settings
from compute_provisioning_service.db.database import (
    check_database,
    create_db_engine,
    migrate_database,
)
from compute_provisioning_service.db.migrations import CHAIN

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
    logging.basicConfig(
        level=getattr(logging, str(settings.log_level).upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    engine = create_db_engine(settings.database_url, settings.is_sqlite)
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
        logger.info("Applying migrations to %s ...", settings.database_url)
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
