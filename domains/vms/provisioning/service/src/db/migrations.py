"""Versioned schema migrations for provisioning-service databases.

SQLAlchemy ``create_all`` creates missing tables but does not alter existing
tables. These migrations cover additive compatibility changes needed by
persisted service databases across image upgrades.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine, inspect, text

from db.models import Base


@dataclass(frozen=True)
class Migration:
    id: str
    apply: Callable[[Engine], None]


def apply_schema_migrations(engine: Engine) -> None:
    """Apply all known migrations once, tracking completion in the database."""
    _ensure_schema_migrations_table(engine)
    applied = _applied_migration_ids(engine)

    for migration in _MIGRATIONS:
        if migration.id in applied:
            continue
        migration.apply(engine)
        _record_migration(engine, migration.id)


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


def _add_column_if_missing(
    engine: Engine,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    if not _table_exists(engine, table_name) or _column_exists(
        engine, table_name, column_name
    ):
        return

    if engine.dialect.name == "postgresql":
        sql = (
            f"ALTER TABLE {table_name} "
            f"ADD COLUMN IF NOT EXISTS {column_name} {column_sql}"
        )
    else:
        sql = f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"
    with engine.begin() as connection:
        connection.execute(text(sql))


def _create_index_if_missing(engine: Engine, index_name: str, sql: str) -> None:
    with engine.begin() as connection:
        connection.execute(text(sql))


def _migrate_ansible_jobs_escrow_uid(engine: Engine) -> None:
    _add_column_if_missing(engine, "ansible_jobs", "escrow_uid", "VARCHAR")
    if _table_exists(engine, "ansible_jobs"):
        _create_index_if_missing(
            engine,
            "ix_ansible_jobs_escrow_uid",
            "CREATE INDEX IF NOT EXISTS ix_ansible_jobs_escrow_uid "
            "ON ansible_jobs (escrow_uid)",
        )


def _migrate_hosts_public_host(engine: Engine) -> None:
    _add_column_if_missing(engine, "hosts", "public_host", "VARCHAR")


def _migrate_vm_leases_table(engine: Engine) -> None:
    Base.metadata.tables["vm_leases"].create(bind=engine, checkfirst=True)


def _migrate_vm_leases_allocation_id(engine: Engine) -> None:
    _add_column_if_missing(engine, "vm_leases", "allocation_id", "VARCHAR")
    if _table_exists(engine, "vm_leases"):
        _create_index_if_missing(
            engine,
            "ix_vm_leases_allocation_id",
            "CREATE INDEX IF NOT EXISTS ix_vm_leases_allocation_id "
            "ON vm_leases (allocation_id)",
        )


_MIGRATIONS: tuple[Migration, ...] = (
    Migration("20260603_001_ansible_jobs_escrow_uid", _migrate_ansible_jobs_escrow_uid),
    Migration("20260603_002_hosts_public_host", _migrate_hosts_public_host),
    Migration("20260603_003_vm_leases_table", _migrate_vm_leases_table),
    Migration("20260603_004_vm_leases_allocation_id", _migrate_vm_leases_allocation_id),
)
