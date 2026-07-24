"""Versioned schema migrations for provisioning-service databases.

SQLAlchemy ``create_all`` creates missing tables but does not alter existing
tables. These migrations cover additive compatibility changes needed by
persisted service databases across image upgrades.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from compute_provisioning_service.db.models import AnsiblePoolConfig, Base, DEFAULT_POOL_ID, ResourcePool
from market_fulfillment import (
    LegacyFulfillmentBackfillCompiler,
    LegacyFulfillmentBackfillDraft,
    LegacyFulfillmentBackfillInput,
    SettlementRequirement,
    new_fulfillment_id,
    new_provisioned_resource_id,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Migration:
    id: str
    apply: Callable[[Engine], None] | None


@dataclass(frozen=True)
class _BackfillPersistenceDraft:
    reservation_id: str
    owner_principal: str
    selected_id: str
    attributes: dict[str, object]
    vm_target: str
    requirements: dict[str, object]
    compiled: LegacyFulfillmentBackfillDraft
    state: str
    failure_reason: str | None


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
    fulfillment_backfill_compiler: LegacyFulfillmentBackfillCompiler | None = None,
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
        elif migration.id == "20260724_001_active_vm_fulfillment_backfill":
            _migrate_active_vm_fulfillments(
                engine,
                compiler=fulfillment_backfill_compiler,
                migration_id=migration.id,
            )
            logger.info("Applied migration: %s", migration.id)
            continue
        else:
            if migration.apply is None:
                raise AssertionError(f"migration {migration.id} has no apply function")
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
    required_migrations = {migration.id for migration in _MIGRATIONS}
    missing_migrations = required_migrations - applied
    if missing_migrations:
        current = sorted(applied)[-1] if applied else "<none>"
        raise SchemaDriftError(
            _drift_message(current=current, expected=expected)
            + "\nMissing migration records: "
            + ", ".join(sorted(missing_migrations))
        )

    required_fulfillment_tables = {
        "settlement_records",
        "provisioned_resources",
        "scheduling_cursors",
    }
    missing = required_fulfillment_tables - set(inspect(engine).get_table_names())
    if missing:
        raise SchemaDriftError(
            "Database schema records the current migration but is missing required "
            f"fulfillment tables: {', '.join(sorted(missing))}. Reconcile schema "
            "drift before starting the service."
        )
    for table_name in ("capacity_reservations", "settlement_records"):
        if not _column_exists(engine, table_name, "owner_principal"):
            raise SchemaDriftError(
                "Database schema records the current migration but is missing "
                f"{table_name}.owner_principal. Reconcile schema drift before "
                "starting the service."
            )
    for table_name, column_name in (
        ("settlement_records", "credential_generation"),
        ("settlement_records", "backfilled"),
        ("ansible_jobs", "credentials_private"),
    ):
        if not _column_exists(engine, table_name, column_name):
            raise SchemaDriftError(
                "Database schema records the current migration but is missing "
                f"{table_name}.{column_name}. Reconcile schema drift before "
                "starting the service."
            )


def _drift_message(*, current: str, expected: str) -> str:
    return (
        f"Database schema is at version {current}, service expects {expected}.\n"
        "Apply migrations before starting the service:\n"
        "  docker run <image> compute-provisioning-migrate (docker / local)\n"
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
    """Add multidimensional capacity columns.

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
    CapacityReservation (market_site.db) instead. This is a genuine DROP, not a
    disable/soft-delete — there is no data to preserve (the table has
    always been empty in practice) and no application-level FK references
    it (VmLease.resource_id was always an unvalidated TEXT column, per its
    own former docstring).
    """
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS vm_leases"))


def _migrate_rename_site_allocations_to_capacity_reservations(engine: Engine) -> None:
    """Rename legacy reservation and job identifier schema to current names."""
    legacy_exists = _table_exists(engine, "site_allocations")
    current_exists = _table_exists(engine, "capacity_reservations")
    if legacy_exists and current_exists:
        raise SchemaDriftError(
            "both site_allocations and capacity_reservations exist; "
            "refusing an ambiguous reservation-table migration"
        )
    if legacy_exists:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE site_allocations RENAME TO capacity_reservations")
            )
            connection.execute(text(
                "ALTER TABLE capacity_reservations "
                "RENAME COLUMN allocation_id TO capacity_reservation_id"
            ))
    if _column_exists(engine, "ansible_jobs", "allocation_id"):
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE ansible_jobs "
                "RENAME COLUMN allocation_id TO capacity_reservation_id"
            ))


def _migrate_site_allocations_executor_fields(engine: Engine) -> None:
    _add_column_if_missing(engine, "site_allocations", "executor_kind", "VARCHAR")
    _add_column_if_missing(engine, "site_allocations", "executor_target", "VARCHAR")
    _add_column_if_missing(engine, "site_allocations", "release_job_id", "VARCHAR")
    _add_column_if_missing(engine, "site_allocations", "executor_ref", "JSON")


def _migrate_ansible_jobs_contract_fields(engine: Engine) -> None:
    # On a database created fresh from the current ORM model, create_all
    # already named this column capacity_reservation_id -- this historical
    # migration's job (ensure the column exists) is already done under
    # that name, and must not add a second, stray allocation_id column
    # that a later rename step would then collide with when it tries to
    # rename allocation_id to a name that's already taken.
    reservation_column = (
        "capacity_reservation_id"
        if _column_exists(engine, "ansible_jobs", "capacity_reservation_id")
        else "allocation_id"
    )
    for column_name, column_sql in (
        ("contract_version", "VARCHAR"),
        (reservation_column, "VARCHAR"),
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
            f"CREATE INDEX IF NOT EXISTS ix_ansible_jobs_allocation_id "
            f"ON ansible_jobs ({reservation_column})",
        )
        _create_index_if_missing(
            engine,
            "uq_ansible_jobs_contract_idempotency",
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ansible_jobs_contract_idempotency "
            f"ON ansible_jobs ({reservation_column}, action_kind, idempotency_key)",
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


def _migrate_capacity_reservations_settlement_resource_id(engine: Engine) -> None:
    """Add ``capacity_reservations.settlement_resource_id``.

    Purely additive (nullable, no backfill needed): existing rows predate
    scheduling ever running against them in this codebase (no production
    caller exists yet, so
    NULL ("scheduling hasn't run for this row") is the correct value for
    every pre-existing row, not just a safe default.
    """
    _add_column_if_missing(
        engine, "capacity_reservations", "settlement_resource_id", "VARCHAR",
    )
    if _table_exists(engine, "capacity_reservations"):
        _create_index_if_missing(
            engine,
            "ix_capacity_reservations_settlement_resource_id",
            "CREATE INDEX IF NOT EXISTS "
            "ix_capacity_reservations_settlement_resource_id "
            "ON capacity_reservations (settlement_resource_id)",
        )


def _migrate_site_resources_pool_id(engine: Engine) -> None:
    """Place historical storefront-authored resources in the default pool."""
    _add_column_if_missing(engine, "site_resources", "pool_id", "VARCHAR")
    if not _table_exists(engine, "site_resources"):
        return
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE site_resources SET pool_id = :pool_id"),
            {"pool_id": DEFAULT_POOL_ID},
        )
    _create_index_if_missing(
        engine,
        "ix_site_resources_pool_id",
        "CREATE INDEX IF NOT EXISTS ix_site_resources_pool_id "
        "ON site_resources (pool_id)",
    )


def _migrate_capacity_buckets_and_current_debits(engine: Engine) -> None:
    """Create private host-level accounting rows and backfill current debits.

    The storefront reservation contract no longer exposes the selected
    accounting row. Existing reservation/resource links are converted into
    current debit rows before repositories begin using the new model.
    """
    from market_site.db import Base as SiteBase

    SiteBase.metadata.tables["capacity_buckets"].create(bind=engine, checkfirst=True)
    SiteBase.metadata.tables["capacity_reservation_debits"].create(
        bind=engine, checkfirst=True
    )
    if not _table_exists(engine, "site_resources"):
        return
    has_legacy_reservation_resource = (
        _table_exists(engine, "capacity_reservations")
        and _column_exists(engine, "capacity_reservations", "resource_id")
    )
    with engine.begin() as connection:
        connection.execute(text(
            """
            INSERT INTO capacity_buckets (
                capacity_bucket_id, backing_resource_id, pool_id, resource_type,
                resource_subtype, total_units, capacity, attributes, enabled
            )
            SELECT
                'bucket:' || sr.resource_id,
                sr.resource_id,
                COALESCE(sr.pool_id, 'default'),
                sr.resource_type,
                sr.resource_subtype,
                sr.total_units,
                COALESCE(sr.capacity, json_object('gpu_count', sr.total_units)),
                COALESCE(sr.attributes, json_object()),
                sr.enabled
            FROM site_resources sr
            WHERE NOT EXISTS (
                SELECT 1 FROM capacity_buckets cb
                WHERE cb.backing_resource_id = sr.resource_id
            )
            """
        ))
        if has_legacy_reservation_resource:
            connection.execute(text(
                """
                INSERT INTO capacity_reservation_debits (
                    capacity_reservation_id, capacity_bucket_id, dimensions
                )
                SELECT
                    cr.capacity_reservation_id,
                    cb.capacity_bucket_id,
                    COALESCE(cr.dimensions, json_object('gpu_count', cr.units))
                FROM capacity_reservations cr
                JOIN capacity_buckets cb
                  ON cb.backing_resource_id = cr.resource_id
                WHERE cr.resource_id IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM capacity_reservation_debits d
                    WHERE d.capacity_reservation_id = cr.capacity_reservation_id
                  )
                """
            ))


def _migrate_retire_site_resources(engine: Engine) -> None:
    """Validate the replacement accounting model and retire site_resources."""
    if not _table_exists(engine, "site_resources"):
        return
    with engine.begin() as connection:
        missing_buckets = connection.execute(text(
            "SELECT COUNT(*) FROM site_resources sr "
            "LEFT JOIN capacity_buckets cb ON cb.backing_resource_id = sr.resource_id "
            "WHERE cb.capacity_bucket_id IS NULL"
        )).scalar_one()
        if int(missing_buckets or 0):
            raise SchemaDriftError(
                f"cannot retire site_resources: {missing_buckets} rows have no capacity bucket"
            )
        if _table_exists(engine, "capacity_reservations"):
            missing_debits = connection.execute(text(
                "SELECT COUNT(*) FROM capacity_reservations cr "
                "LEFT JOIN capacity_reservation_debits d "
                "ON d.capacity_reservation_id = cr.capacity_reservation_id "
                "WHERE cr.state IN ('reserved','provisioning','leased','releasing','release_failed','unmanaged') "
                "AND d.capacity_reservation_id IS NULL"
            )).scalar_one()
            if int(missing_debits or 0):
                raise SchemaDriftError(
                    f"cannot retire site_resources: {missing_debits} held reservations have no current debit"
                )
        connection.execute(text("DROP TABLE site_resources"))


def _migrate_capacity_model_cutover(engine: Engine) -> None:
    """Apply the reservation and private capacity-accounting cutover."""
    _migrate_rename_site_allocations_to_capacity_reservations(engine)
    _migrate_capacity_reservations_settlement_resource_id(engine)
    _migrate_site_resources_pool_id(engine)
    _migrate_capacity_buckets_and_current_debits(engine)
    _migrate_retire_site_resources(engine)


def _migrate_storefront_ownership(engine: Engine) -> None:
    """Bind legacy rows to the compatible single-storefront principal."""
    for table_name in ("capacity_reservations", "settlement_records"):
        _add_column_if_missing(
            engine,
            table_name,
            "owner_principal",
            "VARCHAR NOT NULL DEFAULT 'legacy-admin'",
        )
        if _table_exists(engine, table_name):
            _create_index_if_missing(
                engine,
                f"ix_{table_name}_owner_principal",
                f"CREATE INDEX IF NOT EXISTS ix_{table_name}_owner_principal "
                f"ON {table_name} (owner_principal)",
            )


def _migrate_fulfillment_credential_generation(engine: Engine) -> None:
    """Add the non-secret monotonic result credential generation."""
    _add_column_if_missing(
        engine,
        "settlement_records",
        "credential_generation",
        "INTEGER NOT NULL DEFAULT 0",
    )


def _migrate_private_job_credentials(engine: Engine) -> None:
    """Prevent transient fulfillment credentials from legacy job reads."""
    _add_column_if_missing(
        engine,
        "ansible_jobs",
        "credentials_private",
        "BOOLEAN NOT NULL DEFAULT 0",
    )


def _json_mapping(value: object, *, field: str) -> dict[str, object]:
    if value is None:
        return {}
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise SchemaDriftError(f"legacy {field} must be a JSON object")
    return {str(key): item for key, item in value.items()}


def _migrate_active_vm_fulfillments(
    engine: Engine,
    *,
    compiler: LegacyFulfillmentBackfillCompiler | None,
    migration_id: str,
) -> None:
    """Atomically backfill teardown-capable aggregates for existing VM leases."""
    needs_backfilled_column = not _column_exists(
        engine, "settlement_records", "backfilled"
    )
    with engine.begin() as connection:
        if needs_backfilled_column:
            connection.execute(text(
                "ALTER TABLE settlement_records ADD COLUMN backfilled "
                "BOOLEAN NOT NULL DEFAULT 0"
            ))

        # This one-time cutover predates durable fulfillment ownership. All
        # existing host membership and host-backed accounting therefore enter
        # the system-owned default pool before any aggregate is reconstructed.
        connection.execute(
            text("UPDATE hosts SET pool_id = :pool_id"),
            {"pool_id": DEFAULT_POOL_ID},
        )
        connection.execute(
            text("UPDATE capacity_buckets SET pool_id = :pool_id"),
            {"pool_id": DEFAULT_POOL_ID},
        )

        rows = connection.execute(text(
            """
            SELECT
                cr.capacity_reservation_id,
                cr.owner_principal,
                cr.state,
                cr.units,
                cr.dimensions,
                cr.executor_kind,
                cr.executor_target,
                cr.executor_ref,
                cr.vm_host,
                cr.vm_target,
                cr.create_job_id,
                cr.release_job_id,
                cr.vm_remove_job_id,
                cr.settlement_resource_id AS existing_settlement_resource_id,
                cr.lease_end_utc,
                d.capacity_bucket_id,
                cb.backing_resource_id,
                cb.pool_id,
                cb.resource_type,
                cb.attributes,
                rp.provider,
                h.pool_id AS host_pool_id,
                apc.playbook_path,
                apc.extra_vars
            FROM capacity_reservations cr
            LEFT JOIN capacity_reservation_debits d
              ON d.capacity_reservation_id = cr.capacity_reservation_id
            LEFT JOIN capacity_buckets cb
              ON cb.capacity_bucket_id = d.capacity_bucket_id
            LEFT JOIN resource_pools rp ON rp.id = cb.pool_id
            LEFT JOIN hosts h ON h.name = cr.vm_host
            LEFT JOIN ansible_pool_configs apc ON apc.pool_id = cb.pool_id
            WHERE cr.state IN ('leased', 'releasing')
              AND (
                cr.executor_kind = 'vm'
                OR (
                  cr.executor_kind IS NULL
                  AND (cr.vm_host IS NOT NULL OR cr.vm_target IS NOT NULL)
                )
              )
            ORDER BY cr.capacity_reservation_id
            """
        )).mappings().all()

        if rows and compiler is None:
            raise SchemaDriftError(
                "active VM fulfillment backfill requires the VM adapter compiler"
            )

        drafts: list[_BackfillPersistenceDraft] = []
        coordinates: set[tuple[str, str]] = set()
        for row in rows:
            reservation_id = str(row["capacity_reservation_id"])
            if connection.execute(
                text(
                    "SELECT 1 FROM settlement_records "
                    "WHERE capacity_reservation_id = :reservation_id"
                ),
                {"reservation_id": reservation_id},
            ).first() is not None:
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} already has a fulfillment aggregate"
                )
            executor_ref = _json_mapping(
                row["executor_ref"], field=f"{reservation_id}.executor_ref"
            )
            attributes = _json_mapping(
                row["attributes"], field=f"{reservation_id}.resource_attributes"
            )
            host_values = {
                str(value)
                for value in (
                    row["vm_host"],
                    executor_ref.get("vm_host"),
                    attributes.get("vm_host"),
                )
                if value is not None and str(value).strip()
            }
            if len(host_values) != 1:
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} has ambiguous vm_host"
                )
            vm_host = next(iter(host_values))
            target_values = {
                str(value)
                for value in (row["executor_target"], row["vm_target"])
                if value is not None and str(value).strip()
            }
            if len(target_values) != 1:
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} has ambiguous vm_target"
                )
            vm_target = next(iter(target_values))
            coordinate = (vm_host, vm_target)
            if coordinate in coordinates:
                raise SchemaDriftError(
                    f"multiple active VM reservations use {vm_host!r}/{vm_target!r}"
                )
            coordinates.add(coordinate)

            selected_id = row["backing_resource_id"]
            if not row["capacity_bucket_id"] or not selected_id:
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} has no unique capacity bucket"
                )
            if row["resource_type"] != "compute.gpu":
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} is not compute.gpu"
                )
            if row["pool_id"] != DEFAULT_POOL_ID or row["host_pool_id"] != DEFAULT_POOL_ID:
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} is not mapped to the default pool"
                )
            if row["provider"] != "ansible" or not row["playbook_path"]:
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} has no Ansible provider configuration"
                )
            existing_selected = row["existing_settlement_resource_id"]
            if existing_selected not in (None, selected_id):
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} has a conflicting selected resource"
                )
            if not row["lease_end_utc"]:
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} has no lease end"
                )

            release_ids = {
                str(value)
                for value in (row["release_job_id"], row["vm_remove_job_id"])
                if value is not None and str(value).strip()
            }
            if len(release_ids) > 1:
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} has conflicting teardown jobs"
                )
            teardown_job_id = next(iter(release_ids), None)
            teardown_job_status = None
            if row["state"] == "releasing":
                if teardown_job_id is None:
                    raise SchemaDriftError(
                        f"releasing VM reservation {reservation_id!r} has no teardown job"
                    )
                job = connection.execute(
                    text("SELECT status, params FROM ansible_jobs WHERE id = :job_id"),
                    {"job_id": teardown_job_id},
                ).mappings().first()
                if job is None:
                    raise SchemaDriftError(
                        f"releasing VM reservation {reservation_id!r} references a missing teardown job"
                    )
                job_params = _json_mapping(
                    job["params"], field=f"{reservation_id}.teardown_job.params"
                )
                if (
                    job_params.get("vm_action") != "vm_remove"
                    or job_params.get("vm_host") != vm_host
                    or job_params.get("vm_target") != vm_target
                ):
                    raise SchemaDriftError(
                        f"releasing VM reservation {reservation_id!r} has a mismatched teardown job"
                    )
                teardown_job_status = str(job["status"])

            dimensions = _json_mapping(
                row["dimensions"], field=f"{reservation_id}.dimensions"
            ) or {"gpu_count": int(row["units"])}
            requirement = SettlementRequirement.model_validate({
                "resource_kind": "compute.gpu",
                "dimensions": dimensions,
                "attributes": {},
            })
            extra_vars = _json_mapping(
                row["extra_vars"], field=f"{reservation_id}.provider_extra_vars"
            )
            assert compiler is not None
            try:
                compiled = compiler(LegacyFulfillmentBackfillInput(
                    capacity_reservation_id=reservation_id,
                    executor_host=vm_host,
                    executor_target=vm_target,
                    create_job_id=(
                        str(row["create_job_id"]) if row["create_job_id"] else None
                    ),
                    teardown_job_id=teardown_job_id,
                    playbook_path=str(row["playbook_path"]),
                    provider_extra_vars=extra_vars,
                ))
            except Exception as exc:
                raise SchemaDriftError(
                    f"legacy VM reservation {reservation_id!r} cannot compile teardown: {exc}"
                ) from exc
            state = "active"
            failure_reason = None
            if row["state"] == "releasing":
                if teardown_job_status in {"failed", "cancelled"}:
                    state = "teardown_failed"
                    failure_reason = "legacy_teardown_provider_failed"
                else:
                    state = "tearing_down"
            drafts.append(_BackfillPersistenceDraft(
                reservation_id=reservation_id,
                owner_principal=str(row["owner_principal"] or "legacy-admin"),
                selected_id=str(selected_id),
                attributes=attributes,
                vm_target=vm_target,
                requirements=requirement.model_dump(mode="json"),
                compiled=compiled,
                state=state,
                failure_reason=failure_reason,
            ))

        for draft in drafts:
            fulfillment_id = new_fulfillment_id()
            compiled = draft.compiled
            connection.execute(text(
                """
                INSERT INTO settlement_records (
                    capacity_reservation_id, fulfillment_id, owner_principal,
                    market, scheduling_requirements, resource_id_constraint,
                    settlement_resource_id, pool_id, provider,
                    resource_attributes, provider_metadata,
                    prepared_teardown_operation, teardown_provider_metadata,
                    state, failure_reason, credential_generation, backfilled,
                    attempt_count
                ) VALUES (
                    :reservation_id, :fulfillment_id, :owner_principal,
                    'vms', :requirements, :selected_id,
                    :selected_id, :pool_id, 'ansible',
                    :attributes, :provider_metadata,
                    :prepared_teardown, :teardown_metadata,
                    :state, :failure_reason, 0, 1, 0
                )
                """
            ), {
                "reservation_id": draft.reservation_id,
                "fulfillment_id": fulfillment_id,
                "owner_principal": draft.owner_principal,
                "requirements": json.dumps(draft.requirements),
                "selected_id": draft.selected_id,
                "pool_id": DEFAULT_POOL_ID,
                "attributes": json.dumps(draft.attributes),
                "provider_metadata": json.dumps(compiled.provider_metadata),
                "prepared_teardown": json.dumps(
                    compiled.prepared_teardown_operation.model_dump(mode="json")
                ),
                "teardown_metadata": (
                    json.dumps(compiled.teardown_provider_metadata)
                    if draft.state != "active"
                    else None
                ),
                "state": draft.state,
                "failure_reason": draft.failure_reason,
            })
            connection.execute(text(
                """
                INSERT INTO provisioned_resources (
                    provisioned_resource_id, capacity_reservation_id,
                    fulfillment_id, domain_resource_ref, status
                ) VALUES (
                    :resource_id, :reservation_id, :fulfillment_id,
                    :domain_resource_ref, 'active'
                )
                """
            ), {
                "resource_id": new_provisioned_resource_id(),
                "reservation_id": draft.reservation_id,
                "fulfillment_id": fulfillment_id,
                "domain_resource_ref": draft.vm_target,
            })
            connection.execute(
                text(
                    "UPDATE capacity_reservations "
                    "SET settlement_resource_id = :selected_id "
                    "WHERE capacity_reservation_id = :reservation_id"
                ),
                {
                    "selected_id": draft.selected_id,
                    "reservation_id": draft.reservation_id,
                },
            )

        connection.execute(
            text("INSERT INTO schema_migrations (id) VALUES (:id)"),
            {"id": migration_id},
        )


def _migrate_fulfillment_aggregate(engine: Engine) -> None:
    """Create the provisioning-owned fulfillment aggregate and fairness state."""
    from market_fulfillment.db import Base as FulfillmentBase

    FulfillmentBase.metadata.create_all(bind=engine)


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
    Migration(
        "20260722_001_pools7_capacity_model_cutover",
        _migrate_capacity_model_cutover,
    ),
    Migration(
        "20260723_001_fulfillment_aggregate",
        _migrate_fulfillment_aggregate,
    ),
    Migration(
        "20260723_002_storefront_ownership",
        _migrate_storefront_ownership,
    ),
    Migration(
        "20260723_003_fulfillment_credential_generation",
        _migrate_fulfillment_credential_generation,
    ),
    Migration(
        "20260723_004_private_job_credentials",
        _migrate_private_job_credentials,
    ),
    Migration(
        "20260724_001_active_vm_fulfillment_backfill",
        None,
    ),
)
