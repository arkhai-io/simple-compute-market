"""Versioned schema migrations for provisioning-service databases.

SQLAlchemy ``create_all`` creates missing tables but does not alter existing
tables. These migrations cover additive compatibility changes needed by
persisted service databases across image upgrades.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from compute_provisioning_service.db.models import AnsiblePoolConfig, Base, DEFAULT_POOL_ID, ResourcePool

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



def _migrate_legacy_vm_leases_to_fulfillment(engine: Engine) -> None:
    """Atomically preserve nonterminal VM leases in the fulfillment aggregate.

    A tracked provider job is authoritative during cutover. Per-candidate
    derivation and provider-envelope preparation are delegated to
    ``compile_legacy_vm_fulfillment_backfill``, a pure function with no
    database session; this function owns only enumeration, cross-candidate
    identity/target deduplication, comparison against already-persisted
    rows, and the single atomic write.
    """
    if not _table_exists(engine, "vm_leases"):
        return

    from market_fulfillment.db import Base as FulfillmentBase

    FulfillmentBase.metadata.create_all(engine)

    with engine.begin() as connection:
        _apply_legacy_vm_lease_backfill(connection)


def _normalize_json_column(value):
    """Return a JSON column's value as a Python object regardless of whether
    the driver already decoded it or returned the stored text."""
    if isinstance(value, str):
        return json.loads(value)
    return value


def _existing_settlement_row_conflicts(existing, draft) -> bool:
    """Compare an already-persisted settlement row against a compiled draft.

    Equivalence covers every field a provider operation depends on for
    correctness, not only coarse placement fields: provider metadata
    (including the tracked create job), teardown provider metadata
    (including the active teardown job), the prepared teardown envelope,
    and resource attributes. A row matching on state/resource/pool/provider
    alone but differing in tracked job identity is a conflict, not an
    equivalent rerun.
    """
    expected = (
        draft.state,
        draft.settlement_resource_id,
        draft.pool_id,
        draft.provider,
        draft.resource_attributes,
        draft.provider_metadata,
        draft.teardown_provider_metadata,
        draft.prepared_teardown_operation,
    )
    actual = (
        existing["state"],
        existing["settlement_resource_id"],
        existing["pool_id"],
        existing["provider"],
        _normalize_json_column(existing["resource_attributes"]),
        _normalize_json_column(existing["provider_metadata"]),
        _normalize_json_column(existing["teardown_provider_metadata"]),
        _normalize_json_column(existing["prepared_teardown_operation"]),
    )
    return actual != expected


def _existing_provisioned_resources_conflict(connection, capacity_reservation_id, expected_ref) -> bool:
    """Compare already-persisted ``ProvisionedResource`` rows against a draft.

    A candidate with no live target expects zero provisioned-resource rows;
    a candidate with a live target expects exactly one, whose
    ``provisioned_resource_id`` equals ``expected_ref`` -- the same
    deterministic derivation ``compile_legacy_vm_fulfillment_backfill`` used
    to compute it, so a genuine re-run always recomputes the identical value.
    Zero, several, or a differently-identified row are all conflicts:
    silently accepting any of them could mean losing track of, or
    overwriting, which VM a reservation actually owns. Row count alone is
    not sufficient here -- a single row with the wrong identity must still
    be rejected, not treated as equivalent.
    """
    rows = connection.execute(text(
        "SELECT provisioned_resource_id FROM provisioned_resources WHERE capacity_reservation_id=:id"
    ), {"id": capacity_reservation_id}).mappings().all()
    ids = [row["provisioned_resource_id"] for row in rows]
    if expected_ref is None:
        return len(ids) != 0
    return ids != [expected_ref]


def _apply_legacy_vm_lease_backfill(connection) -> None:
    """Enumerate all historical VM lease candidates, compile them before
    writing, reject conflicts, and persist the population atomically.

    Takes an open connection rather than an engine: the caller owns the
    transaction boundary this enumeration and write run inside.
    """
    from market_fulfillment.backfill import LegacyBackfillValidationError
    from vm_provisioning_adapter.legacy_backfill import (
        LegacyVmLeaseCandidate,
        compile_legacy_vm_fulfillment_backfill,
    )

    rows = connection.execute(text(
        """
        SELECT vl.id AS lease_id, vl.allocation_id, vl.escrow_uid,
               vl.vm_host, vl.vm_target, vl.status, vl.create_job_id,
               vl.vm_remove_job_id, cr.capacity_reservation_id,
               cr.executor_target, h.pool_id, rp.provider,
               apc.playbook_path, apc.inventory_group, apc.extra_vars
        FROM vm_leases vl
        LEFT JOIN capacity_reservations cr
          ON cr.capacity_reservation_id = vl.allocation_id
        LEFT JOIN hosts h ON h.name = vl.vm_host
        LEFT JOIN resource_pools rp ON rp.id = h.pool_id
        LEFT JOIN ansible_pool_configs apc ON apc.pool_id = h.pool_id
        WHERE vl.status IN ('provisioning','leased','releasing','release_failed')
        ORDER BY vl.id
        """
    )).mappings().all()

    seen_reservations: set[str] = set()
    seen_targets: set[str] = set()
    drafts = []
    for row in rows:
        reservation_id = row["capacity_reservation_id"] or row["allocation_id"]
        if not reservation_id:
            raise SchemaDriftError(f"legacy VM lease {row['lease_id']} has no reservation identity")
        if reservation_id in seen_reservations:
            raise SchemaDriftError(f"duplicate legacy VM leases for reservation {reservation_id}")
        seen_reservations.add(reservation_id)

        extra_vars = row["extra_vars"] or {}
        if isinstance(extra_vars, str):
            extra_vars = json.loads(extra_vars)
        candidate = LegacyVmLeaseCandidate(
            lease_id=str(row["lease_id"]),
            capacity_reservation_id=reservation_id,
            status=row["status"],
            vm_host=row["vm_host"],
            pool_id=row["pool_id"],
            provider=row["provider"],
            playbook_path=row["playbook_path"],
            inventory_group=row["inventory_group"],
            extra_vars=extra_vars,
            vm_target=row["vm_target"],
            executor_target=row["executor_target"],
            create_job_id=row["create_job_id"],
            vm_remove_job_id=row["vm_remove_job_id"],
        )
        try:
            draft = compile_legacy_vm_fulfillment_backfill(
                candidate, fulfillment_id=str(uuid.uuid4())
            )
        except LegacyBackfillValidationError as exc:
            raise SchemaDriftError(str(exc)) from exc

        target = draft.provisioned_resource_id
        if target and target in seen_targets:
            raise SchemaDriftError(f"duplicate legacy VM target {target}")
        if target:
            seen_targets.add(target)
        drafts.append(draft)

    for draft in drafts:
        existing = connection.execute(text(
            "SELECT capacity_reservation_id, state, settlement_resource_id, pool_id, provider, "
            "resource_attributes, provider_metadata, teardown_provider_metadata, "
            "prepared_teardown_operation "
            "FROM settlement_records WHERE capacity_reservation_id=:id"
        ), {"id": draft.capacity_reservation_id}).mappings().one_or_none()
        if existing:
            if _existing_settlement_row_conflicts(existing, draft) or _existing_provisioned_resources_conflict(
                connection, draft.capacity_reservation_id, draft.provisioned_resource_id
            ):
                raise SchemaDriftError(
                    f"conflicting settlement aggregate for reservation {draft.capacity_reservation_id}"
                )
            continue

        connection.execute(text(
            """INSERT INTO settlement_records (
                capacity_reservation_id, fulfillment_id, market, scheduling_requirements,
                settlement_resource_id, pool_id, provider, resource_attributes,
                prepared_teardown_operation, provider_metadata, teardown_provider_metadata, state, attempt_count
            ) VALUES (:rid,:fid,'vms',:requirements,:resource_id,:pool_id,:provider,:attributes,
                      :prepared_teardown,:metadata,:teardown_metadata,:state,0)"""
        ), {
            "rid": draft.capacity_reservation_id, "fid": draft.fulfillment_id,
            "requirements": json.dumps({"resource_kind": "vm"}), "resource_id": draft.settlement_resource_id,
            "pool_id": draft.pool_id, "provider": draft.provider,
            "attributes": json.dumps(draft.resource_attributes),
            "prepared_teardown": json.dumps(draft.prepared_teardown_operation) if draft.prepared_teardown_operation is not None else None,
            "metadata": json.dumps(draft.provider_metadata),
            "teardown_metadata": json.dumps(draft.teardown_provider_metadata) if draft.teardown_provider_metadata is not None else None,
            "state": draft.state,
        })
        if draft.provisioned_resource_id:
            connection.execute(text(
                """INSERT INTO provisioned_resources
                (provisioned_resource_id, capacity_reservation_id, fulfillment_id, status)
                VALUES (:id,:rid,:fid,'active')"""
            ), {
                "id": draft.provisioned_resource_id, "rid": draft.capacity_reservation_id,
                "fid": draft.fulfillment_id,
            })


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
    """Add ``site_resources.pool_id`` and backfill it from the existing
    ``attributes`` JSON, where the storefront's old sync push put it.

    Additive column, backfill-then-done (not ongoing): once this runs,
    ``pool_id`` is a real column callers set explicitly going forward
    (
    enforced attribute rather than a storefront-authored guess"). Rows
    whose attributes never had a pool_id stay NULL, correctly falling
    back to the degenerate single-resource-pool case
    (``market_site.ledger._resource_attribute_view``).
    """
    _add_column_if_missing(engine, "site_resources", "pool_id", "VARCHAR")
    if not _table_exists(engine, "site_resources"):
        return
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.execute(text(
                "UPDATE site_resources SET pool_id = attributes->>'pool_id' "
                "WHERE pool_id IS NULL "
                "AND attributes IS NOT NULL "
                "AND attributes->>'pool_id' IS NOT NULL"
            ))
        else:
            connection.execute(text(
                "UPDATE site_resources "
                "SET pool_id = json_extract(attributes, '$.pool_id') "
                "WHERE pool_id IS NULL "
                "AND attributes IS NOT NULL "
                "AND json_extract(attributes, '$.pool_id') IS NOT NULL"
            ))
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
                COALESCE(sr.pool_id, sr.resource_id),
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



def _migrate_remove_provisioned_resource_domain_ref(engine: Engine) -> None:
    """Remove the redundant provider-domain identifier from fulfillment outputs."""
    if not _table_exists(engine, "provisioned_resources") or not _column_exists(
        engine, "provisioned_resources", "domain_resource_ref"
    ):
        return
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE provisioned_resources_new (
                provisioned_resource_id VARCHAR PRIMARY KEY,
                capacity_reservation_id VARCHAR NOT NULL,
                fulfillment_id VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(capacity_reservation_id) REFERENCES settlement_records(capacity_reservation_id) ON DELETE CASCADE
            )
        """))
        connection.execute(text("""
            INSERT INTO provisioned_resources_new (
                provisioned_resource_id, capacity_reservation_id, fulfillment_id,
                status, created_at, updated_at
            )
            SELECT provisioned_resource_id, capacity_reservation_id, fulfillment_id,
                   status, created_at, updated_at
            FROM provisioned_resources
        """))
        connection.execute(text("DROP TABLE provisioned_resources"))
        connection.execute(text("ALTER TABLE provisioned_resources_new RENAME TO provisioned_resources"))
        connection.execute(text("CREATE INDEX ix_provisioned_resources_capacity_reservation_id ON provisioned_resources (capacity_reservation_id)"))
        connection.execute(text("CREATE INDEX ix_provisioned_resources_fulfillment_id ON provisioned_resources (fulfillment_id)"))


def _migrate_ansible_pool_requirement_delegate(engine: Engine) -> None:
    _add_column_if_missing(
        engine,
        "ansible_pool_configs",
        "requirement_delegate",
        "VARCHAR NOT NULL DEFAULT 'vm_management_v1'",
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
        "20260720_001_multidimensional_capacity",
        _migrate_multidimensional_capacity,
    ),
    Migration(
        "20260722_001_pools7_capacity_model_cutover",
        _migrate_capacity_model_cutover,
    ),
    Migration(
        "20260724_001_legacy_vm_leases_to_fulfillment",
        _migrate_legacy_vm_leases_to_fulfillment,
    ),
    Migration(
        "20260724_002_drop_vm_leases_table",
        _migrate_drop_vm_leases_table,
    ),
    Migration(
        "20260725_001_remove_provisioned_resource_domain_ref",
        _migrate_remove_provisioned_resource_domain_ref,
    ),
    Migration(
        "20260728_001_ansible_pool_requirement_delegate",
        _migrate_ansible_pool_requirement_delegate,
    ),
)
