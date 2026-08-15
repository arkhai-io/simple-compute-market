"""Versioned schema migrations for the storefront market-state database.

``SQLiteClient`` creates missing tables during startup, but SQLite does not
alter existing tables to match new model columns. Keep additive compatibility
changes here so persisted storefront DBs can upgrade across image versions.

This module owns the migration engine plus the domain-neutral migrations
(negotiation/escrow/listing tables). Domain composition roots keep their
own inventory migrations and pass them through
``SQLiteClient._domain_migrations``.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from market_identity import Identity

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LegacyMigrationInputs:
    """Explicit domain-owned inputs for one legacy database migration."""

    accepted_escrows_synthesizer: (
        Callable[[Any], list[dict[str, Any]] | None] | None
    ) = None


@dataclass(frozen=True)
class Migration:
    id: str
    apply: Callable[[sqlite3.Connection], None]
    apply_with_identity_context: Callable[
        [sqlite3.Connection, Identity | None, Collection[str]], None
    ] | None = None
    apply_with_legacy_context: Callable[
        [sqlite3.Connection, LegacyMigrationInputs | None], None
    ] | None = None


class MigrationLike(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def apply(self) -> Callable[[sqlite3.Connection], None]: ...


def apply_schema_migrations(
    conn: sqlite3.Connection,
    extra_migrations: Sequence[MigrationLike] = (),
    *,
    local_listing_principal: Identity | None = None,
    expected_legacy_sellers: Collection[str] = (),
    legacy_inputs: LegacyMigrationInputs | None = None,
) -> None:
    """Apply all known migrations once, tracking completion in the database.

    ``extra_migrations`` carries the domain composition root's own
    migrations; they run after the core set, keyed by the same
    once-per-id tracking table.
    """
    _ensure_schema_migrations_table(conn)
    applied = _applied_migration_ids(conn)

    for migration in (*_MIGRATIONS, *extra_migrations):
        if migration.id in applied:
            continue
        savepoint = "schema_migration"
        conn.execute(f"SAVEPOINT {savepoint}")
        try:
            identity_contextual = getattr(
                migration, "apply_with_identity_context", None
            )
            legacy_contextual = getattr(
                migration, "apply_with_legacy_context", None
            )
            if identity_contextual is not None and legacy_contextual is not None:
                raise RuntimeError(
                    f"migration {migration.id!r} declares two context owners"
                )
            if identity_contextual is not None:
                identity_contextual(
                    conn,
                    local_listing_principal,
                    expected_legacy_sellers,
                )
            elif legacy_contextual is not None:
                legacy_contextual(conn, legacy_inputs)
            else:
                migration.apply(conn)
            _record_migration(conn, migration.id)
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
        except Exception:
            conn.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            conn.execute(f"RELEASE SAVEPOINT {savepoint}")
            raise


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
          id TEXT PRIMARY KEY,
          applied_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
        """
    )


def _applied_migration_ids(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT id FROM schema_migrations").fetchall()
    return {str(row[0]) for row in rows}


def _record_migration(conn: sqlite3.Connection, migration_id: str) -> None:
    conn.execute(
        "INSERT INTO schema_migrations (id) VALUES (?)",
        (migration_id,),
    )


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    if not _table_exists(conn, table_name):
        return False
    return column_name in {
        str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")
    }


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
    column_sql: str,
) -> None:
    if not _table_exists(conn, table_name) or _column_exists(
        conn, table_name, column_name
    ):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


# ---------------------------------------------------------------------------
# Legacy accepted_escrows backfill — synthesis is domain vocabulary.
# ---------------------------------------------------------------------------


def _backfill_accepted_escrows(
    conn: sqlite3.Connection,
    legacy_inputs: LegacyMigrationInputs | None,
) -> None:
    synthesizer = (
        legacy_inputs.accepted_escrows_synthesizer
        if legacy_inputs is not None
        else None
    )
    if synthesizer is None:
        return
    rows = conn.execute(
        "SELECT listing_id, demand_resource FROM listings "
        "WHERE accepted_escrows IS NULL AND demand_resource IS NOT NULL"
    ).fetchall()
    for listing_id, demand_resource in rows:
        synthesized = synthesizer(demand_resource)
        if not synthesized:
            continue
        conn.execute(
            "UPDATE listings SET accepted_escrows=? WHERE listing_id=?",
            (json.dumps(synthesized), listing_id),
        )


def _column_types(conn: sqlite3.Connection, table_name: str) -> dict[str, str]:
    return {
        str(row[1]): str(row[2] or "").upper()
        for row in conn.execute(f"PRAGMA table_info({table_name})")
    }


def _needs_rebuild(
    conn: sqlite3.Connection,
    table_name: str,
    columns: tuple[str, ...],
) -> bool:
    if not _table_exists(conn, table_name):
        return False
    types = _column_types(conn, table_name)
    return any(types.get(column) != "TEXT" for column in columns)


def _migrate_negotiation_amount_columns(conn: sqlite3.Connection) -> None:
    """Move EVM amount columns off SQLite INTEGER affinity."""
    if _table_exists(conn, "negotiation_threads"):
        for column_name, column_sql in (
            ("buyer", "TEXT"),
            ("matched_offer_id", "TEXT"),
        ):
            _add_column_if_missing(conn, "negotiation_threads", column_name, column_sql)

    if _needs_rebuild(conn, "negotiation_threads", ("agreed_price",)):
        conn.execute("DROP TABLE IF EXISTS negotiation_threads__amount_migration")
        conn.execute(
            "ALTER TABLE negotiation_threads RENAME TO negotiation_threads__amount_migration"
        )
        conn.execute(
            """
            CREATE TABLE negotiation_threads (
              negotiation_id TEXT PRIMARY KEY,
              our_listing_id TEXT,
              their_listing_id TEXT,
              our_agent_id TEXT,
              their_agent_id TEXT,
              status TEXT DEFAULT 'active',
              created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
              updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
              terminal_state TEXT,
              requested_duration_seconds INTEGER,
              requested_start_utc TEXT,
              buyer_escrow_proposal TEXT,
              provision_terms TEXT,
              agreed_price TEXT,
              agreed_duration_seconds INTEGER,
              agreed_at TEXT,
              buyer TEXT,
              matched_offer_id TEXT
            )
            """
        )
        conn.execute(
            """
            INSERT INTO negotiation_threads (
                negotiation_id, our_listing_id, their_listing_id,
                our_agent_id, their_agent_id, status, created_at,
                updated_at, terminal_state, requested_duration_seconds,
                requested_start_utc, buyer_escrow_proposal, provision_terms,
                agreed_price, agreed_duration_seconds, agreed_at, buyer,
                matched_offer_id
            )
            SELECT negotiation_id, our_listing_id, their_listing_id,
                   our_agent_id, their_agent_id, status, created_at,
                   updated_at, terminal_state, requested_duration_seconds,
                   NULL,
                   buyer_escrow_proposal,
                   provision_terms,
                   CASE WHEN agreed_price IS NULL THEN NULL ELSE CAST(agreed_price AS TEXT) END,
                   agreed_duration_seconds, agreed_at, buyer, matched_offer_id
            FROM negotiation_threads__amount_migration
            """
        )
        conn.execute("DROP TABLE negotiation_threads__amount_migration")

    if _needs_rebuild(conn, "negotiation_local_state", ("our_initial_price",)):
        conn.execute("DROP TABLE IF EXISTS negotiation_local_state__amount_migration")
        conn.execute(
            "ALTER TABLE negotiation_local_state RENAME TO negotiation_local_state__amount_migration"
        )
        conn.execute(
            """
            CREATE TABLE negotiation_local_state (
              negotiation_id TEXT NOT NULL,
              owner_id TEXT NOT NULL,
              our_initial_price TEXT,
              our_strategy TEXT,
              PRIMARY KEY(negotiation_id, owner_id),
              FOREIGN KEY(negotiation_id) REFERENCES negotiation_threads(negotiation_id)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO negotiation_local_state (
                negotiation_id, owner_id, our_initial_price, our_strategy
            )
            SELECT negotiation_id, owner_id,
                   CASE WHEN our_initial_price IS NULL THEN NULL ELSE CAST(our_initial_price AS TEXT) END,
                   our_strategy
            FROM negotiation_local_state__amount_migration
            """
        )
        conn.execute("DROP TABLE negotiation_local_state__amount_migration")

    if _needs_rebuild(
        conn,
        "negotiation_messages",
        ("our_price", "their_price", "proposed_price"),
    ):
        conn.execute("DROP TABLE IF EXISTS negotiation_messages__amount_migration")
        conn.execute(
            "ALTER TABLE negotiation_messages RENAME TO negotiation_messages__amount_migration"
        )
        conn.execute(
            """
            CREATE TABLE negotiation_messages (
              message_id INTEGER PRIMARY KEY AUTOINCREMENT,
              negotiation_id TEXT NOT NULL,
              round INTEGER NOT NULL,
              sender TEXT NOT NULL,
              our_price TEXT,
              their_price TEXT,
              proposed_price TEXT,
              action_taken TEXT NOT NULL,
              message_type TEXT NOT NULL,
              timestamp TEXT NOT NULL,
              FOREIGN KEY(negotiation_id) REFERENCES negotiation_threads(negotiation_id),
              UNIQUE(negotiation_id, round)
            )
            """
        )
        conn.execute(
            """
            INSERT INTO negotiation_messages (
                message_id, negotiation_id, round, sender,
                our_price, their_price, proposed_price,
                action_taken, message_type, timestamp
            )
            SELECT message_id, negotiation_id, round, sender,
                   CASE WHEN our_price IS NULL THEN NULL ELSE CAST(our_price AS TEXT) END,
                   CASE WHEN their_price IS NULL THEN NULL ELSE CAST(their_price AS TEXT) END,
                   CASE WHEN proposed_price IS NULL THEN NULL ELSE CAST(proposed_price AS TEXT) END,
                   action_taken, message_type, timestamp
            FROM negotiation_messages__amount_migration
            """
        )
        conn.execute("DROP TABLE negotiation_messages__amount_migration")


def _cols(conn: sqlite3.Connection, table_name: str) -> set[str]:
    if not _table_exists(conn, table_name):
        return set()
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def _drop_column_if_exists(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> None:
    if not _column_exists(conn, table_name, column_name):
        return
    try:
        conn.execute(f"ALTER TABLE {table_name} DROP COLUMN {column_name}")
    except sqlite3.OperationalError:
        pass


def _migrate_escrows_and_listings(
    conn: sqlite3.Connection,
    legacy_inputs: LegacyMigrationInputs | None = None,
) -> None:
    """Migrate legacy settlement/listing columns with explicit domain input."""
    if _table_exists(conn, "settlement_jobs") and not _table_exists(conn, "escrows"):
        conn.execute("ALTER TABLE settlement_jobs RENAME TO escrows")
        for old_idx in (
            "idx_settlement_jobs_status",
            "idx_settlement_jobs_negotiation",
        ):
            conn.execute(f"DROP INDEX IF EXISTS {old_idx}")

    if _table_exists(conn, "escrows"):
        for column_name, column_sql in (
            ("chain_name", "TEXT"),
            ("escrow_address", "TEXT"),
            ("is_primary", "INTEGER NOT NULL DEFAULT 1"),
            ("fulfillment_uid", "TEXT"),
        ):
            _add_column_if_missing(conn, "escrows", column_name, column_sql)

    if _table_exists(conn, "negotiation_threads"):
        for column_name, column_sql in (
            ("buyer", "TEXT"),
            ("matched_offer_id", "TEXT"),
        ):
            _add_column_if_missing(conn, "negotiation_threads", column_name, column_sql)

    if _table_exists(conn, "listings"):
        for column_name, column_sql in (
            ("accepted_escrows", "TEXT"),
            ("demands", "TEXT"),
        ):
            _add_column_if_missing(conn, "listings", column_name, column_sql)
        if _column_exists(conn, "listings", "demand_resource"):
            _backfill_accepted_escrows(conn, legacy_inputs)

    listing_cols = _cols(conn, "listings")
    escrow_cols = _cols(conn, "escrows")

    if "attestation_uid" in escrow_cols:
        conn.execute(
            "UPDATE escrows SET fulfillment_uid = attestation_uid "
            "WHERE fulfillment_uid IS NULL AND attestation_uid IS NOT NULL"
        )

    if (
        "accepted_escrows" in listing_cols
        and _table_exists(conn, "escrows")
        and _table_exists(conn, "negotiation_threads")
    ):
        rows = conn.execute(
            """
            SELECT escrows.escrow_uid, l.accepted_escrows
            FROM escrows
            JOIN negotiation_threads nt
              ON nt.negotiation_id = escrows.negotiation_id
            JOIN listings l
              ON l.listing_id = nt.our_listing_id
            WHERE escrows.chain_name IS NULL OR escrows.escrow_address IS NULL
            """
        ).fetchall()
        for escrow_uid, ae_blob in rows:
            if not ae_blob:
                continue
            try:
                ae_list = json.loads(ae_blob) if isinstance(ae_blob, str) else ae_blob
            except (ValueError, TypeError):
                continue
            if not isinstance(ae_list, list) or not ae_list:
                continue
            first = ae_list[0]
            if not isinstance(first, dict):
                continue
            conn.execute(
                "UPDATE escrows SET chain_name = ?, escrow_address = ? "
                "WHERE escrow_uid = ?",
                (first.get("chain_name"), first.get("escrow_address"), escrow_uid),
            )

    if "buyer" in listing_cols and _table_exists(conn, "negotiation_threads"):
        conn.execute(
            """
            UPDATE negotiation_threads
            SET buyer = (
                SELECT l.buyer FROM listings l
                WHERE l.listing_id = negotiation_threads.our_listing_id
                LIMIT 1
            )
            WHERE buyer IS NULL
            """
        )
    if "matched_offer_id" in listing_cols and _table_exists(
        conn, "negotiation_threads"
    ):
        conn.execute(
            """
            UPDATE negotiation_threads
            SET matched_offer_id = (
                SELECT l.matched_offer_id FROM listings l
                WHERE l.listing_id = negotiation_threads.our_listing_id
                LIMIT 1
            )
            WHERE matched_offer_id IS NULL
            """
        )

    for table_name, column_name in (
        ("escrows", "attestation_uid"),
        ("listings", "demand_resource"),
        ("listings", "escrow_uid"),
        ("listings", "buyer_attestation"),
        ("listings", "seller_attestation"),
        ("listings", "buyer"),
        ("listings", "matched_offer_id"),
    ):
        _drop_column_if_exists(conn, table_name, column_name)


def _migrate_listing_resource_timestamps(conn: sqlite3.Connection) -> None:
    for table_name in ("listings", "resources"):
        _add_column_if_missing(conn, table_name, "created_at", "TEXT")
        _add_column_if_missing(conn, table_name, "updated_at", "TEXT")
        if _table_exists(conn, table_name):
            conn.execute(
                f"""
                UPDATE {table_name}
                SET created_at = COALESCE(
                      created_at,
                      STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    ),
                    updated_at = COALESCE(
                      updated_at,
                      STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
                    )
                """
            )


def _migrate_capacity_holds_reservation_id(conn: sqlite3.Connection) -> None:
    """Rename ``capacity_holds.allocation_id`` to ``capacity_holds.
    capacity_reservation_id``.

    ``capacity_holds`` is created unconditionally via ``CREATE TABLE IF
    NOT EXISTS`` (SQLiteClient.init_db), not through this versioned
    migration system, so an existing on-disk database still has the old
    column name and needs this rename step; a fresh database already has
    the current column from that CREATE TABLE statement, and
    ``_column_exists`` below is what makes this a no-op in that case.
    """
    if _column_exists(conn, "capacity_holds", "allocation_id"):
        conn.execute(
            "ALTER TABLE capacity_holds "
            "RENAME COLUMN allocation_id TO capacity_reservation_id"
        )


def _migrate_negotiation_provision_terms(conn: sqlite3.Connection) -> None:
    if _table_exists(conn, "negotiation_threads"):
        _add_column_if_missing(
            conn,
            "negotiation_threads",
            "provision_terms",
            "TEXT",
        )
        _add_column_if_missing(
            conn,
            "negotiation_threads",
            "settlement_plan",
            "TEXT",
        )


_LEGACY_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _legacy_principal(
    value: Any,
    *,
    field: str,
    casing: dict[str, str],
) -> tuple[str, str]:
    if not isinstance(value, str) or not _LEGACY_ADDRESS.fullmatch(value):
        raise ValueError(f"{field} is not a valid legacy EIP-191 address")
    identifier = value.lower()
    prior = casing.get(identifier)
    if prior is not None and prior != value:
        raise ValueError(f"{field} has checksum/casing drift for one address")
    casing[identifier] = value
    return "eip191", identifier


def _validated_principal(
    scheme: Any,
    identifier: Any,
    *,
    field: str,
) -> tuple[str, str]:
    try:
        from market_identity import Identity

        principal = Identity(scheme=scheme, identifier=identifier)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} principal is incomplete or unsupported") from exc
    return principal.scheme.value, principal.identifier


def _principal_dict(value: tuple[str, str]) -> dict[str, str]:
    return {"scheme": value[0], "identifier": value[1]}


def _require_json_object(value: Any, *, field: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} contains malformed JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"{field} must contain a JSON object")
    return parsed


def _require_embedded_principal(
    value: Any,
    *,
    expected: tuple[str, str],
    field: str,
) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{field} principal is malformed")
    actual = _validated_principal(
        value.get("scheme"),
        value.get("identifier"),
        field=field,
    )
    if actual != expected:
        raise ValueError(f"{field} principal conflicts with durable negotiation parties")


def _migrate_settlement_plan_parties(
    value: Any,
    *,
    buyer: tuple[str, str],
    seller: tuple[str, str],
    field: str,
) -> str:
    plan = _require_json_object(value, field=field)
    for key, expected in (
        ("buyer_principal", buyer),
        ("seller_principal", seller),
    ):
        if key in plan:
            _require_embedded_principal(plan[key], expected=expected, field=f"{field}.{key}")
        else:
            plan[key] = _principal_dict(expected)
    obligations = plan.get("obligations")
    if obligations is not None:
        if not isinstance(obligations, list):
            raise ValueError(f"{field}.obligations must be a list")
        parties = {"buyer": buyer, "seller": seller}
        for index, obligation in enumerate(obligations):
            if not isinstance(obligation, dict):
                raise ValueError(f"{field}.obligations[{index}] is malformed")
            for role_key, principal_key in (
                ("payer", "payer_principal"),
                ("claimant", "claimant_principal"),
            ):
                role = obligation.get(role_key)
                if role not in parties:
                    raise ValueError(
                        f"{field}.obligations[{index}].{role_key} is invalid"
                    )
                expected = parties[role]
                if principal_key in obligation:
                    _require_embedded_principal(
                        obligation[principal_key],
                        expected=expected,
                        field=f"{field}.obligations[{index}].{principal_key}",
                    )
                else:
                    obligation[principal_key] = _principal_dict(expected)
    return json.dumps(plan, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _migrate_stage_event_identity(value: Any, *, casing: dict[str, str]) -> str:
    event = _require_json_object(value, field="stage_events.data")
    version = event.get("version", 1)
    if version not in {1, 2}:
        raise ValueError("stage event has an unsupported run-log version")
    for legacy, current in (
        ("buyer_address", "buyer_principal"),
        ("seller_address", "seller_principal"),
        ("signer", "actor_principal"),
    ):
        if legacy not in event:
            continue
        if current in event:
            raise ValueError(f"stage event contains both {legacy} and {current}")
        event[current] = _principal_dict(
            _legacy_principal(
                event.pop(legacy),
                field=f"stage_events.data.{legacy}",
                casing=casing,
            )
        )
    event["version"] = 2
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _canonical_storefront_url(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty storefront URL")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{field} is not a well-formed public storefront URL")
    path = parsed.path.rstrip("/")
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            path,
            "",
            "",
        )
    )


def _rebuild_replay_reservations_without_legacy_principal(
    conn: sqlite3.Connection,
    *,
    legacy_column: str,
) -> None:
    """Re-key a legacy replay table on the complete canonical principal."""

    columns = _cols(conn, "auth_replay_reservations")
    if legacy_column not in columns:
        raise ValueError("legacy replay principal column disappeared during migration")
    required = {
        "principal_scheme",
        "principal_identifier",
        "request_id",
        "request_hash",
        "created_at",
    }
    missing = required - columns
    if missing:
        raise ValueError(
            "auth_replay_reservations lacks required replay fields: "
            + ", ".join(sorted(missing))
        )
    optional = {
        name: name if name in columns else "NULL"
        for name in (
            "response_status",
            "response_body",
            "attempt_token",
            "lease_until",
        )
    }
    conn.execute("DROP TABLE IF EXISTS auth_replay_reservations_identity_new")
    conn.execute(
        """
        CREATE TABLE auth_replay_reservations_identity_new (
          principal_scheme TEXT NOT NULL,
          principal_identifier TEXT NOT NULL,
          request_id TEXT NOT NULL,
          request_hash TEXT NOT NULL,
          response_status INTEGER,
          response_body TEXT,
          attempt_token TEXT,
          lease_until INTEGER,
          created_at TEXT NOT NULL,
          PRIMARY KEY (principal_scheme, principal_identifier, request_id)
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO auth_replay_reservations_identity_new (
          principal_scheme, principal_identifier, request_id, request_hash,
          response_status, response_body, attempt_token, lease_until, created_at
        )
        SELECT principal_scheme, principal_identifier, request_id, request_hash,
               {optional["response_status"]}, {optional["response_body"]},
               {optional["attempt_token"]}, {optional["lease_until"]}, created_at
        FROM auth_replay_reservations
        """
    )
    conn.execute("DROP TABLE auth_replay_reservations")
    conn.execute(
        "ALTER TABLE auth_replay_reservations_identity_new "
        "RENAME TO auth_replay_reservations"
    )


def _rebuild_service_peers_without_legacy_identity(
    conn: sqlite3.Connection,
    *,
    legacy_column: str,
) -> None:
    """Replace legacy peer identity constraints with canonical principal keys."""

    columns = _cols(conn, "service_peers")
    required = {
        "peer_id",
        "role",
        "site_id",
        "principal_scheme",
        "principal_identifier",
    }
    if legacy_column not in columns:
        raise ValueError("legacy service-peer identity disappeared during migration")
    missing = required - columns
    if missing:
        raise ValueError(
            "service_peers lacks required binding fields: "
            + ", ".join(sorted(missing))
        )
    status = "status" if "status" in columns else "'active'"
    created_at = "created_at" if "created_at" in columns else "'1970-01-01T00:00:00+00:00'"
    updated_at = "updated_at" if "updated_at" in columns else created_at
    conn.execute("DROP TABLE IF EXISTS service_peers_identity_new")
    conn.execute(
        """
        CREATE TABLE service_peers_identity_new (
          peer_id TEXT PRIMARY KEY,
          role TEXT NOT NULL,
          site_id TEXT NOT NULL,
          principal_scheme TEXT NOT NULL,
          principal_identifier TEXT NOT NULL,
          status TEXT NOT NULL CHECK (status IN ('active', 'disabled', 'retired')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE (role, site_id),
          UNIQUE (role, principal_scheme, principal_identifier)
        )
        """
    )
    conn.execute(
        f"""
        INSERT INTO service_peers_identity_new (
          peer_id, role, site_id, principal_scheme, principal_identifier,
          status, created_at, updated_at
        )
        SELECT peer_id, role, site_id, principal_scheme, principal_identifier,
               {status}, {created_at}, {updated_at}
        FROM service_peers
        """
    )
    conn.execute("DROP TABLE service_peers")
    conn.execute(
        "ALTER TABLE service_peers_identity_new RENAME TO service_peers"
    )


def _migrate_marketplace_principals(
    conn: sqlite3.Connection,
    local_listing_principal: Identity | None = None,
    expected_legacy_sellers: Collection[str] = (),
) -> None:
    casing: dict[str, str] = {}
    listing_parties: dict[str, tuple[str, str]] = {}

    if _table_exists(conn, "listings"):
        _add_column_if_missing(conn, "listings", "storefront_url", "TEXT")
        _add_column_if_missing(conn, "listings", "seller_scheme", "TEXT")
        _add_column_if_missing(conn, "listings", "seller_identifier", "TEXT")
        columns = _cols(conn, "listings")
        legacy_column = "seller" if "seller" in columns else None
        select_legacy = legacy_column or "NULL"
        rows = conn.execute(
            f"""
            SELECT listing_id, {select_legacy}, storefront_url,
                   seller_scheme, seller_identifier
            FROM listings
            """
        ).fetchall()
        if rows and local_listing_principal is None:
            raise ValueError(
                "populated listings require the configured local marketplace principal"
            )
        expected_urls = {
            _canonical_storefront_url(
                value,
                field="expected legacy storefront URL",
            )
            for value in expected_legacy_sellers
        }
        if rows and not expected_urls:
            raise ValueError(
                "populated listings require an expected local storefront URL"
            )
        principal = (
            (
                local_listing_principal.scheme.value,
                local_listing_principal.identifier,
            )
            if local_listing_principal is not None
            else None
        )
        for listing_id, legacy, current_url, scheme, identifier in rows:
            legacy_url = (
                _canonical_storefront_url(
                    legacy,
                    field=f"listings[{listing_id}].seller",
                )
                if legacy is not None
                else None
            )
            stored_url = (
                _canonical_storefront_url(
                    current_url,
                    field=f"listings[{listing_id}].storefront_url",
                )
                if current_url is not None
                else None
            )
            if legacy_url is not None and stored_url is not None and legacy_url != stored_url:
                raise ValueError(
                    f"listings[{listing_id}] storefront URL conflicts with its legacy value"
                )
            storefront_url = stored_url or legacy_url
            if storefront_url is None or storefront_url not in expected_urls:
                raise ValueError(
                    f"listings[{listing_id}] belongs to an unexpected storefront URL"
                )
            assert principal is not None
            if scheme is None and identifier is None:
                pass
            elif scheme is None or identifier is None:
                raise ValueError(f"listings[{listing_id}] has a partial seller principal")
            elif _validated_principal(
                scheme,
                identifier,
                field=f"listings[{listing_id}].seller_principal",
            ) != principal:
                raise ValueError(
                    f"listings[{listing_id}] seller principal conflicts with local identity"
                )
            conn.execute(
                """
                UPDATE listings
                SET storefront_url=?, seller_scheme=?, seller_identifier=?
                WHERE listing_id=?
                """,
                (storefront_url, *principal, listing_id),
            )
            listing_parties[str(listing_id)] = principal
        if legacy_column is not None:
            _drop_column_if_exists(conn, "listings", legacy_column)

    thread_parties: dict[str, tuple[tuple[str, str], tuple[str, str]]] = {}
    if _table_exists(conn, "negotiation_threads"):
        for name in (
            "buyer_scheme",
            "buyer_identifier",
            "seller_scheme",
            "seller_identifier",
        ):
            _add_column_if_missing(conn, "negotiation_threads", name, "TEXT")
        columns = _cols(conn, "negotiation_threads")
        has_legacy_buyer = "buyer" in columns
        select_buyer = "buyer" if has_legacy_buyer else "NULL"
        rows = conn.execute(
            f"""
            SELECT negotiation_id, our_listing_id, {select_buyer},
                   buyer_scheme, buyer_identifier,
                   seller_scheme, seller_identifier, settlement_plan
            FROM negotiation_threads
            """
        ).fetchall()
        for row in rows:
            (
                negotiation_id,
                listing_id,
                legacy_buyer,
                buyer_scheme,
                buyer_identifier,
                seller_scheme,
                seller_identifier,
                settlement_plan,
            ) = row
            if buyer_scheme is None and buyer_identifier is None:
                buyer = _legacy_principal(
                    legacy_buyer,
                    field=f"negotiation_threads[{negotiation_id}].buyer",
                    casing=casing,
                )
            elif buyer_scheme is None or buyer_identifier is None:
                raise ValueError(
                    f"negotiation_threads[{negotiation_id}] has a partial buyer principal"
                )
            else:
                buyer = _validated_principal(
                    buyer_scheme,
                    buyer_identifier,
                    field=f"negotiation_threads[{negotiation_id}].buyer",
                )

            if seller_scheme is None and seller_identifier is None:
                seller = listing_parties.get(str(listing_id))
                if seller is None:
                    raise ValueError(
                        f"negotiation_threads[{negotiation_id}] has no seller ownership"
                    )
            elif seller_scheme is None or seller_identifier is None:
                raise ValueError(
                    f"negotiation_threads[{negotiation_id}] has a partial seller principal"
                )
            else:
                seller = _validated_principal(
                    seller_scheme,
                    seller_identifier,
                    field=f"negotiation_threads[{negotiation_id}].seller",
                )
            conn.execute(
                """
                UPDATE negotiation_threads
                SET buyer_scheme=?, buyer_identifier=?,
                    seller_scheme=?, seller_identifier=?
                WHERE negotiation_id=?
                """,
                (*buyer, *seller, negotiation_id),
            )
            if settlement_plan is not None:
                migrated_plan = _migrate_settlement_plan_parties(
                    settlement_plan,
                    buyer=buyer,
                    seller=seller,
                    field=f"negotiation_threads[{negotiation_id}].settlement_plan",
                )
                conn.execute(
                    "UPDATE negotiation_threads SET settlement_plan=? "
                    "WHERE negotiation_id=?",
                    (migrated_plan, negotiation_id),
                )
            thread_parties[str(negotiation_id)] = (buyer, seller)
        if has_legacy_buyer:
            _drop_column_if_exists(conn, "negotiation_threads", "buyer")

    if _table_exists(conn, "negotiation_messages"):
        _add_column_if_missing(conn, "negotiation_messages", "sender_role", "TEXT")
        _add_column_if_missing(conn, "negotiation_messages", "sender_scheme", "TEXT")
        _add_column_if_missing(conn, "negotiation_messages", "sender_identifier", "TEXT")
        columns = _cols(conn, "negotiation_messages")
        has_legacy_sender = "sender" in columns
        select_sender = "sender" if has_legacy_sender else "NULL"
        rows = conn.execute(
            f"""
            SELECT message_id, negotiation_id, {select_sender},
                   sender_role, sender_scheme, sender_identifier
            FROM negotiation_messages
            """
        ).fetchall()
        for message_id, negotiation_id, legacy, role, scheme, identifier in rows:
            if scheme is None and identifier is None:
                sender = _legacy_principal(
                    legacy,
                    field=f"negotiation_messages[{message_id}].sender",
                    casing=casing,
                )
            elif scheme is None or identifier is None:
                raise ValueError(
                    f"negotiation_messages[{message_id}] has a partial sender principal"
                )
            else:
                sender = _validated_principal(
                    scheme,
                    identifier,
                    field=f"negotiation_messages[{message_id}].sender",
                )
            parties = thread_parties.get(str(negotiation_id))
            if parties is None:
                raise ValueError(
                    f"negotiation_messages[{message_id}] has no negotiation parties"
                )
            if role is None:
                if sender == parties[0]:
                    role = "buyer"
                elif sender == parties[1]:
                    role = "seller"
                else:
                    raise ValueError(
                        f"negotiation_messages[{message_id}] sender has no durable role"
                    )
            elif role not in {"buyer", "seller", "admin", "service"}:
                raise ValueError(
                    f"negotiation_messages[{message_id}] has an invalid sender role"
                )
            if role == "buyer" and sender != parties[0]:
                raise ValueError(
                    f"negotiation_messages[{message_id}] buyer principal conflicts"
                )
            if role == "seller" and sender != parties[1]:
                raise ValueError(
                    f"negotiation_messages[{message_id}] seller principal conflicts"
                )
            conn.execute(
                """
                UPDATE negotiation_messages
                SET sender_role=?, sender_scheme=?, sender_identifier=?
                WHERE message_id=?
                """,
                (role, *sender, message_id),
            )
        if has_legacy_sender:
            _drop_column_if_exists(conn, "negotiation_messages", "sender")

    deal_parties = dict(thread_parties)
    if _table_exists(conn, "escrows"):
        escrow_columns = _cols(conn, "escrows")
        if not {"escrow_uid", "negotiation_id"}.issubset(escrow_columns):
            raise ValueError("escrows lacks its durable negotiation association")
        for escrow_uid, negotiation_id in conn.execute(
            "SELECT escrow_uid, negotiation_id FROM escrows"
        ).fetchall():
            parties = thread_parties.get(str(negotiation_id))
            if parties is None:
                raise ValueError(
                    f"escrows[{escrow_uid}] has no durable negotiation parties"
                )
            prior = deal_parties.get(str(escrow_uid))
            if prior is not None and prior != parties:
                raise ValueError(
                    f"escrows[{escrow_uid}] conflicts with another durable deal"
                )
            deal_parties[str(escrow_uid)] = parties

    if _table_exists(conn, "deal_heartbeats"):
        for name in (
            "buyer_scheme",
            "buyer_identifier",
            "seller_scheme",
            "seller_identifier",
        ):
            _add_column_if_missing(conn, "deal_heartbeats", name, "TEXT")
        columns = _cols(conn, "deal_heartbeats")
        has_legacy_signer = "signer" in columns
        select_signer = "signer" if has_legacy_signer else "NULL"
        rows = conn.execute(
            f"""
            SELECT id, deal_ref, {select_signer},
                   buyer_scheme, buyer_identifier,
                   seller_scheme, seller_identifier
            FROM deal_heartbeats
            """
        ).fetchall()
        for (
            heartbeat_id,
            deal_ref,
            legacy_signer,
            buyer_scheme,
            buyer_identifier,
            seller_scheme,
            seller_identifier,
        ) in rows:
            parties = deal_parties.get(str(deal_ref))
            if buyer_scheme is None and buyer_identifier is None:
                buyer = _legacy_principal(
                    legacy_signer,
                    field=f"deal_heartbeats[{heartbeat_id}].signer",
                    casing=casing,
                )
            elif buyer_scheme is None or buyer_identifier is None:
                raise ValueError(
                    f"deal_heartbeats[{heartbeat_id}] has a partial buyer principal"
                )
            else:
                buyer = _validated_principal(
                    buyer_scheme,
                    buyer_identifier,
                    field=f"deal_heartbeats[{heartbeat_id}].buyer",
                )
            if seller_scheme is None and seller_identifier is None:
                if parties is None:
                    raise ValueError(
                        f"deal_heartbeats[{heartbeat_id}] has no durable deal parties"
                    )
                seller = parties[1]
            elif seller_scheme is None or seller_identifier is None:
                raise ValueError(
                    f"deal_heartbeats[{heartbeat_id}] has a partial seller principal"
                )
            else:
                seller = _validated_principal(
                    seller_scheme,
                    seller_identifier,
                    field=f"deal_heartbeats[{heartbeat_id}].seller",
                )
            conn.execute(
                """
                UPDATE deal_heartbeats
                SET buyer_scheme=?, buyer_identifier=?,
                    seller_scheme=?, seller_identifier=?
                WHERE id=?
                """,
                (*buyer, *seller, heartbeat_id),
            )
        if has_legacy_signer:
            _drop_column_if_exists(conn, "deal_heartbeats", "signer")

    if _table_exists(conn, "settlement_obligations"):
        _add_column_if_missing(
            conn,
            "settlement_obligations",
            "payer_principal",
            "TEXT",
        )
        _add_column_if_missing(
            conn,
            "settlement_obligations",
            "claimant_principal",
            "TEXT",
        )
        rows = conn.execute(
            """
            SELECT obligation_ref, agreement_ref, obligation,
                   payer_principal, claimant_principal
            FROM settlement_obligations
            """
        ).fetchall()
        for obligation_ref, agreement_ref, raw, payer_value, claimant_value in rows:
            parties = thread_parties.get(str(agreement_ref))
            if parties is None:
                raise ValueError(
                    f"settlement_obligations[{obligation_ref}] has no negotiation parties"
                )
            obligation = _require_json_object(
                raw,
                field=f"settlement_obligations[{obligation_ref}].obligation",
            )
            role_parties = {"buyer": parties[0], "seller": parties[1]}
            payer_role = obligation.get("payer")
            claimant_role = obligation.get("claimant")
            if payer_role not in role_parties or claimant_role not in role_parties:
                raise ValueError(
                    f"settlement_obligations[{obligation_ref}] has invalid party roles"
                )
            payer = role_parties[payer_role]
            claimant = role_parties[claimant_role]
            for value, expected, field in (
                (payer_value, payer, "payer_principal"),
                (claimant_value, claimant, "claimant_principal"),
            ):
                if value is None:
                    continue
                embedded = _require_json_object(
                    value,
                    field=f"settlement_obligations[{obligation_ref}].{field}",
                )
                _require_embedded_principal(
                    embedded,
                    expected=expected,
                    field=f"settlement_obligations[{obligation_ref}].{field}",
                )
            conn.execute(
                """
                UPDATE settlement_obligations
                SET payer_principal=?, claimant_principal=?
                WHERE obligation_ref=?
                """,
                (
                    json.dumps(
                        _principal_dict(payer),
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    json.dumps(
                        _principal_dict(claimant),
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                    obligation_ref,
                ),
            )



    for table_name, key_column in (
        ("auth_replay_reservations", "request_id"),
        ("identity_claims", "claim_id"),
    ):
        if not _table_exists(conn, table_name):
            continue
        columns = _cols(conn, table_name)
        legacy_column = next(
            (
                name
                for name in ("principal", "identity", "address")
                if name in columns
            ),
            None,
        )
        _add_column_if_missing(conn, table_name, "principal_scheme", "TEXT")
        _add_column_if_missing(conn, table_name, "principal_identifier", "TEXT")
        select_legacy = legacy_column or "NULL"
        rows = conn.execute(
            f"""
            SELECT rowid, {key_column}, {select_legacy},
                   principal_scheme, principal_identifier
            FROM {table_name}
            """
        ).fetchall()
        for row_id, key, legacy, scheme, identifier in rows:
            if scheme is None and identifier is None:
                principal = _legacy_principal(
                    legacy,
                    field=f"{table_name}[{key}].principal",
                    casing=casing,
                )
            elif scheme is None or identifier is None:
                raise ValueError(f"{table_name}[{key}] has a partial principal")
            else:
                principal = _validated_principal(
                    scheme,
                    identifier,
                    field=f"{table_name}[{key}].principal",
                )
            conn.execute(
                f"""
                UPDATE {table_name}
                SET principal_scheme=?, principal_identifier=?
                WHERE rowid=?
                """,
                (*principal, row_id),
            )
        if legacy_column is not None:
            if table_name == "auth_replay_reservations":
                _rebuild_replay_reservations_without_legacy_principal(
                    conn,
                    legacy_column=legacy_column,
                )
            else:
                _drop_column_if_exists(conn, table_name, legacy_column)

    if _table_exists(conn, "identity_audit"):
        columns = _cols(conn, "identity_audit")
        actor_legacy = next(
            (
                name
                for name in ("actor", "actor_identity", "actor_address")
                if name in columns
            ),
            None,
        )
        target_legacy = next(
            (
                name
                for name in ("target", "target_identity", "target_address")
                if name in columns
            ),
            None,
        )
        for name in (
            "actor_scheme",
            "actor_identifier",
            "target_scheme",
            "target_identifier",
        ):
            _add_column_if_missing(conn, "identity_audit", name, "TEXT")
        rows = conn.execute(
            f"""
            SELECT id, {actor_legacy or 'NULL'}, actor_scheme, actor_identifier,
                   {target_legacy or 'NULL'}, target_scheme, target_identifier
            FROM identity_audit
            """
        ).fetchall()
        for row_id, actor_old, actor_scheme, actor_identifier, target_old, target_scheme, target_identifier in rows:
            if actor_scheme is None and actor_identifier is None:
                actor = _legacy_principal(
                    actor_old,
                    field=f"identity_audit[{row_id}].actor",
                    casing=casing,
                )
            elif actor_scheme is None or actor_identifier is None:
                raise ValueError(f"identity_audit[{row_id}] has a partial actor")
            else:
                actor = _validated_principal(
                    actor_scheme,
                    actor_identifier,
                    field=f"identity_audit[{row_id}].actor",
                )
            if target_scheme is None and target_identifier is None:
                target = (
                    None
                    if target_old is None
                    else _legacy_principal(
                        target_old,
                        field=f"identity_audit[{row_id}].target",
                        casing=casing,
                    )
                )
            elif target_scheme is None or target_identifier is None:
                raise ValueError(f"identity_audit[{row_id}] has a partial target")
            else:
                target = _validated_principal(
                    target_scheme,
                    target_identifier,
                    field=f"identity_audit[{row_id}].target",
                )
            conn.execute(
                """
                UPDATE identity_audit
                SET actor_scheme=?, actor_identifier=?,
                    target_scheme=?, target_identifier=?
                WHERE id=?
                """,
                (*actor, *(target or (None, None)), row_id),
            )
        for legacy_column in (actor_legacy, target_legacy):
            if legacy_column is not None:
                _drop_column_if_exists(conn, "identity_audit", legacy_column)

    if _table_exists(conn, "stage_events"):
        rows = conn.execute("SELECT id, data FROM stage_events").fetchall()
        for event_id, data in rows:
            conn.execute(
                "UPDATE stage_events SET data=? WHERE id=?",
                (_migrate_stage_event_identity(data, casing=casing), event_id),
            )

    if _table_exists(conn, "service_peers"):
        columns = _cols(conn, "service_peers")
        legacy_column = next(
            (name for name in ("address", "identity") if name in columns),
            None,
        )
        if legacy_column is not None:
            _add_column_if_missing(conn, "service_peers", "principal_scheme", "TEXT")
            _add_column_if_missing(conn, "service_peers", "principal_identifier", "TEXT")
            seen: dict[tuple[str, str, str], str] = {}
            rows = conn.execute(
                f"""
                SELECT peer_id, role, {legacy_column},
                       principal_scheme, principal_identifier
                FROM service_peers
                """
            ).fetchall()
            for peer_id, role, legacy, scheme, identifier in rows:
                if scheme is None and identifier is None:
                    principal = _legacy_principal(
                        legacy,
                        field=f"service_peers[{peer_id}].{legacy_column}",
                        casing=casing,
                    )
                elif scheme is None or identifier is None:
                    raise ValueError(
                        f"service_peers[{peer_id}] has a partial principal"
                    )
                else:
                    principal = _validated_principal(
                        scheme,
                        identifier,
                        field=f"service_peers[{peer_id}].principal",
                    )
                owner = seen.get((str(role), principal[0], principal[1]))
                if owner is not None and owner != str(peer_id):
                    raise ValueError("duplicate active service-peer principal ownership")
                seen[(str(role), principal[0], principal[1])] = str(peer_id)
                conn.execute(
                    """
                    UPDATE service_peers
                    SET principal_scheme=?, principal_identifier=?
                    WHERE peer_id=?
                    """,
                    (*principal, peer_id),
                )
            _rebuild_service_peers_without_legacy_identity(
                conn,
                legacy_column=legacy_column,
            )

    for table_name, required_columns in (
        (
            "listings",
            ("storefront_url", "seller_scheme", "seller_identifier"),
        ),
        (
            "negotiation_threads",
            (
                "buyer_scheme",
                "buyer_identifier",
                "seller_scheme",
                "seller_identifier",
            ),
        ),
        (
            "negotiation_messages",
            ("sender_role", "sender_scheme", "sender_identifier"),
        ),
        (
            "deal_heartbeats",
            (
                "buyer_scheme",
                "buyer_identifier",
                "seller_scheme",
                "seller_identifier",
            ),
        ),
        (
            "settlement_obligations",
            ("payer_principal", "claimant_principal"),
        ),
        (
            "auth_replay_reservations",
            ("principal_scheme", "principal_identifier"),
        ),
        (
            "identity_claims",
            ("principal_scheme", "principal_identifier"),
        ),
        (
            "identity_audit",
            ("actor_scheme", "actor_identifier"),
        ),
        (
            "service_peers",
            ("principal_scheme", "principal_identifier"),
        ),
    ):
        if not _table_exists(conn, table_name):
            continue
        null_check = " OR ".join(
            f"NEW.{column_name} IS NULL" for column_name in required_columns
        )
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {table_name}_principal_insert
            BEFORE INSERT ON {table_name}
            WHEN {null_check}
            BEGIN
              SELECT RAISE(ABORT, 'canonical principal fields are required');
            END
            """
        )
        conn.execute(
            f"""
            CREATE TRIGGER IF NOT EXISTS {table_name}_principal_update
            BEFORE UPDATE ON {table_name}
            WHEN {null_check}
            BEGIN
              SELECT RAISE(ABORT, 'canonical principal fields are required');
            END
            """
        )

    for table_name, old_column in (
        ("listings", "seller"),
        ("negotiation_threads", "buyer"),
        ("negotiation_messages", "sender"),
        ("deal_heartbeats", "signer"),
    ):
        if _column_exists(conn, table_name, old_column):
            raise RuntimeError(
                f"{table_name}.{old_column} could not be removed during identity cutover"
            )

def migrate_storefront_domain_bindings_schema(conn: sqlite3.Connection) -> None:
    """Create immutable listing, negotiation, and domain-artifact bindings."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storefront_listing_bindings (
          listing_id TEXT PRIMARY KEY,
          site_id TEXT NOT NULL,
          pool_id TEXT,
          physical_resource_id TEXT,
          offering_mode TEXT NOT NULL,
          domain_identity TEXT NOT NULL,
          contract_major INTEGER NOT NULL CHECK (contract_major >= 1),
          contract_minor INTEGER NOT NULL CHECK (contract_minor >= 0),
          derivation_key TEXT NOT NULL UNIQUE,
          source_envelope_json TEXT NOT NULL,
          last_reconciled_at TEXT NOT NULL,
          FOREIGN KEY (listing_id) REFERENCES listings(listing_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_storefront_listing_bindings_site "
        "ON storefront_listing_bindings(site_id, offering_mode)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_storefront_listing_bindings_domain "
        "ON storefront_listing_bindings("
        "domain_identity, contract_major, contract_minor)"
    )
    for column_name, column_sql in (
        ("domain_listing_id", "TEXT"),
        ("site_id", "TEXT"),
        ("offering_mode", "TEXT"),
        ("domain_identity", "TEXT"),
        ("contract_major", "INTEGER"),
        ("contract_minor", "INTEGER"),
    ):
        _add_column_if_missing(
            conn,
            "negotiation_threads",
            column_name,
            column_sql,
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_negotiation_threads_domain_binding "
        "ON negotiation_threads("
        "domain_identity, contract_major, contract_minor, offering_mode)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_negotiation_threads_domain_listing "
        "ON negotiation_threads(domain_listing_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS storefront_domain_artifacts (
          negotiation_id TEXT NOT NULL,
          artifact_slot TEXT NOT NULL,
          offering_mode TEXT NOT NULL,
          domain_identity TEXT NOT NULL,
          contract_major INTEGER NOT NULL CHECK (contract_major >= 1),
          contract_minor INTEGER NOT NULL CHECK (contract_minor >= 0),
          artifact_json TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (
            STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')
          ),
          PRIMARY KEY (negotiation_id, artifact_slot),
          FOREIGN KEY (negotiation_id)
            REFERENCES negotiation_threads(negotiation_id)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_storefront_domain_artifacts_binding "
        "ON storefront_domain_artifacts("
        "domain_identity, contract_major, contract_minor, offering_mode)"
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS storefront_listing_binding_insert_owner
        BEFORE INSERT ON storefront_listing_bindings
        WHEN NOT EXISTS (
          SELECT 1 FROM listings WHERE listing_id = NEW.listing_id
        )
        BEGIN
          SELECT RAISE(ABORT, 'listing binding requires an existing listing');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS storefront_listing_binding_immutable
        BEFORE UPDATE OF
          listing_id, site_id, pool_id, physical_resource_id, offering_mode,
          domain_identity, contract_major, contract_minor, derivation_key,
          source_envelope_json
        ON storefront_listing_bindings
        WHEN NOT (OLD.listing_id IS NEW.listing_id)
          OR NOT (OLD.site_id IS NEW.site_id)
          OR NOT (OLD.pool_id IS NEW.pool_id)
          OR NOT (OLD.physical_resource_id IS NEW.physical_resource_id)
          OR NOT (OLD.offering_mode IS NEW.offering_mode)
          OR NOT (OLD.domain_identity IS NEW.domain_identity)
          OR NOT (OLD.contract_major IS NEW.contract_major)
          OR NOT (OLD.contract_minor IS NEW.contract_minor)
          OR NOT (OLD.derivation_key IS NEW.derivation_key)
          OR NOT (OLD.source_envelope_json IS NEW.source_envelope_json)
        BEGIN
          SELECT RAISE(ABORT, 'storefront listing binding is immutable');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS negotiation_domain_binding_complete_insert
        BEFORE INSERT ON negotiation_threads
        WHEN (
          NEW.domain_listing_id IS NULL
          OR NEW.site_id IS NULL
          OR NEW.offering_mode IS NULL
          OR NEW.domain_identity IS NULL
          OR NEW.contract_major IS NULL
          OR NEW.contract_minor IS NULL
        ) AND NOT (
          NEW.domain_listing_id IS NULL
          AND NEW.site_id IS NULL
          AND NEW.offering_mode IS NULL
          AND NEW.domain_identity IS NULL
          AND NEW.contract_major IS NULL
          AND NEW.contract_minor IS NULL
        )
        BEGIN
          SELECT RAISE(ABORT, 'negotiation domain binding is incomplete');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS negotiation_domain_binding_owner_insert
        BEFORE INSERT ON negotiation_threads
        WHEN NEW.domain_identity IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM storefront_listing_bindings binding
            WHERE binding.listing_id = NEW.domain_listing_id
              AND binding.site_id = NEW.site_id
              AND binding.offering_mode = NEW.offering_mode
              AND binding.domain_identity = NEW.domain_identity
              AND binding.contract_major = NEW.contract_major
              AND binding.contract_minor = NEW.contract_minor
          )
        BEGIN
          SELECT RAISE(ABORT, 'negotiation domain binding disagrees with listing');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS negotiation_domain_binding_immutable
        BEFORE UPDATE OF
          domain_listing_id, site_id, offering_mode, domain_identity,
          contract_major, contract_minor
        ON negotiation_threads
        WHEN OLD.domain_identity IS NOT NULL
          AND (
            NOT (OLD.domain_listing_id IS NEW.domain_listing_id)
            OR NOT (OLD.site_id IS NEW.site_id)
            OR NOT (OLD.offering_mode IS NEW.offering_mode)
            OR NOT (OLD.domain_identity IS NEW.domain_identity)
            OR NOT (OLD.contract_major IS NEW.contract_major)
            OR NOT (OLD.contract_minor IS NEW.contract_minor)
          )
        BEGIN
          SELECT RAISE(ABORT, 'negotiation domain binding is immutable');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS negotiation_domain_binding_owner_update
        BEFORE UPDATE OF
          domain_listing_id, site_id, offering_mode, domain_identity,
          contract_major, contract_minor
        ON negotiation_threads
        WHEN NEW.domain_identity IS NOT NULL
          AND NOT EXISTS (
            SELECT 1
            FROM storefront_listing_bindings binding
            WHERE binding.listing_id = NEW.domain_listing_id
              AND binding.site_id = NEW.site_id
              AND binding.offering_mode = NEW.offering_mode
              AND binding.domain_identity = NEW.domain_identity
              AND binding.contract_major = NEW.contract_major
              AND binding.contract_minor = NEW.contract_minor
          )
        BEGIN
          SELECT RAISE(ABORT, 'negotiation domain binding disagrees with listing');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS storefront_domain_artifact_owner_insert
        BEFORE INSERT ON storefront_domain_artifacts
        WHEN NOT EXISTS (
          SELECT 1
          FROM negotiation_threads thread
          WHERE thread.negotiation_id = NEW.negotiation_id
            AND thread.offering_mode = NEW.offering_mode
            AND thread.domain_identity = NEW.domain_identity
            AND thread.contract_major = NEW.contract_major
            AND thread.contract_minor = NEW.contract_minor
        )
        BEGIN
          SELECT RAISE(ABORT, 'domain artifact disagrees with negotiation binding');
        END
        """
    )
    conn.execute(
        """
        CREATE TRIGGER IF NOT EXISTS storefront_domain_artifact_immutable
        BEFORE UPDATE ON storefront_domain_artifacts
        WHEN NOT (OLD.negotiation_id IS NEW.negotiation_id)
          OR NOT (OLD.artifact_slot IS NEW.artifact_slot)
          OR NOT (OLD.offering_mode IS NEW.offering_mode)
          OR NOT (OLD.domain_identity IS NEW.domain_identity)
          OR NOT (OLD.contract_major IS NEW.contract_major)
          OR NOT (OLD.contract_minor IS NEW.contract_minor)
          OR NOT (OLD.artifact_json IS NEW.artifact_json)
        BEGIN
          SELECT RAISE(ABORT, 'storefront domain artifact is immutable');
        END
        """
    )


def _migrate_replay_attempt_leases(conn: sqlite3.Connection) -> None:
    """Make pending replay reservations reclaimable after a crashed attempt."""

    if not _table_exists(conn, "auth_replay_reservations"):
        return
    _add_column_if_missing(
        conn,
        "auth_replay_reservations",
        "attempt_token",
        "TEXT",
    )
    _add_column_if_missing(
        conn,
        "auth_replay_reservations",
        "lease_until",
        "INTEGER",
    )
    conn.execute(
        """
        UPDATE auth_replay_reservations
        SET lease_until=0
        WHERE response_status IS NULL AND response_body IS NULL
          AND lease_until IS NULL
        """
    )


_MIGRATIONS: tuple[Migration, ...] = (
    Migration(
        "20260604_000_listing_resource_timestamps",
        _migrate_listing_resource_timestamps,
    ),
    Migration(
        "20260604_004_negotiation_amount_text_columns",
        _migrate_negotiation_amount_columns,
    ),
    Migration(
        "20260604_005_escrows_and_listings",
        _migrate_escrows_and_listings,
        apply_with_legacy_context=_migrate_escrows_and_listings,
    ),
    Migration(
        "20260722_001_capacity_holds_reservation_id",
        _migrate_capacity_holds_reservation_id,
    ),
    Migration(
        "20260810_003_negotiation_provision_terms",
        _migrate_negotiation_provision_terms,
    ),
    Migration(
        "20260811_001_marketplace_principals_v2",
        _migrate_marketplace_principals,
        _migrate_marketplace_principals,
    ),
    Migration(
        "20260811_002_replay_attempt_leases",
        _migrate_replay_attempt_leases,
    ),
    Migration(
        "20260815_001_storefront_domain_bindings",
        migrate_storefront_domain_bindings_schema,
    ),
)
