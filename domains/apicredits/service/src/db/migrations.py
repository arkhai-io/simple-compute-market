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

import hashlib
import logging
from dataclasses import dataclass
from typing import Callable

from market_identity import Identity, IdentityScheme
from models.keys_model import (
    LEGACY_ISSUANCE_RESOURCE_ID,
    LEGACY_ISSUANCE_SERVICE,
    derive_credit_fulfillment_id,
    legacy_issuance_request_digest,
)
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
        connection.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                id VARCHAR PRIMARY KEY,
                applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
            )
        )


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


def _migrate_owner_principals(engine: Engine) -> None:
    """Normalize legacy wallet owners to canonical marketplace principals."""
    with engine.begin() as connection:
        rows = connection.execute(
            text("SELECT key_id, owner_scheme, owner_id FROM api_keys"),
        ).mappings()
        for row in rows:
            scheme = row["owner_scheme"]
            identifier = row["owner_id"]
            if scheme is None and identifier is None:
                continue
            if scheme is None or identifier is None:
                raise SchemaDriftError(
                    f"API key {row['key_id']!r} has an incomplete owner principal",
                )
            if scheme == "wallet":
                scheme = IdentityScheme.EIP191
            else:
                try:
                    scheme = IdentityScheme(str(scheme))
                except ValueError as exc:
                    raise SchemaDriftError(
                        f"API key {row['key_id']!r} has unknown owner scheme "
                        f"{row['owner_scheme']!r}",
                    ) from exc
            try:
                principal = Identity(scheme=scheme, identifier=str(identifier))
            except ValueError as exc:
                raise SchemaDriftError(
                    f"API key {row['key_id']!r} has a malformed owner principal",
                ) from exc
            connection.execute(
                text(
                    "UPDATE api_keys SET owner_scheme = :scheme, owner_id = :identifier "
                    "WHERE key_id = :key_id",
                ),
                {
                    "key_id": row["key_id"],
                    "scheme": principal.scheme.value,
                    "identifier": principal.identifier,
                },
            )


def _legacy_key_mode(escrow_uid: str, key_id: str) -> str:
    digest = hashlib.sha256(f"key:{escrow_uid}".encode()).hexdigest()
    return "new" if key_id == f"ak_{digest[:16]}" else "existing"


def _migrate_fulfillment_grants(engine: Engine) -> None:
    """Backfill historical settlement grants without guessing ambiguous rows."""

    columns = {
        "fulfillment_id": "VARCHAR",
        "obligation_ref": "VARCHAR",
        "mechanism": "VARCHAR",
        "service": "VARCHAR",
        "resource_id": "VARCHAR",
        "key_mode": "VARCHAR",
        "key_target_id": "VARCHAR",
        "owner_scheme": "VARCHAR",
        "owner_id": "VARCHAR",
        "request_digest": "VARCHAR",
        "capacity_reservation_id": "VARCHAR",
        "result_balance": "INTEGER",
    }
    known_columns = {
        str(column["name"]) for column in inspect(engine).get_columns("credit_grants")
    }
    with engine.begin() as connection:
        for name, sql_type in columns.items():
            if name not in known_columns:
                connection.execute(
                    text(f"ALTER TABLE credit_grants ADD COLUMN {name} {sql_type}")
                )

        rows = (
            connection.execute(
                text(
                    """
                SELECT grants.id, grants.key_id, grants.escrow_uid, grants.quantity,
                       grants.reason, grants.fulfillment_id, grants.obligation_ref,
                       grants.mechanism, grants.service, grants.resource_id,
                       grants.key_mode, grants.key_target_id, grants.owner_scheme,
                       grants.owner_id, grants.request_digest,
                       keys.owner_scheme AS key_owner_scheme,
                       keys.owner_id AS key_owner_id
                FROM credit_grants AS grants
                LEFT JOIN api_keys AS keys ON keys.key_id = grants.key_id
                ORDER BY grants.id
                """
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            escrow_uid = row["escrow_uid"]
            if escrow_uid is None:
                if row["reason"] == "issuance":
                    raise SchemaDriftError(
                        f"issuance grant {row['id']} has no historical escrow identity"
                    )
                continue
            if row["reason"] != "issuance":
                raise SchemaDriftError(
                    f"grant {row['id']} reuses an escrow identity for a non-issuance row"
                )
            if row["key_owner_scheme"] is None and row["key_owner_id"] is not None:
                raise SchemaDriftError(
                    f"grant {row['id']} references an ambiguously owned API key"
                )
            if row["key_owner_scheme"] is not None and row["key_owner_id"] is None:
                raise SchemaDriftError(
                    f"grant {row['id']} references an ambiguously owned API key"
                )

            obligation_ref = str(escrow_uid)
            fulfillment_id = derive_credit_fulfillment_id(obligation_ref)
            key_id = str(row["key_id"])
            key_mode = _legacy_key_mode(obligation_ref, key_id)
            key_target_id = key_id if key_mode == "existing" else None
            owner = (
                Identity(
                    scheme=IdentityScheme(str(row["key_owner_scheme"])),
                    identifier=str(row["key_owner_id"]),
                )
                if row["key_owner_scheme"] is not None
                and row["key_owner_id"] is not None
                else None
            )
            expected = {
                "fulfillment_id": fulfillment_id,
                "obligation_ref": obligation_ref,
                "mechanism": "alkahest.v1",
                "service": LEGACY_ISSUANCE_SERVICE,
                "resource_id": LEGACY_ISSUANCE_RESOURCE_ID,
                "key_mode": key_mode,
                "key_target_id": key_target_id,
                "owner_scheme": row["key_owner_scheme"],
                "owner_id": row["key_owner_id"],
                "request_digest": legacy_issuance_request_digest(
                    fulfillment_id=fulfillment_id,
                    obligation_ref=obligation_ref,
                    key_id=key_id,
                    key_mode=key_mode,
                    owner=owner,
                    quantity=int(row["quantity"]),
                ),
            }
            for name, value in expected.items():
                current = row[name]
                if current is not None and current != value:
                    raise SchemaDriftError(
                        f"grant {row['id']} has conflicting {name} during migration"
                    )
            connection.execute(
                text(
                    """
                    UPDATE credit_grants
                    SET fulfillment_id=:fulfillment_id,
                        obligation_ref=:obligation_ref,
                        mechanism=:mechanism,
                        service=:service,
                        resource_id=:resource_id,
                        key_mode=:key_mode,
                        key_target_id=:key_target_id,
                        owner_scheme=:owner_scheme,
                        owner_id=:owner_id,
                        request_digest=:request_digest
                    WHERE id=:id
                    """
                ),
                {"id": row["id"], **expected},
            )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS "
                "uq_credit_grants_fulfillment_id "
                "ON credit_grants(fulfillment_id) "
                "WHERE fulfillment_id IS NOT NULL"
            )
        )


_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        "20260731_001_apicredits_schema_baseline",
        _adopt_baseline_schema,
    ),
    Migration(
        "20260811_002_canonical_owner_principals",
        _migrate_owner_principals,
    ),
    Migration(
        "20260815_003_fulfillment_grants",
        _migrate_fulfillment_grants,
    ),
)
