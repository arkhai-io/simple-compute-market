"""Versioned schema migrations for provisioning-service databases.

SQLAlchemy ``create_all`` creates missing tables but does not alter existing
tables. These migrations cover additive compatibility changes needed by
persisted service databases across image upgrades.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import Connection
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

    for migration in MIGRATIONS:
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
    expected = MIGRATIONS[-1].id if MIGRATIONS else None
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


def _table_exists(bind: Engine | Connection, table_name: str) -> bool:
    return table_name in set(inspect(bind).get_table_names())


def _column_exists(engine: Engine, table_name: str, column_name: str) -> bool:
    if not _table_exists(engine, table_name):
        return False
    return column_name in {
        column["name"] for column in inspect(engine).get_columns(table_name)
    }


_SQLITE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_sql_identifier(name: str) -> str:
    """Reject anything that isn't a bare SQLite identifier before it is
    interpolated into raw SQL. ``table_name``/``columns_to_drop`` are
    ordinary Python arguments, not user input, on every caller this
    helper has today — this validates them anyway so the helper stays
    provably safe to call generically rather than safe only by every
    caller happening to pass a literal.
    """
    if not _SQLITE_IDENTIFIER.match(name):
        raise ValueError(f"Not a safe SQL identifier: {name!r}")
    return name


def _drop_columns_via_table_rebuild(
    engine: Engine, table_name: str, columns_to_drop: Sequence[str],
) -> None:
    """Deterministically drop columns from a SQLite table via a full
    create/copy/drop/rename cycle, instead of ``ALTER TABLE ... DROP
    COLUMN`` (unavailable before SQLite 3.35, and this repository
    supports SQLite only — so there is no reason to accept a silent
    partial migration rather than doing the rebuild every version
    actually supports).

    A no-op if none of ``columns_to_drop`` are present. Introspects the
    table's current columns via ``PRAGMA table_info`` rather than a
    hardcoded column list, so this stays correct as the model gains
    columns rather than needing to be kept in sync by hand; preserves
    every other column's type, nullability, default, and primary-key
    flag, and recreates every named index that doesn't reference a
    dropped column. Every identifier this function interpolates into raw
    SQL — the table name, the columns to drop, and every column name
    read back from ``PRAGMA table_info`` — is validated against a strict
    ``[A-Za-z_][A-Za-z0-9_]*`` rule first.

    Follows SQLite's documented offline-schema-change procedure for a
    table other rows may reference by foreign key: the whole rebuild runs
    on one dedicated connection with foreign-key enforcement disabled for
    its duration (dropping the original table would otherwise cascade-delete
    every referencing child row if the caller's database has
    ``PRAGMA foreign_keys=ON`` — those rows are never touched by this
    function, but a plain ``DROP TABLE`` under FK enforcement would delete
    them as a side effect of the rebuild, not preserve them), verifies with
    ``PRAGMA foreign_key_check`` before committing, and restores whatever
    the connection's foreign-key setting was before this function ran.

    Does not preserve triggers, views, or outbound foreign-key constraints
    *defined on this table* — ``capacity_reservations`` (this helper's
    only caller today) has none of those, confirmed by inspection, and
    this function refuses to run against a table that does rather than
    silently dropping them unnoticed. Extend it deliberately if a future
    caller needs that.
    """
    _validate_sql_identifier(table_name)
    for column in columns_to_drop:
        _validate_sql_identifier(column)

    present = {
        column for column in columns_to_drop
        if _column_exists(engine, table_name, column)
    }
    if not present:
        return

    with engine.connect() as connection:
        triggers_and_views = connection.execute(text(
            "SELECT type, name FROM sqlite_master "
            "WHERE tbl_name = :table_name AND type IN ('trigger', 'view')"
        ), {"table_name": table_name}).fetchall()
        if triggers_and_views:
            raise NotImplementedError(
                f"_drop_columns_via_table_rebuild does not preserve "
                f"triggers/views, but {table_name!r} has: "
                f"{sorted(f'{kind}:{name}' for kind, name in triggers_and_views)}. "
                "Extend this helper before using it on this table."
            )
        outbound_fks = connection.execute(
            text(f"PRAGMA foreign_key_list({table_name})")
        ).fetchall()
        if outbound_fks:
            raise NotImplementedError(
                f"_drop_columns_via_table_rebuild does not preserve "
                f"outbound foreign key constraints, but {table_name!r} "
                f"has some. Extend this helper before using it on this "
                "table."
            )

        # PRAGMA foreign_keys can only be changed with no transaction
        # open -- read and set it before starting the rebuild's own
        # transaction, using exec_driver_sql + an explicit commit to
        # close out SQLAlchemy's autobegin rather than assuming none is
        # open.
        prior_foreign_keys = connection.exec_driver_sql(
            "PRAGMA foreign_keys"
        ).scalar()
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()

        try:
            with connection.begin():
                columns = connection.execute(
                    text(f"PRAGMA table_info({table_name})")
                ).fetchall()
                keep = [c for c in columns if c[1] not in present]
                if not keep:
                    raise ValueError(
                        f"Refusing to drop every column of {table_name!r}"
                    )
                keep_names = [_validate_sql_identifier(c[1]) for c in keep]

                # Captured before the table is dropped -- once the
                # rebuilt table is renamed into place, a query for
                # tbl_name = table_name would find the *new*, index-less
                # table instead of the original's indexes.
                indexes = connection.execute(text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'index' AND tbl_name = :table_name "
                    "AND sql IS NOT NULL"
                ), {"table_name": table_name}).fetchall()

                def _column_def(col) -> str:
                    _cid, name, col_type, notnull, default, pk = col
                    parts = [name, col_type or ""]
                    if pk:
                        parts.append("PRIMARY KEY")
                    if notnull and not pk:
                        parts.append("NOT NULL")
                    if default is not None:
                        parts.append(f"DEFAULT {default}")
                    return " ".join(part for part in parts if part)

                rebuild_table = f"{table_name}__rebuild"
                connection.execute(text(f"DROP TABLE IF EXISTS {rebuild_table}"))
                connection.execute(text(
                    f"CREATE TABLE {rebuild_table} "
                    f"({', '.join(_column_def(c) for c in keep)})"
                ))
                column_list = ", ".join(keep_names)
                connection.execute(text(
                    f"INSERT INTO {rebuild_table} ({column_list}) "
                    f"SELECT {column_list} FROM {table_name}"
                ))
                connection.execute(text(f"DROP TABLE {table_name}"))
                connection.execute(text(
                    f"ALTER TABLE {rebuild_table} RENAME TO {table_name}"
                ))

                for (index_sql,) in indexes:
                    if any(dropped in index_sql for dropped in present):
                        continue
                    connection.execute(text(index_sql))

                violations = connection.execute(text(
                    "PRAGMA foreign_key_check"
                )).fetchall()
                if violations:
                    raise ValueError(
                        f"{table_name!r} rebuild left dangling foreign-key "
                        f"references: {violations!r}"
                    )
        finally:
            # Restored even if the rebuild raised, and outside any
            # transaction (the `with connection.begin()` block above has
            # already committed or rolled back by the time we get here).
            connection.exec_driver_sql(
                f"PRAGMA foreign_keys={'ON' if prior_foreign_keys else 'OFF'}"
            )
            connection.commit()


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


def _migrate_hosts_ssh_port(engine: Engine) -> None:
    """Add the port the provisioner connects to, defaulting to 22.

    NOT NULL with a default in the same statement, so pre-existing rows
    backfill as part of the ALTER rather than through a second pass that a
    partially-applied migration could skip.
    """
    _add_column_if_missing(
        engine, "hosts", "ssh_port", "INTEGER NOT NULL DEFAULT 22"
    )


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
               cr.executor_kind, cr.executor_target, h.pool_id, rp.provider,
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
        existing_executor_kind = row["executor_kind"]
        if existing_executor_kind is not None and (
            not isinstance(existing_executor_kind, str)
            or (
                existing_executor_kind.strip()
                and existing_executor_kind.strip() != "vm"
            )
        ):
            raise SchemaDriftError(
                f"legacy VM lease {row['lease_id']} conflicts with reservation "
                f"executor identity {existing_executor_kind!r}"
            )


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
            "SELECT capacity_reservation_id, state, scheduling_requirements, "
            "settlement_resource_id, pool_id, provider, resource_attributes, "
            "provider_metadata, teardown_provider_metadata, prepared_teardown_operation "
            "FROM settlement_records WHERE capacity_reservation_id=:id"
        ), {"id": draft.capacity_reservation_id}).mappings().one_or_none()
        requirements = {
            "executor_kind": draft.executor_kind,
            "resource_kind": "vm",
        }
        if existing:
            persisted_requirements = _normalize_json_column(
                existing["scheduling_requirements"]
            ) or {}
            if not isinstance(persisted_requirements, dict):
                raise SchemaDriftError(
                    f"settlement aggregate for reservation "
                    f"{draft.capacity_reservation_id} has invalid scheduling requirements"
                )
            persisted_executor_kind = persisted_requirements.get("executor_kind")
            if persisted_executor_kind is not None and (
                not isinstance(persisted_executor_kind, str)
                or (
                    persisted_executor_kind.strip()
                    and persisted_executor_kind.strip() != draft.executor_kind
                )
            ):
                raise SchemaDriftError(
                    f"settlement aggregate for reservation "
                    f"{draft.capacity_reservation_id} conflicts with VM executor identity"
                )
            if _existing_settlement_row_conflicts(existing, draft) or _existing_provisioned_resources_conflict(
                connection, draft.capacity_reservation_id, draft.provisioned_resource_id
            ):
                raise SchemaDriftError(
                    f"conflicting settlement aggregate for reservation {draft.capacity_reservation_id}"
                )
            requirements.update(persisted_requirements)
            requirements["executor_kind"] = draft.executor_kind

        # A successfully compiled candidate is bounded evidence from the
        # historical VM-lease table. Persist that exact identity on both
        # records; never infer it later from a selected pool or resource.
        connection.execute(
            text(
                "UPDATE capacity_reservations SET executor_kind=:executor_kind "
                "WHERE capacity_reservation_id=:reservation_id"
            ),
            {
                "executor_kind": draft.executor_kind,
                "reservation_id": draft.capacity_reservation_id,
            },
        )
        if existing:
            connection.execute(
                text(
                    "UPDATE settlement_records SET scheduling_requirements=:requirements "
                    "WHERE capacity_reservation_id=:reservation_id"
                ),
                {
                    "requirements": json.dumps(requirements, sort_keys=True),
                    "reservation_id": draft.capacity_reservation_id,
                },
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
            "requirements": json.dumps(requirements, sort_keys=True), "resource_id": draft.settlement_resource_id,
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
    """Apply the full reservation and capacity-accounting cutover.

    A single migration ID rather than several sequential ones: nothing
    built on this cutover has been deployed anywhere, so there is no
    intermediate, partially-migrated database to preserve compatibility
    with. Folding every related schema change in here (rather than
    registering each as its own dated migration) keeps the migration list
    reflecting only states a real database has actually been in.
    """
    _migrate_rename_site_allocations_to_capacity_reservations(engine)
    _migrate_capacity_reservations_settlement_resource_id(engine)
    _migrate_site_resources_pool_id(engine)
    _migrate_capacity_buckets_and_current_debits(engine)
    _migrate_retire_site_resources(engine)
    _migrate_remove_provisioned_resource_domain_ref(engine)
    _migrate_ansible_pool_requirement_delegate(engine)
    _migrate_capacity_reservations_vm_host_to_executor_ref(engine)
    _migrate_capacity_reservations_vm_target_to_executor_target(engine)


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


def _migrate_capacity_reservations_vm_host_to_executor_ref(engine: Engine) -> None:
    """Retire ``capacity_reservations.vm_host`` in favor of the generic
    ``executor_ref`` JSON field.

    ``kit/site`` carries no VM-domain-specific column names on the shared,
    domain-neutral reservation table -- physical placement identity lives
    uniformly in ``executor_ref`` across every domain, matching
    bare-metal's ``physical_host_id`` pattern (which was never given its
    own column). Backfills any existing ``vm_host`` value into
    ``executor_ref`` (merged via ``json_set``, not overwritten -- a row
    may already carry other ``executor_ref`` keys) before dropping the
    column. A no-op on a database created fresh from the current ORM
    model, which never had this column.
    """
    if not _table_exists(engine, "capacity_reservations"):
        return
    if not _column_exists(engine, "capacity_reservations", "vm_host"):
        return
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE capacity_reservations "
            "SET executor_ref = json_set(COALESCE(executor_ref, '{}'), '$.vm_host', vm_host) "
            "WHERE vm_host IS NOT NULL "
            "AND (executor_ref IS NULL OR json_extract(executor_ref, '$.vm_host') IS NULL)"
        ))
    _drop_columns_via_table_rebuild(engine, "capacity_reservations", ["vm_host"])


def _migrate_capacity_reservations_vm_target_to_executor_target(engine: Engine) -> None:
    """Retire ``capacity_reservations.vm_target`` in favor of the generic
    ``executor_target`` field.

    Unlike ``vm_host``, ``vm_target`` was never actually distinct from
    ``executor_target`` -- every reservation-binding write site sets both
    columns to the same value at the same time. This backfill exists only
    for defensiveness against a row where the two happened to diverge; on
    every row this repository's own code could have produced, it is a
    no-op. A no-op on a database created fresh from the current ORM
    model, which never had this column.
    """
    if not _table_exists(engine, "capacity_reservations"):
        return
    if not _column_exists(engine, "capacity_reservations", "vm_target"):
        return
    with engine.begin() as connection:
        connection.execute(text(
            "UPDATE capacity_reservations "
            "SET executor_target = vm_target "
            "WHERE vm_target IS NOT NULL AND executor_target IS NULL"
        ))
    _drop_columns_via_table_rebuild(engine, "capacity_reservations", ["vm_target"])


def _migrate_ansible_pool_config_vm_size_defaults(engine: Engine) -> None:
    """Add ``ansible_pool_configs``' optional VM size default columns.

    These back the fulfillment-time three-tier precedence's final
    fallback tier (see ``AnsiblePoolConfig.default_vm_ram`` and siblings);
    a NULL value on an existing row simply means that pool contributes
    nothing at that tier, matching its pre-migration behavior exactly.
    """
    _add_column_if_missing(engine, "ansible_pool_configs", "default_vm_ram", "INTEGER")
    _add_column_if_missing(engine, "ansible_pool_configs", "default_vm_vcpus", "INTEGER")
    _add_column_if_missing(engine, "ansible_pool_configs", "default_vm_disk_size", "VARCHAR")


def _migrate_hosts_gpu_model(engine: Engine) -> None:
    """Add ``hosts``' optional descriptive GPU model column.

    NULL on an existing row means the operator hasn't recorded a model
    yet, matching pre-migration behavior exactly -- it is not treated as
    "no GPU", which is what ``gpu_count`` already reports independently.
    """
    _add_column_if_missing(engine, "hosts", "gpu_model", "VARCHAR")
def _migrate_provisioning_replay_reservations(engine: Engine) -> None:
    """Create the durable request reservation and exact-outcome store."""

    with engine.begin() as connection:
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS provisioning_replay_reservations (
                principal_scheme VARCHAR NOT NULL,
                principal_identifier VARCHAR NOT NULL,
                request_id VARCHAR NOT NULL,
                request_hash VARCHAR NOT NULL,
                dispatch_lease_expires_at TIMESTAMP NOT NULL,
                dispatch_attempt_count INTEGER NOT NULL DEFAULT 1,
                response_status INTEGER,
                response_body JSON,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                response_body_empty BOOLEAN NOT NULL DEFAULT 0,
                response_media_type VARCHAR,
                completed_at TIMESTAMP,
                PRIMARY KEY (
                    principal_scheme,
                    principal_identifier,
                    request_id
                )
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS capacity_release_callback_outbox (
                capacity_reservation_id VARCHAR NOT NULL PRIMARY KEY,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                last_attempted_at TIMESTAMP,
                delivered_at TIMESTAMP
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS provisioning_trusted_principals (
                role VARCHAR NOT NULL,
                principal_scheme VARCHAR NOT NULL,
                principal_identifier VARCHAR NOT NULL,
                generation INTEGER NOT NULL,
                valid_until TIMESTAMP,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (role, principal_scheme, principal_identifier)
            )
            """
        ))
        connection.execute(text(
            """
            CREATE TABLE IF NOT EXISTS provisioning_identity_rotation_audit (
                nonce VARCHAR NOT NULL PRIMARY KEY,
                role VARCHAR NOT NULL,
                current_scheme VARCHAR NOT NULL,
                current_identifier VARCHAR NOT NULL,
                replacement_scheme VARCHAR NOT NULL,
                replacement_identifier VARCHAR NOT NULL,
                overlap_seconds INTEGER NOT NULL,
                intent_expires_at INTEGER NOT NULL,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        ))




_EXECUTOR_IDENTITY_QUARANTINE_REASON = "legacy_executor_identity_quarantined"
_ACTIVE_JOB_STATES = frozenset({"queued", "running"})
_HELD_RESERVATION_STATES = frozenset(
    {"reserved", "provisioning", "leased", "releasing", "release_failed", "unmanaged"}
)


def _json_mapping(value, *, label: str) -> dict:
    try:
        normalized = _normalize_json_column(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SchemaDriftError(f"{label} is not valid JSON: {exc}") from exc
    if normalized is None:
        return {}
    if not isinstance(normalized, dict):
        raise SchemaDriftError(f"{label} must be a JSON object")
    return dict(normalized)


def _legacy_executor_evidence(
    *,
    executor_ref=None,
    backing_attributes=None,
    deal_ref=None,
    scheduling_requirements=None,
    params=None,
) -> set[str]:
    """Return only executor identities proved by durable legacy fields."""
    evidence: set[str] = set()
    ref = _json_mapping(executor_ref, label="executor_ref")
    backing = _json_mapping(backing_attributes, label="capacity bucket attributes")
    deal = _json_mapping(deal_ref, label="deal_ref")
    requirements = _json_mapping(
        scheduling_requirements, label="scheduling_requirements"
    )
    job_params = _json_mapping(params, label="ansible job params")

    recorded = requirements.get("executor_kind") or job_params.get("executor_kind")
    if isinstance(recorded, str) and recorded.strip():
        evidence.add(recorded.strip())
    market = deal.get("market")
    if market == "vms":
        evidence.add("vm")
    elif market == "bare_metal":
        evidence.add("bare_metal")
    if ref.get("physical_host_id") or job_params.get("physical_host_id"):
        evidence.add("bare_metal")
    if ref.get("vm_host") or (
        job_params.get("vm_host") and not job_params.get("physical_host_id")
    ):
        evidence.add("vm")
    if backing.get("vm_host"):
        evidence.add("vm")
    if (
        backing.get("physical_host_id")
        and backing.get("allocation_mode") == "exclusive"
    ):
        evidence.add("bare_metal")
    return evidence


def _derive_pool_deliverable_modes(connection) -> None:
    """Derive exact pool mode sets from registered provider configuration."""
    if not _table_exists(connection, "resource_pools"):
        return
    config_rows = {}
    if _table_exists(connection, "ansible_pool_configs"):
        config_rows = {
            row["pool_id"]: row
            for row in connection.execute(
                text(
                    "SELECT pool_id, playbook_path, requirement_delegate "
                    "FROM ansible_pool_configs"
                )
            ).mappings()
        }
    pools = connection.execute(
        text("SELECT id, provider, policy_tags FROM resource_pools ORDER BY id")
    ).mappings()
    for pool in pools:
        modes: set[str] = set()
        config = config_rows.get(pool["id"])
        if (
            pool["provider"] == "ansible"
            and config is not None
            and config["requirement_delegate"] == "vm_management_v1"
            and isinstance(config["playbook_path"], str)
            and config["playbook_path"].strip()
        ):
            modes.add("vm")
        policy_tags = _json_mapping(
            pool["policy_tags"], label=f"pool {pool['id']!r} policy_tags"
        )
        policy_tags["deliverable_modes"] = sorted(modes)
        connection.execute(
            text(
                "UPDATE resource_pools SET policy_tags=:policy_tags "
                "WHERE id=:pool_id"
            ),
            {
                "pool_id": pool["id"],
                "policy_tags": json.dumps(policy_tags, sort_keys=True),
            },
        )
        logger.info(
            "[MIGRATION] Derived deliverable modes for pool %s: %s",
            pool["id"],
            ", ".join(sorted(modes)) or "none",
        )


def _migrate_executor_identities_and_pool_modes(engine: Engine) -> None:
    """Backfill proved executor identities and quarantine every unresolved row."""
    with engine.begin() as connection:
        _derive_pool_deliverable_modes(connection)

        job_rows: list[dict] = []
        job_evidence_by_reservation: dict[str, set[str]] = {}
        if _table_exists(connection, "ansible_jobs"):
            job_rows = list(
                connection.execute(
                    text(
                        "SELECT id, status, params, executor_kind, "
                        "capacity_reservation_id, error FROM ansible_jobs"
                    )
                ).mappings()
            )
            for job in job_rows:
                reservation_id = job["capacity_reservation_id"]
                if reservation_id is None:
                    continue
                existing_kind = job["executor_kind"]
                evidence = (
                    {existing_kind.strip()}
                    if isinstance(existing_kind, str) and existing_kind.strip()
                    else _legacy_executor_evidence(params=job["params"])
                )
                job_evidence_by_reservation.setdefault(
                    str(reservation_id), set()
                ).update(evidence)

        reservation_kinds: dict[str, str | None] = {}
        if _table_exists(connection, "capacity_reservations"):
            has_settlements = _table_exists(connection, "settlement_records")
            settlement_join = (
                "LEFT JOIN settlement_records sr "
                "ON sr.capacity_reservation_id=cr.capacity_reservation_id"
                if has_settlements
                else ""
            )
            settlement_column = (
                "sr.scheduling_requirements" if has_settlements else "NULL"
            )
            rows = list(
                connection.execute(
                    text(
                        "SELECT cr.capacity_reservation_id, cr.executor_kind, "
                        "cr.executor_ref, cr.deal_ref, cr.state, "
                        "cr.failure_reason, cb.attributes AS backing_attributes, "
                        f"{settlement_column} AS scheduling_requirements "
                        "FROM capacity_reservations cr "
                        "LEFT JOIN capacity_reservation_debits d "
                        "ON d.capacity_reservation_id=cr.capacity_reservation_id "
                        "LEFT JOIN capacity_buckets cb "
                        "ON cb.capacity_bucket_id=d.capacity_bucket_id "
                        f"{settlement_join}"
                    )
                ).mappings()
            )
            grouped: dict[str, dict] = {}
            for row in rows:
                reservation_id = str(row["capacity_reservation_id"])
                group = grouped.setdefault(
                    reservation_id,
                    {
                        "row": row,
                        "backing_evidence": set(),
                        "requirements": [],
                    },
                )
                group["backing_evidence"].update(
                    _legacy_executor_evidence(
                        backing_attributes=row["backing_attributes"]
                    )
                )
                if row["scheduling_requirements"] is not None:
                    group["requirements"].append(
                        _json_mapping(
                            row["scheduling_requirements"],
                            label=(
                                f"settlement {reservation_id!r} "
                                "scheduling_requirements"
                            ),
                        )
                    )

            for reservation_id, group in grouped.items():
                row = group["row"]
                existing_kind = row["executor_kind"]
                existing_kind = (
                    existing_kind.strip()
                    if isinstance(existing_kind, str) and existing_kind.strip()
                    else None
                )
                evidence = _legacy_executor_evidence(
                    executor_ref=row["executor_ref"],
                    deal_ref=row["deal_ref"],
                )
                for requirements in group["requirements"]:
                    recorded = requirements.get("executor_kind")
                    if isinstance(recorded, str) and recorded.strip():
                        evidence.add(recorded.strip())
                evidence.update(
                    job_evidence_by_reservation.get(reservation_id, set())
                )
                if existing_kind is None:
                    evidence.update(group["backing_evidence"])
                else:
                    evidence.add(existing_kind)

                executor_kind = next(iter(evidence)) if len(evidence) == 1 else None
                if executor_kind is not None:
                    if existing_kind is None:
                        connection.execute(
                            text(
                                "UPDATE capacity_reservations "
                                "SET executor_kind=:executor_kind "
                                "WHERE capacity_reservation_id=:reservation_id"
                            ),
                            {
                                "executor_kind": executor_kind,
                                "reservation_id": reservation_id,
                            },
                        )
                    for requirements in group["requirements"]:
                        if requirements.get("executor_kind") == executor_kind:
                            continue
                        requirements["executor_kind"] = executor_kind
                        connection.execute(
                            text(
                                "UPDATE settlement_records "
                                "SET scheduling_requirements=:requirements "
                                "WHERE capacity_reservation_id=:reservation_id"
                            ),
                            {
                                "requirements": json.dumps(
                                    requirements, sort_keys=True
                                ),
                                "reservation_id": reservation_id,
                            },
                        )
                    reservation_kinds[reservation_id] = executor_kind
                    continue

                state = (
                    "unmanaged"
                    if row["state"] in _HELD_RESERVATION_STATES
                    else row["state"]
                )
                detail = (
                    "conflicting evidence: " + ", ".join(sorted(evidence))
                    if evidence
                    else "no durable executor evidence"
                )
                message = f"Legacy executor identity is quarantined: {detail}"
                connection.execute(
                    text(
                        "UPDATE capacity_reservations SET state=:state, "
                        "failure_reason=CASE WHEN :quarantine_active "
                        "THEN :reason ELSE COALESCE(failure_reason, :reason) END, "
                        "failure_message=CASE WHEN :quarantine_active "
                        "THEN :message ELSE COALESCE(failure_message, :message) END "
                        "WHERE capacity_reservation_id=:reservation_id"
                    ),
                    {
                        "state": state,
                        "quarantine_active": (
                            row["state"] in _HELD_RESERVATION_STATES
                        ),
                        "reason": _EXECUTOR_IDENTITY_QUARANTINE_REASON,
                        "message": message,
                        "reservation_id": reservation_id,
                    },
                )
                if has_settlements:
                    connection.execute(
                        text(
                            "UPDATE settlement_records SET "
                            "state=CASE WHEN state IN "
                            "('assigned', 'dispatch_pending', 'dispatching', "
                            "'active', 'teardown_dispatch_pending', "
                            "'tearing_down', 'teardown_failed') "
                            "THEN 'failed' ELSE state END, "
                            "failure_reason=CASE WHEN state IN "
                            "('assigned', 'dispatch_pending', 'dispatching', "
                            "'active', 'teardown_dispatch_pending', "
                            "'tearing_down', 'teardown_failed') "
                            "THEN :reason ELSE COALESCE(failure_reason, :reason) END, "
                            "failure_message=CASE WHEN state IN "
                            "('assigned', 'dispatch_pending', 'dispatching', "
                            "'active', 'teardown_dispatch_pending', "
                            "'tearing_down', 'teardown_failed') "
                            "THEN :message ELSE COALESCE(failure_message, :message) END "
                            "WHERE capacity_reservation_id=:reservation_id"
                        ),
                        {
                            "reason": _EXECUTOR_IDENTITY_QUARANTINE_REASON,
                            "message": message,
                            "reservation_id": reservation_id,
                        },
                    )
                logger.warning(
                    "[MIGRATION] Quarantined reservation %s: %s",
                    reservation_id,
                    detail,
                )
                reservation_kinds[reservation_id] = None

        for job in job_rows:
            params = _json_mapping(
                job["params"], label=f"ansible job {job['id']!r} params"
            )
            existing_kind = job["executor_kind"]
            existing_kind = (
                existing_kind.strip()
                if isinstance(existing_kind, str) and existing_kind.strip()
                else None
            )
            reservation_id = job["capacity_reservation_id"]
            linked_kind = (
                reservation_kinds.get(str(reservation_id))
                if reservation_id is not None
                else None
            )
            linked_quarantined = (
                reservation_id is not None
                and str(reservation_id) in reservation_kinds
                and linked_kind is None
            )
            evidence = (
                {existing_kind}
                if existing_kind is not None
                else _legacy_executor_evidence(params=params)
            )
            if linked_kind is not None:
                evidence.add(linked_kind)
            executor_kind = (
                next(iter(evidence))
                if len(evidence) == 1 and not linked_quarantined
                else None
            )
            if executor_kind is not None:
                params["executor_kind"] = executor_kind
                connection.execute(
                    text(
                        "UPDATE ansible_jobs SET executor_kind=:executor_kind, "
                        "params=:params WHERE id=:job_id"
                    ),
                    {
                        "executor_kind": executor_kind,
                        "params": json.dumps(params, sort_keys=True),
                        "job_id": job["id"],
                    },
                )
                continue

            detail = (
                "linked reservation is quarantined"
                if linked_quarantined
                else (
                    "conflicting evidence: " + ", ".join(sorted(evidence))
                    if evidence
                    else "no durable executor evidence"
                )
            )
            status_value = (
                "failed"
                if job["status"] in _ACTIVE_JOB_STATES
                else job["status"]
            )
            connection.execute(
                text(
                    "UPDATE ansible_jobs SET status=:status, error=:error "
                    "WHERE id=:job_id"
                ),
                {
                    "status": status_value,
                    "error": (
                        "Legacy executor identity is quarantined: "
                        f"{detail}"
                        if job["status"] in _ACTIVE_JOB_STATES or not job["error"]
                        else job["error"]
                    ),
                    "job_id": job["id"],
                },
            )
            logger.warning(
                "[MIGRATION] Quarantined Ansible job %s: %s",
                job["id"],
                detail,
            )


MIGRATIONS: tuple[Migration, ...] = (
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
        "20260803_001_ansible_pool_config_vm_size_defaults",
        _migrate_ansible_pool_config_vm_size_defaults,
    ),
    Migration(
        "20260804_001_hosts_gpu_model",
        _migrate_hosts_gpu_model,
    ),
    Migration(
        "20260811_001_provisioning_replay_reservations",
        _migrate_provisioning_replay_reservations,
    ),
    Migration(
        "20260815_001_pool_declared_offering_modes",
        _migrate_executor_identities_and_pool_modes,
    ),
    Migration(
        "20260901_001_hosts_ssh_port",
        _migrate_hosts_ssh_port,
    ),
)
