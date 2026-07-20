"""Versioned schema migrations for provisioning-service databases.

SQLAlchemy ``create_all`` creates missing tables but does not alter existing
tables. These migrations cover additive compatibility changes needed by
persisted service databases across image upgrades.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from db.models import AnsiblePoolConfig, Base, DEFAULT_POOL_ID, ResourcePool

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    id: str
    apply: Callable[[Engine], None]


class SchemaDriftError(RuntimeError):
    """Raised at startup when the DB schema is behind the code's expectations.

    Per ARCHITECTURE.md § Schema Migration Execution: the service no longer
    applies migrations automatically at startup. An operator (or the Helm
    init container, or `make migrate` for local dev) must run them first.
    """


def apply_schema_migrations(
    engine: Engine,
    *,
    default_playbook_path: str = "/opt/domains/vms/provisioning/iac/ansible/playbooks/single-tenant/vm-operations.yaml",
    default_inventory_group: str = "kvm_hosts",
) -> None:
    """Apply all known migrations once, tracking completion in the database.

    Idempotent: migrations already recorded in ``schema_migrations`` are
    skipped, so this is safe to call repeatedly (the CLI entrypoint and the
    Helm init container both call it unconditionally on every run/restart).
    """
    _ensure_schema_migrations_table(engine)
    applied = _applied_migration_ids(engine)

    for migration in _MIGRATIONS:
        if migration.id in applied:
            continue
        if migration.id == "20260713_002_resource_pools_and_hosts_pool_id":
            _migrate_resource_pools_and_hosts_pool_id(
                engine,
                default_playbook_path=default_playbook_path,
                default_inventory_group=default_inventory_group,
            )
        else:
            migration.apply(engine)
        _record_migration(engine, migration.id)
        logger.info("Applied migration: %s", migration.id)


def check_schema_version(engine: Engine) -> None:
    """Fail fast if the DB schema is behind the last known migration.

    Called by the main service container at startup instead of applying
    migrations in-process. Raises :class:`SchemaDriftError` with an
    actionable message if ``schema_migrations`` is missing the most recent
    migration id — meaning migrations were never run, or the code shipped
    in this image is ahead of what's been applied to this database.
    """
    expected = _MIGRATIONS[-1].id if _MIGRATIONS else None
    if expected is None:
        return

    if not _table_exists(engine, "schema_migrations"):
        raise SchemaDriftError(_drift_message(current="<no migrations table>", expected=expected))

    applied = _applied_migration_ids(engine)
    if expected not in applied:
        current = sorted(applied)[-1] if applied else "<none>"
        raise SchemaDriftError(_drift_message(current=current, expected=expected))


def _drift_message(*, current: str, expected: str) -> str:
    return (
        f"Database schema is at version {current}, service expects {expected}.\n"
        "Apply migrations before starting the service:\n"
        "  docker run <image> python -m db.migrate        (docker / local)\n"
        "  kubectl apply -f migrate-job.yaml               (Kubernetes without init container)\n"
        "  make migrate                                    (local dev, outside Docker)"
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
    """Historical step, kept for correct replay against any DB still
    catching up from scratch. vm_leases was dropped for good by
    ``_migrate_drop_vm_leases_table`` below — this only recreates a table
    that migration then removes. Defined via raw SQL rather than
    ``Base.metadata.tables["vm_leases"]`` because the VmLease ORM model
    (which this table backed) was removed once the table itself was
    confirmed dead code; migration history must stay replayable without
    depending on a model that no longer exists.
    """
    if engine.dialect.name == "postgresql":
        id_default = "(gen_random_uuid()::text)"
    else:
        id_default = "(lower(hex(randomblob(16))))"
    with engine.begin() as connection:
        connection.execute(text(
            f"""
            CREATE TABLE IF NOT EXISTS vm_leases (
                id VARCHAR PRIMARY KEY DEFAULT {id_default},
                resource_id VARCHAR NOT NULL,
                escrow_uid VARCHAR NOT NULL UNIQUE,
                vm_host VARCHAR NOT NULL,
                vm_target VARCHAR NOT NULL,
                lease_start_utc TIMESTAMP,
                lease_end_utc TIMESTAMP NOT NULL,
                status VARCHAR NOT NULL DEFAULT 'pending',
                create_job_id VARCHAR,
                vm_remove_job_id VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
            """
        ))
    for index_name, sql in (
        ("ix_vm_leases_resource_id", "CREATE INDEX IF NOT EXISTS ix_vm_leases_resource_id ON vm_leases (resource_id)"),
        ("ix_vm_leases_escrow_uid", "CREATE INDEX IF NOT EXISTS ix_vm_leases_escrow_uid ON vm_leases (escrow_uid)"),
        ("ix_vm_leases_lease_end_utc", "CREATE INDEX IF NOT EXISTS ix_vm_leases_lease_end_utc ON vm_leases (lease_end_utc)"),
        ("ix_vm_leases_status", "CREATE INDEX IF NOT EXISTS ix_vm_leases_status ON vm_leases (status)"),
    ):
        _create_index_if_missing(engine, index_name, sql)


def _migrate_vm_leases_allocation_id(engine: Engine) -> None:
    _add_column_if_missing(engine, "vm_leases", "allocation_id", "VARCHAR")
    if _table_exists(engine, "vm_leases"):
        _create_index_if_missing(
            engine,
            "ix_vm_leases_allocation_id",
            "CREATE INDEX IF NOT EXISTS ix_vm_leases_allocation_id "
            "ON vm_leases (allocation_id)",
        )


def _migrate_multidimensional_capacity(engine: Engine) -> None:
    """Add POOLS-6 pass-1 multidimensional capacity columns.

    Additive-only: ``site_resources.total_units`` and
    ``site_allocations.units`` are left in place as service-maintained
    mirrors of ``capacity["gpu_count"]``/``dimensions["gpu_count"]`` so
    existing readers keep working unchanged. Pre-migration rows have
    ``capacity``/``dimensions`` = NULL; the ledger falls back to
    ``{"gpu_count": total_units}``/``{"gpu_count": units}`` for those rows.
    """
    _add_column_if_missing(engine, "site_resources", "capacity", "JSON")
    _add_column_if_missing(engine, "site_allocations", "dimensions", "JSON")
    _add_column_if_missing(engine, "capacity_events", "dimensions", "JSON")


def _migrate_drop_vm_leases_table(engine: Engine) -> None:
    """Drop vm_leases for good.

    Confirmed dead: no code anywhere in this repository ever constructs a
    VmLease row (the ORM model backing this table has been removed —
    db/models.py). The live lease watchdog operates entirely through
    SiteAllocation (market_site.db) instead. This is a genuine DROP, not a
    disable/soft-delete — there is no data to preserve (the table has
    always been empty in practice) and no application-level FK references
    it (VmLease.resource_id was always an unvalidated TEXT column, per its
    own former docstring).
    """
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS vm_leases"))


def _migrate_site_allocations_executor_fields(engine: Engine) -> None:
    _add_column_if_missing(engine, "site_allocations", "executor_kind", "VARCHAR")
    _add_column_if_missing(engine, "site_allocations", "executor_target", "VARCHAR")
    _add_column_if_missing(engine, "site_allocations", "release_job_id", "VARCHAR")
    _add_column_if_missing(engine, "site_allocations", "executor_ref", "JSON")


def _migrate_ansible_jobs_contract_fields(engine: Engine) -> None:
    for column_name, column_sql in (
        ("contract_version", "VARCHAR"),
        ("allocation_id", "VARCHAR"),
        ("deal_ref", "JSON"),
        ("executor_kind", "VARCHAR"),
        ("action_kind", "VARCHAR"),
        ("idempotency_key", "VARCHAR"),
    ):
        _add_column_if_missing(engine, "ansible_jobs", column_name, column_sql)
    if _table_exists(engine, "ansible_jobs"):
        _create_index_if_missing(
            engine,
            "ix_ansible_jobs_allocation_id",
            "CREATE INDEX IF NOT EXISTS ix_ansible_jobs_allocation_id "
            "ON ansible_jobs (allocation_id)",
        )
        _create_index_if_missing(
            engine,
            "uq_ansible_jobs_contract_idempotency",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ansible_jobs_contract_idempotency "
            "ON ansible_jobs (allocation_id, action_kind, idempotency_key)",
        )


def _migrate_resource_pools_and_hosts_pool_id(
    engine: Engine,
    *,
    default_playbook_path: str = "/opt/domains/vms/provisioning/iac/ansible/playbooks/single-tenant/vm-operations.yaml",
    default_inventory_group: str = "kvm_hosts",
) -> None:
    """Create resource_pools/ansible_pool_configs, seed the "default" pool,
    and add hosts.pool_id as NOT NULL.

    Ordering matters: the default pool row must exist before the
    hosts.pool_id column is added, since the column carries both a
    NOT NULL constraint and a DEFAULT of DEFAULT_POOL_ID — on Postgres the
    FK would fail validation against a not-yet-existing referenced row.
    Pre-existing hosts are backfilled to "default" by the column DEFAULT
    itself (SQLite and Postgres both apply DEFAULT to existing rows when a
    NOT NULL column is added), so no separate UPDATE statement is needed.

    This is the one deliberate exception to "migrations are schema-only":
    seeding a single deterministic system row is what makes the NOT NULL
    constraint possible without a nullable transitional state. It is not
    open-ended business-logic seeding (that stays in app_runtime's YAML
    pool-definitions import).
    """
    from market_resource_pools.db import Base as PoolsBase

    PoolsBase.metadata.tables["resource_pools"].create(bind=engine, checkfirst=True)
    Base.metadata.tables["ansible_pool_configs"].create(bind=engine, checkfirst=True)

    with Session(engine) as session:
        exists = (
            session.query(ResourcePool).filter(ResourcePool.id == DEFAULT_POOL_ID).one_or_none()
        )
        if exists is None:
            session.add(ResourcePool(
                id=DEFAULT_POOL_ID,
                label="Default Pool",
                provider="ansible",
                enabled=True,
                policy_tags={},
            ))
            session.flush()

        config = (
            session.query(AnsiblePoolConfig)
            .filter(AnsiblePoolConfig.pool_id == DEFAULT_POOL_ID)
            .one_or_none()
        )
        if config is None:
            # Migration values intentionally come from active provisioning
            # configuration: the default pool is a backwards-compatible
            # representation of how all existing hosts are provisioned today.
            session.add(AnsiblePoolConfig(
                pool_id=DEFAULT_POOL_ID,
                playbook_path=default_playbook_path,
                inventory_group=default_inventory_group,
                extra_vars={},
            ))
        session.commit()

    _add_column_if_missing(
        engine,
        "hosts",
        "pool_id",
        f"VARCHAR NOT NULL DEFAULT '{DEFAULT_POOL_ID}' REFERENCES resource_pools(id)",
    )


_MIGRATIONS: tuple[Migration, ...] = (
    Migration("20260603_001_ansible_jobs_escrow_uid", _migrate_ansible_jobs_escrow_uid),
    Migration("20260603_002_hosts_public_host", _migrate_hosts_public_host),
    Migration("20260603_003_vm_leases_table", _migrate_vm_leases_table),
    Migration("20260603_004_vm_leases_allocation_id", _migrate_vm_leases_allocation_id),
    Migration(
        "20260707_001_site_allocations_executor_fields",
        _migrate_site_allocations_executor_fields,
    ),
    Migration(
        "20260713_001_ansible_jobs_contract_fields",
        _migrate_ansible_jobs_contract_fields,
    ),
    Migration(
        "20260713_002_resource_pools_and_hosts_pool_id",
        _migrate_resource_pools_and_hosts_pool_id,
    ),
    Migration(
        "20260718_001_drop_vm_leases_table",
        _migrate_drop_vm_leases_table,
    ),
    Migration(
        "20260720_001_multidimensional_capacity",
        _migrate_multidimensional_capacity,
    ),
)
