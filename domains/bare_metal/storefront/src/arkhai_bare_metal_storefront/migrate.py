"""The migration command.

    bare-metal-storefront-migrate [--check]

Applies the bare-metal storefront's migration chain to its configured database,
which ``bare-metal-storefront serve`` refuses to start without (see
openspec/specs/deployment-state/spec.md#requirement-service-owned-migration-history).
It reads only the database path from the layered settings, without validating
the rest, so it runs whatever else the configuration says: the migrations take
the connection alone. A chart runs it as the storefront's
init container, Compose before ``serve`` in the storefront's container, and
``make migrate`` for local development.

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

from .config import settings_source
from .migrations import CHAIN, check_storefront_database, migrate_storefront_database

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
    db_path = str(settings_source().get("db_path") or "")
    if not db_path:
        print(f"{CHAIN.service}'s configuration names no db_path.", file=sys.stderr)
        raise SystemExit(1)
    # The storefront's configuration states no log level, so the command logs
    # at INFO.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    if arguments.check:
        result = check_storefront_database(db_path)
        print(f"{CHAIN.service}: {describe(result)}")
        if not result.compatible:
            print(
                refusal_message(result, service=CHAIN.service, command=CHAIN.command),
                file=sys.stderr,
            )
            raise SystemExit(1)
        return
    logger.info("Applying migrations to %s ...", db_path)
    try:
        report = migrate_storefront_database(db_path)
    except (MigrationRefused, MigrationFailed) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
    logger.info(
        "Migrations applied successfully (%s).",
        ", ".join(report.applied) if report.applied else "none pending",
    )


if __name__ == "__main__":
    main()
