"""The migration command.

    registry-migrate [--check]

Adopts a v0.3.0 database and upgrades the registry's database to its Alembic
script head, which the application refuses to start without (see
openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history).
It reads only the database URL and the log level from the registry's settings
files (``core_registry.settings_source``), so it runs with no credential file
and no other setting. Used by:

  - The Helm init container, from the application's image with its
    configuration and data volume.
  - Compose, which runs it before the application in the registry's container.
  - ``make migrate`` for local development.

Rerunning it changes nothing. ``--check`` reports what a run would find -- the
database's state and the revisions that differ -- changes nothing, and exits
successfully only for a compatible database. Either form exits unsuccessfully
naming the reason when the database is refused or the upgrade fails.
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
from sqlalchemy.engine import make_url

from core_registry.db.migrations import (
    COMMAND,
    SERVICE,
    check_database,
    migrate_database,
)
from core_registry.settings_source import load_database_settings

logger = logging.getLogger(__name__)


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=COMMAND,
        description=f"Apply {SERVICE}'s migrations to its database.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report the database's state and the revisions that differ; change nothing",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    arguments = _parse(argv)
    settings = load_database_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    if arguments.check:
        result = check_database(settings.database_url)
        print(f"{SERVICE}: {describe(result)}")
        if not result.compatible:
            print(
                refusal_message(result, service=SERVICE, command=COMMAND),
                file=sys.stderr,
            )
            raise SystemExit(1)
        return
    logger.info(
        "Applying migrations to %s ...",
        make_url(settings.database_url).render_as_string(hide_password=True),
    )
    try:
        report = migrate_database(settings.database_url)
    except (MigrationRefused, MigrationFailed) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    logger.info(
        "Migrations applied successfully (%s%s).",
        "adopted the v0.3.0 database; " if report.adopted else "",
        ", ".join(report.applied) if report.applied else "none pending",
    )


if __name__ == "__main__":
    main()
