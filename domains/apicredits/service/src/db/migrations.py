"""Versioned schema migrations for the API-credits service database.

SQLAlchemy ``create_all`` creates missing tables but does not alter
existing ones. This module tracks completed migrations in a
``schema_migrations`` table so schema evolution can be applied exactly
once, in order, idempotently, across restarts.

Migrations run in-process at startup, before the app is ready to serve,
via ``run_migrations`` in ``db/database.py``. ``check_schema_version``
raises if the database is behind the migrations this module defines;
nothing in this service's own startup path calls it today.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from sqlalchemy import Engine, inspect, text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    id: str
    apply: Callable[[Engine], None]


class SchemaDriftError(RuntimeError):
    """Raised when the DB schema is behind the code's expectations --
    migrations were never run against this database."""


def apply_schema_migrations(engine: Engine) -> None:
    """Apply all known migrations once, tracking completion in the
    database.

    Idempotent: migrations already recorded in ``schema_migrations`` are
    skipped, so this is safe to call on every startup.
    """
    _ensure_schema_migrations_table(engine)
    applied = _applied_migration_ids(engine)

    for migration in _MIGRATIONS:
        if migration.id in applied:
            continue
        migration.apply(engine)
        _record_migration(engine, migration.id)
        logger.info("Applied migration: %s", migration.id)


def check_schema_version(engine: Engine) -> None:
    """Raise :class:`SchemaDriftError` if the DB schema is behind the
    last known migration -- meaning migrations were never run, or the
    code shipped in this image is ahead of what's been applied to this
    database. This service's own startup applies migrations in-process
    instead of calling this function (see ``db/database.py``'s
    ``run_migrations``).
    """
    expected = _MIGRATIONS[-1].id if _MIGRATIONS else None
    if expected is None:
        return

    if not _table_exists(engine, "schema_migrations"):
        raise SchemaDriftError(
            _drift_message(current="<no migrations table>", expected=expected)
        )

    applied = _applied_migration_ids(engine)
    if expected not in applied:
        current = sorted(applied)[-1] if applied else "<none>"
        raise SchemaDriftError(_drift_message(current=current, expected=expected))


def _drift_message(*, current: str, expected: str) -> str:
    return (
        f"API-credits database schema is at version {current}, service "
        f"expects {expected}. Apply migrations before starting the "
        "service (run_migrations)."
    )


def _ensure_schema_migrations_table(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id VARCHAR PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        ))


def _applied_migration_ids(engine: Engine) -> set[str]:
    with engine.begin() as connection:
        rows = connection.execute(text("SELECT id FROM schema_migrations")).fetchall()
    return {str(row[0]) for row in rows}


def _record_migration(engine: Engine, migration_id: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO schema_migrations (id) VALUES (:id)"),
            {"id": migration_id},
        )


def _table_exists(engine: Engine, table_name: str) -> bool:
    return table_name in set(inspect(engine).get_table_names())


def _column_exists(engine: Engine, table_name: str, column_name: str) -> bool:
    if not _table_exists(engine, table_name):
        return False
    return column_name in {
        column["name"] for column in inspect(engine).get_columns(table_name)
    }


def _adopt_baseline_schema(engine: Engine) -> None:
    """Adopt the existing API-credit and capacity tables into versioning."""
    required = {
        "api_keys",
        "credit_grants",
        "consumption_events",
        "capacity_buckets",
        "capacity_reservations",
    }
    missing = required - set(inspect(engine).get_table_names())
    if missing:
        raise SchemaDriftError(
            f"API-credits baseline schema is missing tables: {sorted(missing)}"
        )


_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        "20260731_001_apicredits_schema_baseline",
        _adopt_baseline_schema,
    ),
)
