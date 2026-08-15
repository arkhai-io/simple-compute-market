"""SQLite persistence and migrations for the settlement runtime."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from market_identity import Identity, IdentityScheme

from .models import canonical_json, derive_obligation_ref, obligation_payload_hash

SETTLEMENT_MIGRATION_ID = "20260810_001_settlement_obligation_lifecycle"
SETTLEMENT_PRINCIPAL_MIGRATION_ID = (
    "20260811_003_settlement_principal_authorization"
)
SETTLEMENT_MECHANISM_PARAMS_MIGRATION_ID = (
    "20260815_004_settlement_mechanism_materialization_params"
)
_LEGACY_HOSTED_CARD_RECOVERY = {"legacy_recovery": "hosted-card.v1"}


@dataclass(frozen=True)
class SettlementMigration:
    id: str
    apply: Callable[[sqlite3.Connection], None]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _operation_hash(
    obligation_ref: str,
    obligation_hash: str,
    operation: str,
    request: dict[str, Any] | None = None,
) -> str:
    value = {
        "protocol": "arkhai.settlement-operation.v1",
        "obligation_ref": obligation_ref,
        "obligation_hash": obligation_hash,
        "operation": operation,
        "request": request or {},
    }
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settlement_obligations (
          obligation_ref TEXT PRIMARY KEY,
          agreement_ref TEXT NOT NULL,
          obligation_index INTEGER NOT NULL CHECK (obligation_index >= 0),
          obligation_hash TEXT NOT NULL,
          obligation TEXT NOT NULL,
          mechanism_params TEXT NOT NULL DEFAULT '{}',
          payer_principal TEXT NOT NULL,
          claimant_principal TEXT NOT NULL,
          mechanism_ref TEXT,
          mechanism_status TEXT,
          mechanism_state TEXT NOT NULL DEFAULT '{}',
          buyer_action TEXT,
          condition_anchor TEXT,
          fulfillment_ref TEXT,
          materialization_state TEXT NOT NULL DEFAULT 'pending',
          condition_state TEXT NOT NULL DEFAULT 'pending',
          collection_state TEXT NOT NULL DEFAULT 'pending',
          reclaim_state TEXT NOT NULL DEFAULT 'pending',
          materialization_receipt TEXT,
          status_receipt TEXT,
          collection_receipt TEXT,
          reclaim_receipt TEXT,
          last_error TEXT,
          version INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE (agreement_ref, obligation_index)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settlement_operations (
          obligation_ref TEXT NOT NULL,
          operation TEXT NOT NULL,
          request_hash TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending',
          attempts INTEGER NOT NULL DEFAULT 0,
          uncertain_acknowledgement INTEGER NOT NULL DEFAULT 0,
          receipt TEXT,
          last_error TEXT,
          lease_owner TEXT,
          lease_until_unix REAL,
          next_attempt_unix REAL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          PRIMARY KEY (obligation_ref, operation),
          FOREIGN KEY (obligation_ref) REFERENCES settlement_obligations(obligation_ref)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_settlement_obligations_agreement "
        "ON settlement_obligations(agreement_ref, obligation_index)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_settlement_obligations_mechanism_ref "
        "ON settlement_obligations(mechanism_ref) WHERE mechanism_ref IS NOT NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_settlement_operations_due "
        "ON settlement_operations(state, next_attempt_unix, lease_until_unix)"
    )
    _migrate_legacy_claims(conn)


def _extend_schema(conn: sqlite3.Connection) -> None:
    additions = {
        "mechanism_status": "TEXT",
        "mechanism_state": "TEXT NOT NULL DEFAULT '{}'",
        "buyer_action": "TEXT",
        "condition_anchor": "TEXT",
        "status_receipt": "TEXT",
    }
    known = _columns(conn, "settlement_obligations")
    for name, sql in additions.items():
        if name not in known:
            conn.execute(f"ALTER TABLE settlement_obligations ADD COLUMN {name} {sql}")
    if "next_attempt_unix" not in _columns(conn, "settlement_operations"):
        conn.execute(
            "ALTER TABLE settlement_operations ADD COLUMN next_attempt_unix REAL"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_settlement_operations_due "
        "ON settlement_operations(state, next_attempt_unix, lease_until_unix)"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_settlement_obligations_mechanism_ref "
        "ON settlement_obligations(mechanism_ref) WHERE mechanism_ref IS NOT NULL"
    )


def _principal_from_legacy(
    stored: str | None,
    obligation: dict[str, Any],
    field: str,
) -> Identity:
    candidates: list[Identity] = []
    if stored is not None:
        try:
            candidates.append(Identity.model_validate(json.loads(stored)))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"settlement obligation has malformed {field} column"
            ) from exc
    nested = obligation.get(f"{field}_principal")
    if nested is not None:
        try:
            candidates.append(Identity.model_validate(nested))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"settlement obligation has malformed {field}_principal"
            ) from exc
    legacy = obligation.get(field)
    if not isinstance(legacy, str) or legacy not in ("buyer", "seller"):
        try:
            candidates.append(
                Identity(
                    scheme=IdentityScheme.EIP191,
                    identifier=legacy,
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"settlement obligation has malformed legacy {field}"
            ) from exc
    if not candidates:
        raise ValueError(
            f"settlement obligation cannot resolve {field}_principal"
        )
    principal = candidates[0]
    if any(candidate != principal for candidate in candidates[1:]):
        raise ValueError(
            f"settlement obligation has ambiguous {field} identities"
        )
    return principal


def _extend_principal_schema(conn: sqlite3.Connection) -> None:
    known = _columns(conn, "settlement_obligations")
    for name in ("payer_principal", "claimant_principal"):
        if name not in known:
            conn.execute(
                f"ALTER TABLE settlement_obligations ADD COLUMN {name} "
                "TEXT NOT NULL DEFAULT ''"
            )
    rows = conn.execute(
        "SELECT obligation_ref, obligation, payer_principal, claimant_principal "
        "FROM settlement_obligations ORDER BY obligation_ref"
    ).fetchall()
    converted: list[tuple[str, str, str]] = []
    for obligation_ref, raw, payer_raw, claimant_raw in rows:
        try:
            obligation = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"settlement obligation {obligation_ref!r} has invalid JSON"
            ) from exc
        if not isinstance(obligation, dict):
            raise ValueError(
                f"settlement obligation {obligation_ref!r} is not an object"
            )
        payer = _principal_from_legacy(
            payer_raw or None,
            obligation,
            "payer",
        )
        claimant = _principal_from_legacy(
            claimant_raw or None,
            obligation,
            "claimant",
        )
        converted.append(
            (
                canonical_json(payer.model_dump(mode="json")),
                canonical_json(claimant.model_dump(mode="json")),
                str(obligation_ref),
            )
        )
    conn.executemany(
        "UPDATE settlement_obligations SET payer_principal=?, "
        "claimant_principal=? WHERE obligation_ref=?",
        converted,
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS settlement_principals_insert_required "
        "BEFORE INSERT ON settlement_obligations "
        "WHEN NEW.payer_principal IS NULL OR NEW.payer_principal = '' "
        "OR NEW.claimant_principal IS NULL OR NEW.claimant_principal = '' "
        "BEGIN SELECT RAISE(ABORT, 'settlement principals required'); END"
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS settlement_principals_update_required "
        "BEFORE UPDATE OF payer_principal, claimant_principal "
        "ON settlement_obligations "
        "WHEN NEW.payer_principal IS NULL OR NEW.payer_principal = '' "
        "OR NEW.claimant_principal IS NULL OR NEW.claimant_principal = '' "
        "BEGIN SELECT RAISE(ABORT, 'settlement principals required'); END"
    )

def _extend_mechanism_params_schema(conn: sqlite3.Connection) -> None:
    known = _columns(conn, "settlement_obligations")
    if "mechanism_params" not in known:
        conn.execute(
            "ALTER TABLE settlement_obligations ADD COLUMN mechanism_params "
            "TEXT NOT NULL DEFAULT '{}'"
        )
    rows = conn.execute(
        "SELECT obligation_ref, obligation, mechanism_params, mechanism_ref "
        "FROM settlement_obligations ORDER BY obligation_ref"
    ).fetchall()
    classified: list[tuple[str, str]] = []
    for (
        obligation_ref,
        raw_obligation,
        raw_mechanism_params,
        mechanism_ref,
    ) in rows:
        try:
            obligation = json.loads(raw_obligation)
            mechanism_params = json.loads(raw_mechanism_params or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"settlement obligation {obligation_ref!r} has invalid JSON"
            ) from exc
        if not isinstance(obligation, dict) or not isinstance(mechanism_params, dict):
            raise ValueError(
                f"settlement obligation {obligation_ref!r} has invalid materialization state"
            )
        if obligation.get("mechanism") != "fiat.stripe.v1":
            continue
        params = obligation.get("params")
        if not isinstance(params, dict):
            raise ValueError(
                f"hosted settlement obligation {obligation_ref!r} has no exact params"
            )
        legacy_methods = params.get("payment_method_types")
        funding_profile = params.get("funding_profile")
        if legacy_methods is not None and funding_profile is not None:
            raise ValueError(
                f"hosted settlement obligation {obligation_ref!r} mixes legacy and current funding fields"
            )
        if legacy_methods is not None:
            if not isinstance(mechanism_ref, str) or not mechanism_ref:
                raise ValueError(
                    f"legacy hosted settlement {obligation_ref!r} has no immutable mechanism reference"
                )
            if (
                legacy_methods != ["card"]
                or "funding_authorization_ref" in params
                or (
                    mechanism_params
                    and mechanism_params != _LEGACY_HOSTED_CARD_RECOVERY
                )
            ):
                raise ValueError(
                    f"hosted settlement obligation {obligation_ref!r} is ambiguous legacy funding"
                )
            classified.append(
                (canonical_json(_LEGACY_HOSTED_CARD_RECOVERY), str(obligation_ref))
            )
            continue
        if funding_profile is None:
            raise ValueError(
                f"hosted settlement obligation {obligation_ref!r} has no funding classification"
            )
        if mechanism_params:
            accepted_profile = mechanism_params.get("funding_profile")
            authorization_ref = mechanism_params.get("funding_authorization_ref")
            if (
                accepted_profile != funding_profile
                or not isinstance(authorization_ref, str)
                or not authorization_ref
                or set(mechanism_params)
                != {"funding_profile", "funding_authorization_ref"}
            ):
                raise ValueError(
                    f"hosted settlement obligation {obligation_ref!r} has ambiguous materialization params"
                )
    conn.executemany(
        "UPDATE settlement_obligations SET mechanism_params=? "
        "WHERE obligation_ref=?",
        classified,
    )


def _migrate_legacy_claims(conn: sqlite3.Connection) -> None:
    if not _table_exists(conn, "settlement_claims"):
        return
    rows = conn.execute(
        """
        SELECT claim_ref, state, deal_ref, obligation, fulfillment_ref,
               attempts, next_attempt_unix, mechanism_state, last_error,
               result, created_at, updated_at
        FROM settlement_claims ORDER BY created_at, claim_ref
        """
    ).fetchall()
    candidates: list[dict[str, Any]] = []
    identities: dict[tuple[str, int], tuple[str, str]] = {}
    for row in rows:
        (
            claim_ref,
            claim_state,
            deal_raw,
            obligation_raw,
            fulfillment_ref,
            attempts,
            next_attempt,
            mechanism_raw,
            last_error,
            result_raw,
            created_at,
            updated_at,
        ) = row
        try:
            deal = json.loads(deal_raw) if deal_raw else {}
            obligation = json.loads(obligation_raw) if obligation_raw else None
            mechanism_state = json.loads(mechanism_raw) if mechanism_raw else {}
            result = json.loads(result_raw) if result_raw else None
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"legacy settlement claim {claim_ref!r} has invalid JSON"
            ) from exc
        if (
            not isinstance(deal, dict)
            or not isinstance(obligation, dict)
            or not obligation
        ):
            raise ValueError(
                f"legacy settlement claim {claim_ref!r} lacks an exact obligation snapshot"
            )
        agreement_ref = deal.get("agreement_ref") or deal.get("negotiation_id")
        if not isinstance(agreement_ref, str) or not agreement_ref:
            raise ValueError(
                f"legacy settlement claim {claim_ref!r} lacks stable agreement identity"
            )
        try:
            index = int(deal.get("obligation_index", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"legacy settlement claim {claim_ref!r} has invalid obligation index"
            ) from exc
        obligation_ref = derive_obligation_ref(agreement_ref, index, obligation)
        obligation_hash = obligation_payload_hash(obligation)
        key = (agreement_ref, index)
        identity = (obligation_ref, obligation_hash)
        if identities.setdefault(key, identity) != identity:
            raise ValueError(
                "legacy settlement claims conflict at one immutable obligation index"
            )
        existing = conn.execute(
            "SELECT obligation_ref, obligation_hash FROM settlement_obligations "
            "WHERE agreement_ref=? AND obligation_index=?",
            key,
        ).fetchone()
        if existing is not None and tuple(existing) != identity:
            raise ValueError(
                "legacy settlement claim conflicts with an immutable obligation"
            )
        payer = _principal_from_legacy(None, obligation, "payer")
        claimant = _principal_from_legacy(None, obligation, "claimant")
        candidates.append(
            {
                "claim_ref": str(claim_ref),
                "state": str(claim_state),
                "agreement_ref": agreement_ref,
                "index": index,
                "obligation_ref": obligation_ref,
                "obligation_hash": obligation_hash,
                "obligation": obligation,
                "payer_principal": canonical_json(
                    payer.model_dump(mode="json")
                ),
                "claimant_principal": canonical_json(
                    claimant.model_dump(mode="json")
                ),
                "fulfillment_ref": fulfillment_ref,
                "attempts": int(attempts or 0),
                "next_attempt": next_attempt,
                "mechanism_state": mechanism_state
                if isinstance(mechanism_state, dict)
                else {},
                "last_error": last_error,
                "result": result if isinstance(result, dict) else None,
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
    for item in candidates:
        state = item["state"]
        condition = (
            "ready"
            if state in {"collectable", "collected"}
            else "manual_required"
            if state == "abandoned"
            else "pending"
        )
        collection = (
            "succeeded"
            if state == "collected"
            else "manual_required"
            if state == "abandoned"
            else "pending"
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO settlement_obligations
              (obligation_ref, agreement_ref, obligation_index, obligation_hash,
               obligation, payer_principal, claimant_principal, mechanism_ref,
               mechanism_status, mechanism_state, fulfillment_ref,
               materialization_state, condition_state,
               collection_state, reclaim_state, collection_receipt, last_error,
               version, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?, 'materialized', ?, ?,
                    'pending', ?, ?, 0, ?, ?)
            """,
            (
                item["obligation_ref"],
                item["agreement_ref"],
                item["index"],
                item["obligation_hash"],
                canonical_json(item["obligation"]),
                item["payer_principal"],
                item["claimant_principal"],
                item["claim_ref"],
                canonical_json(item["mechanism_state"]),
                item["fulfillment_ref"],
                condition,
                collection,
                canonical_json(item["result"]) if item["result"] else None,
                item["last_error"],
                item["created_at"],
                item["updated_at"],
            ),
        )
        check_state = (
            "succeeded"
            if state in {"collectable", "collected"}
            else "manual_required"
            if state == "abandoned"
            else "pending"
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO settlement_operations
              (obligation_ref, operation, request_hash, state, attempts,
               uncertain_acknowledgement, last_error, next_attempt_unix,
               created_at, updated_at)
            VALUES (?, 'check', ?, ?, ?, 0, ?, ?, ?, ?)
            """,
            (
                item["obligation_ref"],
                _operation_hash(
                    item["obligation_ref"],
                    item["obligation_hash"],
                    "check",
                    {"fulfillment_ref": item["fulfillment_ref"]},
                ),
                check_state,
                item["attempts"],
                item["last_error"],
                item["next_attempt"],
                item["created_at"],
                item["updated_at"],
            ),
        )
        if state in {"collectable", "collected"}:
            conn.execute(
                """
                INSERT OR IGNORE INTO settlement_operations
                  (obligation_ref, operation, request_hash, state, attempts,
                   uncertain_acknowledgement, receipt, last_error,
                   next_attempt_unix, created_at, updated_at)
                VALUES (?, 'collect', ?, ?, ?, 0, ?, ?, ?, ?, ?)
                """,
                (
                    item["obligation_ref"],
                    _operation_hash(
                        item["obligation_ref"], item["obligation_hash"], "collect"
                    ),
                    "succeeded" if state == "collected" else "pending",
                    item["attempts"],
                    canonical_json(item["result"]) if item["result"] else None,
                    item["last_error"],
                    item["next_attempt"],
                    item["created_at"],
                    item["updated_at"],
                ),
            )


def settlement_migrations() -> tuple[SettlementMigration, ...]:
    return (
        SettlementMigration(SETTLEMENT_MIGRATION_ID, _create_schema),
        SettlementMigration(
            "20260810_002_settlement_servicing_runtime", _extend_schema
        ),
        SettlementMigration(
            SETTLEMENT_PRINCIPAL_MIGRATION_ID,
            _extend_principal_schema,
        ),
        SettlementMigration(
            SETTLEMENT_MECHANISM_PARAMS_MIGRATION_ID,
            _extend_mechanism_params_schema,
        ),
    )


class SettlementSQLiteRepository:
    """Settlement tables and operation journal in an existing SQLite database."""

    _OBLIGATION_JSON_FIELDS = {
        "obligation",
        "payer_principal",
        "claimant_principal",
        "mechanism_params",
        "mechanism_state",
        "buyer_action",
        "materialization_receipt",
        "status_receipt",
        "collection_receipt",
        "reclaim_receipt",
    }
    _OBLIGATION_COLUMNS = (
        "obligation_ref",
        "agreement_ref",
        "obligation_index",
        "obligation_hash",
        "obligation",
        "mechanism_params",
        "payer_principal",
        "claimant_principal",
        "mechanism_ref",
        "mechanism_status",
        "mechanism_state",
        "buyer_action",
        "condition_anchor",
        "fulfillment_ref",
        "materialization_state",
        "condition_state",
        "collection_state",
        "reclaim_state",
        "materialization_receipt",
        "status_receipt",
        "collection_receipt",
        "reclaim_receipt",
        "last_error",
        "version",
    )
    _OPERATION_COLUMNS = (
        "obligation_ref",
        "operation",
        "request_hash",
        "state",
        "attempts",
        "uncertain_acknowledgement",
        "receipt",
        "last_error",
        "lease_owner",
        "lease_until_unix",
        "next_attempt_unix",
    )

    def __init__(self, db_path: str, *, apply_migrations: bool = True) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
        if apply_migrations:
            self._apply_migrations()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _apply_migrations(self) -> None:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(id TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT "
                "(STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now')))"
            )
            applied = {
                str(row[0]) for row in conn.execute("SELECT id FROM schema_migrations")
            }
            for migration in settlement_migrations():
                if migration.id not in applied:
                    migration.apply(conn)
                    conn.execute(
                        "INSERT INTO schema_migrations (id) VALUES (?)", (migration.id,)
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _obligation(self, row: tuple[Any, ...]) -> dict[str, Any]:
        value = dict(zip(self._OBLIGATION_COLUMNS, row))
        for field in self._OBLIGATION_JSON_FIELDS:
            raw = value.get(field)
            if field in {"payer_principal", "claimant_principal"}:
                if not raw:
                    raise ValueError(
                        f"settlement obligation has no canonical {field}"
                    )
                try:
                    principal = Identity.model_validate(json.loads(raw))
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"settlement obligation has malformed {field}"
                    ) from exc
                canonical = canonical_json(principal.model_dump(mode="json"))
                if raw != canonical:
                    raise ValueError(
                        f"settlement obligation has non-canonical {field}"
                    )
                value[field] = principal.model_dump(mode="json")
                continue
            value[field] = (
                json.loads(raw)
                if raw
                else (
                    {}
                    if field in {"obligation", "mechanism_params", "mechanism_state"}
                    else None
                )
            )
        return value

    def _operation(self, row: tuple[Any, ...]) -> dict[str, Any]:
        value = dict(zip(self._OPERATION_COLUMNS, row))
        value["uncertain_acknowledgement"] = bool(value["uncertain_acknowledgement"])
        value["receipt"] = json.loads(value["receipt"]) if value["receipt"] else None
        return value

    async def upsert_settlement_obligation(
        self, obligation: dict[str, Any]
    ) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            now = self._now()
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")

                def json_value(name: str, default: Any = None) -> str | None:
                    value = obligation.get(name, default)
                    return canonical_json(value) if value is not None else None

                payer_principal = json_value("payer_principal")
                claimant_principal = json_value("claimant_principal")
                if payer_principal is None or claimant_principal is None:
                    raise ValueError(
                        "settlement obligation requires canonical principals"
                    )

                conn.execute(
                    """
                    INSERT OR IGNORE INTO settlement_obligations
                      (obligation_ref, agreement_ref, obligation_index,
                       obligation_hash, obligation, mechanism_params,
                       payer_principal, claimant_principal, mechanism_ref,
                       mechanism_status, mechanism_state, buyer_action,
                       condition_anchor, fulfillment_ref, materialization_state,
                       condition_state, collection_state, reclaim_state,
                       materialization_receipt, status_receipt,
                       collection_receipt, reclaim_receipt, last_error,
                       version, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        obligation["obligation_ref"],
                        obligation["agreement_ref"],
                        int(obligation["obligation_index"]),
                        obligation["obligation_hash"],
                        canonical_json(obligation["obligation"]),
                        canonical_json(obligation.get("mechanism_params") or {}),
                        payer_principal,
                        claimant_principal,
                        obligation.get("mechanism_ref"),
                        obligation.get("mechanism_status"),
                        canonical_json(obligation.get("mechanism_state") or {}),
                        json_value("buyer_action"),
                        obligation.get("condition_anchor"),
                        obligation.get("fulfillment_ref"),
                        obligation.get("materialization_state") or "pending",
                        obligation.get("condition_state") or "pending",
                        obligation.get("collection_state") or "pending",
                        obligation.get("reclaim_state") or "pending",
                        json_value("materialization_receipt"),
                        json_value("status_receipt"),
                        json_value("collection_receipt"),
                        json_value("reclaim_receipt"),
                        obligation.get("last_error"),
                        int(obligation.get("version") or 0),
                        now,
                        now,
                    ),
                )
                stored_binding = conn.execute(
                    "SELECT obligation_ref, obligation_hash, "
                    "payer_principal, claimant_principal "
                    "FROM settlement_obligations WHERE agreement_ref=? "
                    "AND obligation_index=?",
                    (
                        obligation["agreement_ref"],
                        int(obligation["obligation_index"]),
                    ),
                ).fetchone()
                if stored_binding is None:
                    raise RuntimeError("settlement obligation insert was lost")
                if (
                    stored_binding[0] != obligation["obligation_ref"]
                    or stored_binding[1] != obligation["obligation_hash"]
                ):
                    raise ValueError(
                        "agreement obligation index was reused with different terms"
                    )
                for stored_principal, supplied_principal in zip(
                    stored_binding[2:],
                    (payer_principal, claimant_principal),
                    strict=True,
                ):
                    if (
                        stored_principal is not None
                        and stored_principal != supplied_principal
                    ):
                        raise ValueError(
                            "settlement obligation principal binding changed"
                        )
                row = conn.execute(
                    f"SELECT {', '.join(self._OBLIGATION_COLUMNS)} FROM settlement_obligations WHERE agreement_ref=? AND obligation_index=?",
                    (obligation["agreement_ref"], int(obligation["obligation_index"])),
                ).fetchone()
                if row is None:
                    raise RuntimeError("settlement obligation insert was lost")
                stored = self._obligation(row)
                if (
                    stored["obligation_ref"] != obligation["obligation_ref"]
                    or stored["obligation_hash"] != obligation["obligation_hash"]
                ):
                    raise ValueError(
                        "agreement obligation index was reused with different terms"
                    )
                conn.commit()
                return stored
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def load_settlement_obligation(
        self, obligation_ref: str
    ) -> dict[str, Any] | None:
        def run() -> dict[str, Any] | None:
            conn = self._connect()
            try:
                row = conn.execute(
                    f"SELECT {', '.join(self._OBLIGATION_COLUMNS)} FROM settlement_obligations WHERE obligation_ref=?",
                    (obligation_ref,),
                ).fetchone()
                return self._obligation(row) if row else None
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def load_settlement_obligation_by_mechanism_ref(
        self, mechanism_ref: str
    ) -> dict[str, Any] | None:
        def run() -> dict[str, Any] | None:
            conn = self._connect()
            try:
                row = conn.execute(
                    f"SELECT {', '.join(self._OBLIGATION_COLUMNS)} "
                    "FROM settlement_obligations WHERE mechanism_ref=?",
                    (mechanism_ref,),
                ).fetchone()
                return self._obligation(row) if row else None
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def list_settlement_obligations(
        self, agreement_ref: str
    ) -> list[dict[str, Any]]:
        def run() -> list[dict[str, Any]]:
            conn = self._connect()
            try:
                rows = conn.execute(
                    f"SELECT {', '.join(self._OBLIGATION_COLUMNS)} FROM settlement_obligations WHERE agreement_ref=? ORDER BY obligation_index",
                    (agreement_ref,),
                ).fetchall()
                return [self._obligation(row) for row in rows]
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def save_settlement_obligation(
        self, obligation: dict[str, Any], *, expected_version: int
    ) -> bool:
        if (
            obligation.get("collection_state") == "succeeded"
            and obligation.get("reclaim_state") == "succeeded"
        ):
            raise ValueError("collection and reclaim cannot both succeed")

        def run() -> bool:
            conn = self._connect()
            try:

                def j(name: str, default: Any = None) -> str | None:
                    value = obligation.get(name, default)
                    return canonical_json(value) if value is not None else None

                changed = conn.execute(
                    """
                    UPDATE settlement_obligations SET mechanism_ref=?,
                      mechanism_status=?, mechanism_state=?, buyer_action=?,
                      condition_anchor=?, fulfillment_ref=?, materialization_state=?,
                      condition_state=?, collection_state=?, reclaim_state=?,
                      materialization_receipt=?, status_receipt=?,
                      collection_receipt=?, reclaim_receipt=?, last_error=?,
                      version=version+1, updated_at=?
                    WHERE obligation_ref=? AND version=?
                    """,
                    (
                        obligation.get("mechanism_ref"),
                        obligation.get("mechanism_status"),
                        canonical_json(obligation.get("mechanism_state") or {}),
                        j("buyer_action"),
                        obligation.get("condition_anchor"),
                        obligation.get("fulfillment_ref"),
                        obligation["materialization_state"],
                        obligation["condition_state"],
                        obligation["collection_state"],
                        obligation["reclaim_state"],
                        j("materialization_receipt"),
                        j("status_receipt"),
                        j("collection_receipt"),
                        j("reclaim_receipt"),
                        obligation.get("last_error"),
                        self._now(),
                        obligation["obligation_ref"],
                        expected_version,
                    ),
                ).rowcount
                conn.commit()
                return changed == 1
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def bind_settlement_mechanism_params(
        self, *, obligation_ref: str, mechanism_params: dict[str, Any]
    ) -> dict[str, Any]:
        if not mechanism_params:
            raise ValueError("mechanism_params must be non-empty")
        encoded = canonical_json(mechanism_params)

        def run() -> dict[str, Any]:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT mechanism_params, materialization_state "
                    "FROM settlement_obligations WHERE obligation_ref=?",
                    (obligation_ref,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown settlement obligation {obligation_ref!r}")
                existing, materialization_state = row
                existing = existing or "{}"
                if existing == encoded:
                    pass
                elif existing != "{}":
                    raise ValueError("mechanism_params are immutable once bound")
                else:
                    operation = conn.execute(
                        "SELECT 1 FROM settlement_operations "
                        "WHERE obligation_ref=? AND operation='materialize'",
                        (obligation_ref,),
                    ).fetchone()
                    if materialization_state != "pending" or operation is not None:
                        raise ValueError(
                            "mechanism_params cannot bind after materialization starts"
                        )
                    changed = conn.execute(
                        "UPDATE settlement_obligations SET mechanism_params=?, "
                        "version=version+1, updated_at=? "
                        "WHERE obligation_ref=? AND mechanism_params='{}' "
                        "AND materialization_state='pending'",
                        (encoded, self._now(), obligation_ref),
                    ).rowcount
                    if changed != 1:
                        raise ValueError("mechanism_params binding lost its compare-and-set")
                result = conn.execute(
                    f"SELECT {', '.join(self._OBLIGATION_COLUMNS)} "
                    "FROM settlement_obligations WHERE obligation_ref=?",
                    (obligation_ref,),
                ).fetchone()
                conn.commit()
                assert result is not None
                return self._obligation(result)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def bind_settlement_fulfillment(
        self, *, obligation_ref: str, fulfillment_ref: str
    ) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT fulfillment_ref, reclaim_state "
                    "FROM settlement_obligations WHERE obligation_ref=?",
                    (obligation_ref,),
                ).fetchone()
                if row is None:
                    raise KeyError(f"unknown settlement obligation {obligation_ref!r}")
                existing_ref, reclaim_state = row
                if existing_ref is not None and existing_ref != fulfillment_ref:
                    raise ValueError("fulfillment_ref is immutable once bound")
                if existing_ref is None:
                    if reclaim_state in {"in_progress", "succeeded"}:
                        raise ValueError(
                            "fulfillment cannot bind after reclaim reservation"
                        )
                    changed = conn.execute(
                        "UPDATE settlement_obligations SET fulfillment_ref=?, "
                        "version=version+1, updated_at=? WHERE obligation_ref=? "
                        "AND reclaim_state NOT IN ('in_progress','succeeded')",
                        (fulfillment_ref, self._now(), obligation_ref),
                    ).rowcount
                    if changed != 1:
                        raise ValueError(
                            "fulfillment lost the collect-versus-reclaim reservation"
                        )
                result = conn.execute(
                    f"SELECT {', '.join(self._OBLIGATION_COLUMNS)} "
                    "FROM settlement_obligations WHERE obligation_ref=?",
                    (obligation_ref,),
                ).fetchone()
                conn.commit()
                assert result is not None
                return self._obligation(result)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def upsert_settlement_operation(
        self, operation: dict[str, Any]
    ) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            now = self._now()
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO settlement_operations
                      (obligation_ref, operation, request_hash, state, attempts,
                       uncertain_acknowledgement, receipt, last_error,
                       lease_owner, lease_until_unix, next_attempt_unix,
                       created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        operation["obligation_ref"],
                        operation["operation"],
                        operation["request_hash"],
                        operation.get("state") or "pending",
                        int(operation.get("attempts") or 0),
                        int(bool(operation.get("uncertain_acknowledgement"))),
                        canonical_json(operation["receipt"])
                        if operation.get("receipt") is not None
                        else None,
                        operation.get("last_error"),
                        operation.get("lease_owner"),
                        operation.get("lease_until_unix"),
                        operation.get("next_attempt_unix"),
                        now,
                        now,
                    ),
                )
                row = conn.execute(
                    f"SELECT {', '.join(self._OPERATION_COLUMNS)} "
                    "FROM settlement_operations WHERE obligation_ref=? AND operation=?",
                    (operation["obligation_ref"], operation["operation"]),
                ).fetchone()
                conn.commit()
                if row is None:
                    raise RuntimeError("settlement operation insert was lost")
                stored = self._operation(row)
                if stored["request_hash"] != operation["request_hash"]:
                    raise ValueError(
                        "settlement operation was reused with a different request"
                    )
                return stored
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def load_settlement_operation(
        self, obligation_ref: str, operation: str
    ) -> dict[str, Any] | None:
        def run() -> dict[str, Any] | None:
            conn = self._connect()
            try:
                row = conn.execute(
                    f"SELECT {', '.join(self._OPERATION_COLUMNS)} "
                    "FROM settlement_operations WHERE obligation_ref=? AND operation=?",
                    (obligation_ref, operation),
                ).fetchone()
                return self._operation(row) if row else None
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def reserve_settlement_operation(
        self,
        *,
        obligation_ref: str,
        operation: str,
        request_hash: str,
        lease_owner: str,
        now_unix: float,
        lease_until_unix: float,
    ) -> dict[str, Any] | None:
        if operation not in {
            "materialize",
            "status",
            "fulfill",
            "check",
            "collect",
            "reclaim",
        }:
            raise ValueError(f"unsupported settlement operation {operation!r}")
        if lease_until_unix <= now_unix:
            raise ValueError("lease_until_unix must be in the future")

        def run() -> dict[str, Any] | None:
            now = self._now()
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                lifecycle = conn.execute(
                    "SELECT collection_state, reclaim_state, fulfillment_ref, "
                    "condition_state FROM settlement_obligations "
                    "WHERE obligation_ref=?",
                    (obligation_ref,),
                ).fetchone()
                if lifecycle is None:
                    raise KeyError(f"unknown settlement obligation {obligation_ref!r}")
                (
                    collection_state,
                    reclaim_state,
                    fulfillment_ref,
                    condition_state,
                ) = lifecycle
                if operation in {"fulfill", "check", "collect"} and reclaim_state in {
                    "in_progress",
                    "succeeded",
                }:
                    conn.rollback()
                    return None
                if operation == "reclaim":
                    active_conflict = conn.execute(
                        "SELECT 1 FROM settlement_operations "
                        "WHERE obligation_ref=? AND operation IN ('fulfill','check') "
                        "AND state='in_progress' AND COALESCE(lease_until_unix, 0)>=? "
                        "LIMIT 1",
                        (obligation_ref, now_unix),
                    ).fetchone()
                    if (
                        collection_state in {"in_progress", "succeeded"}
                        or fulfillment_ref is not None
                        or condition_state == "ready"
                        or active_conflict is not None
                    ):
                        conn.rollback()
                        return None
                conn.execute(
                    """
                    INSERT OR IGNORE INTO settlement_operations
                      (obligation_ref, operation, request_hash, state, attempts,
                       uncertain_acknowledgement, created_at, updated_at)
                    VALUES (?, ?, ?, 'pending', 0, 0, ?, ?)
                    """,
                    (obligation_ref, operation, request_hash, now, now),
                )
                row = conn.execute(
                    f"SELECT {', '.join(self._OPERATION_COLUMNS)} "
                    "FROM settlement_operations WHERE obligation_ref=? AND operation=?",
                    (obligation_ref, operation),
                ).fetchone()
                assert row is not None
                stored = self._operation(row)
                if stored["request_hash"] != request_hash:
                    raise ValueError(
                        "settlement operation was reused with a different request"
                    )
                if stored["state"] in {"succeeded", "manual_required"}:
                    conn.commit()
                    return stored
                if (
                    stored["state"] == "in_progress"
                    and stored["lease_owner"] != lease_owner
                    and stored["lease_until_unix"] is not None
                    and float(stored["lease_until_unix"]) >= now_unix
                ):
                    conn.rollback()
                    return None
                conn.execute(
                    """
                    UPDATE settlement_operations
                    SET state='in_progress', attempts=attempts+1,
                        lease_owner=?, lease_until_unix=?,
                        next_attempt_unix=NULL, updated_at=?
                    WHERE obligation_ref=? AND operation=?
                    """,
                    (lease_owner, lease_until_unix, now, obligation_ref, operation),
                )
                if operation == "materialize":
                    conn.execute(
                        "UPDATE settlement_obligations SET "
                        "materialization_state='in_progress', version=version+1, "
                        "updated_at=? WHERE obligation_ref=? "
                        "AND materialization_state!='materialized'",
                        (now, obligation_ref),
                    )
                elif operation == "collect":
                    conn.execute(
                        "UPDATE settlement_obligations SET "
                        "collection_state='in_progress', version=version+1, "
                        "updated_at=? WHERE obligation_ref=? "
                        "AND reclaim_state NOT IN ('in_progress','succeeded')",
                        (now, obligation_ref),
                    )
                elif operation == "reclaim":
                    changed = conn.execute(
                        "UPDATE settlement_obligations SET "
                        "reclaim_state='in_progress', version=version+1, "
                        "updated_at=? WHERE obligation_ref=? "
                        "AND collection_state NOT IN ('in_progress','succeeded') "
                        "AND fulfillment_ref IS NULL AND condition_state!='ready'",
                        (now, obligation_ref),
                    ).rowcount
                    if changed != 1:
                        conn.rollback()
                        return None
                result = conn.execute(
                    f"SELECT {', '.join(self._OPERATION_COLUMNS)} "
                    "FROM settlement_operations WHERE obligation_ref=? AND operation=?",
                    (obligation_ref, operation),
                ).fetchone()
                conn.commit()
                assert result is not None
                return self._operation(result)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def finish_settlement_operation(
        self,
        *,
        obligation_ref: str,
        operation: str,
        lease_owner: str,
        state: str,
        receipt: dict[str, Any] | None = None,
        last_error: str | None = None,
        uncertain_acknowledgement: bool = False,
        mechanism_ref: str | None = None,
        mechanism_status: str | None = None,
        mechanism_state: dict[str, Any] | None = None,
        buyer_action: dict[str, Any] | None = None,
        condition_anchor: str | None = None,
        condition_state: str | None = None,
        next_attempt_unix: float | None = None,
    ) -> bool:
        if state not in {"pending", "succeeded", "manual_required"}:
            raise ValueError(f"unsupported operation outcome {state!r}")

        def run() -> bool:
            now = self._now()
            receipt_json = canonical_json(receipt) if receipt is not None else None
            mechanism_json = (
                canonical_json(mechanism_state) if mechanism_state is not None else None
            )
            action_json = (
                canonical_json(buyer_action) if buyer_action is not None else None
            )
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                changed = conn.execute(
                    """
                    UPDATE settlement_operations SET state=?,
                      uncertain_acknowledgement=?,
                      receipt=COALESCE(?, receipt), last_error=?,
                      lease_owner=NULL, lease_until_unix=NULL,
                      next_attempt_unix=?, updated_at=?
                    WHERE obligation_ref=? AND operation=?
                      AND state='in_progress' AND lease_owner=?
                    """,
                    (
                        state,
                        int(uncertain_acknowledgement),
                        receipt_json,
                        last_error,
                        next_attempt_unix,
                        now,
                        obligation_ref,
                        operation,
                        lease_owner,
                    ),
                ).rowcount
                if changed != 1:
                    conn.rollback()
                    return False
                if operation == "materialize":
                    lifecycle = {
                        "pending": "pending",
                        "succeeded": "materialized",
                        "manual_required": "manual_required",
                    }[state]
                    conn.execute(
                        """
                        UPDATE settlement_obligations SET
                          materialization_state=?,
                          mechanism_ref=COALESCE(?, mechanism_ref),
                          mechanism_status=COALESCE(?, mechanism_status),
                          mechanism_state=COALESCE(?, mechanism_state),
                          buyer_action=?,
                          condition_anchor=COALESCE(?, condition_anchor),
                          materialization_receipt=
                            COALESCE(?, materialization_receipt),
                          last_error=?, version=version+1, updated_at=?
                        WHERE obligation_ref=?
                        """,
                        (
                            lifecycle,
                            mechanism_ref,
                            mechanism_status,
                            mechanism_json,
                            action_json,
                            condition_anchor,
                            receipt_json,
                            last_error,
                            now,
                            obligation_ref,
                        ),
                    )
                elif operation == "status":
                    materialization = (
                        "manual_required"
                        if mechanism_status == "manual_required"
                        else "materialized"
                        if mechanism_status
                        in {"ready", "collected", "reclaimed", "expired"}
                        else None
                    )
                    conn.execute(
                        """
                        UPDATE settlement_obligations SET
                          mechanism_ref=COALESCE(?, mechanism_ref),
                          mechanism_status=COALESCE(?, mechanism_status),
                          mechanism_state=COALESCE(?, mechanism_state),
                          buyer_action=?,
                          condition_anchor=COALESCE(?, condition_anchor),
                          materialization_state=CASE
                            WHEN collection_state='succeeded'
                              THEN materialization_state
                            ELSE COALESCE(?, materialization_state) END,
                          collection_state=CASE WHEN ?='collected'
                            THEN 'succeeded' ELSE collection_state END,
                          reclaim_state=CASE WHEN ?='reclaimed'
                            THEN 'succeeded' ELSE reclaim_state END,
                          condition_state=CASE WHEN ?='failed'
                            THEN 'failed' ELSE condition_state END,
                          status_receipt=COALESCE(?, status_receipt),
                          last_error=?, version=version+1, updated_at=?
                        WHERE obligation_ref=?
                        """,
                        (
                            mechanism_ref,
                            mechanism_status,
                            mechanism_json,
                            action_json,
                            condition_anchor,
                            materialization,
                            mechanism_status,
                            mechanism_status,
                            mechanism_status,
                            receipt_json,
                            last_error,
                            now,
                            obligation_ref,
                        ),
                    )
                elif operation == "check":
                    resolved = (
                        condition_state
                        or {
                            "pending": "pending",
                            "succeeded": "ready",
                            "manual_required": "manual_required",
                        }[state]
                    )
                    if resolved not in {
                        "pending",
                        "ready",
                        "failed",
                        "manual_required",
                    }:
                        raise ValueError(f"unsupported condition state {resolved!r}")
                    conn.execute(
                        """
                        UPDATE settlement_obligations SET condition_state=?,
                          mechanism_state=COALESCE(?, mechanism_state),
                          last_error=?, version=version+1, updated_at=?
                        WHERE obligation_ref=?
                        """,
                        (
                            resolved,
                            mechanism_json,
                            last_error,
                            now,
                            obligation_ref,
                        ),
                    )
                elif operation == "collect":
                    lifecycle = {
                        "pending": "pending",
                        "succeeded": "succeeded",
                        "manual_required": "manual_required",
                    }[state]
                    conn.execute(
                        """
                        UPDATE settlement_obligations SET collection_state=?,
                          collection_receipt=
                            COALESCE(?, collection_receipt),
                          mechanism_state=COALESCE(?, mechanism_state),
                          last_error=?, version=version+1, updated_at=?
                        WHERE obligation_ref=?
                          AND reclaim_state!='succeeded'
                        """,
                        (
                            lifecycle,
                            receipt_json,
                            mechanism_json,
                            last_error,
                            now,
                            obligation_ref,
                        ),
                    )
                elif operation == "reclaim":
                    lifecycle = {
                        "pending": "pending",
                        "succeeded": "succeeded",
                        "manual_required": "manual_required",
                    }[state]
                    conn.execute(
                        """
                        UPDATE settlement_obligations SET reclaim_state=?,
                          reclaim_receipt=COALESCE(?, reclaim_receipt),
                          mechanism_state=COALESCE(?, mechanism_state),
                          last_error=?, version=version+1, updated_at=?
                        WHERE obligation_ref=?
                          AND collection_state!='succeeded'
                        """,
                        (
                            lifecycle,
                            receipt_json,
                            mechanism_json,
                            last_error,
                            now,
                            obligation_ref,
                        ),
                    )
                conn.commit()
                return True
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def list_due_settlement_obligations(
        self, *, now_unix: float, limit: int = 50
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        def run() -> list[dict[str, Any]]:
            conn = self._connect()
            try:
                columns = ", ".join(
                    f"o.{column}" for column in self._OBLIGATION_COLUMNS
                )
                rows = conn.execute(
                    f"""
                    SELECT {columns}
                    FROM settlement_obligations o
                    LEFT JOIN settlement_operations op
                      ON op.obligation_ref=o.obligation_ref
                     AND op.operation=CASE
                       WHEN o.mechanism_status='failed'
                         AND o.collection_state!='succeeded'
                         THEN 'cleanup'
                       WHEN o.collection_state='succeeded' THEN 'status'
                       WHEN o.condition_state='ready' THEN 'collect'
                       WHEN o.mechanism_status='ready' THEN 'check'
                       ELSE 'status' END
                    WHERE o.fulfillment_ref IS NOT NULL
                      AND (
                        o.collection_state NOT IN ('succeeded','manual_required')
                        OR (
                          o.collection_state='succeeded'
                          AND json_extract(
                            o.mechanism_state,
                            '$.terminal_risk_monitoring'
                          )=1
                        )
                      )
                      AND o.reclaim_state
                        NOT IN ('succeeded','manual_required')
                      AND (
                        o.condition_state NOT IN ('failed','manual_required')
                        OR (
                          o.condition_state='failed'
                          AND o.mechanism_status='failed'
                          AND o.collection_state!='succeeded'
                        )
                      )
                      AND (
                        COALESCE(o.mechanism_status, '') NOT IN (
                          'collected','reclaimed','expired','failed',
                          'manual_required'
                        )
                        OR (
                          o.mechanism_status='collected'
                          AND json_extract(
                            o.mechanism_state,
                            '$.terminal_risk_monitoring'
                          )=1
                        )
                        OR (
                          o.mechanism_status='failed'
                          AND o.collection_state!='succeeded'
                        )
                      )
                      AND (
                        op.state IS NULL OR op.state='pending'
                        OR (op.state='in_progress'
                            AND COALESCE(op.lease_until_unix, 0) < ?)
                      )
                      AND (
                        op.next_attempt_unix IS NULL
                        OR op.next_attempt_unix <= ?
                      )
                      AND NOT EXISTS (
                        SELECT 1 FROM settlement_operations status_op
                        WHERE status_op.obligation_ref=o.obligation_ref
                          AND status_op.operation='status'
                          AND (
                            status_op.next_attempt_unix > ?
                            OR (
                              status_op.state='in_progress'
                              AND COALESCE(status_op.lease_until_unix, 0) >= ?
                            )
                          )
                      )
                    ORDER BY o.updated_at, o.obligation_ref
                    LIMIT ?
                    """,
                    (now_unix, now_unix, now_unix, now_unix, limit),
                ).fetchall()
                return [self._obligation(row) for row in rows]
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def schedule_settlement_retry(
        self,
        *,
        obligation_ref: str,
        operation: str,
        next_attempt_unix: float,
        last_error: str | None = None,
    ) -> None:
        def run() -> None:
            conn = self._connect()
            try:
                changed = conn.execute(
                    """
                    UPDATE settlement_operations SET next_attempt_unix=?,
                      last_error=COALESCE(?, last_error), updated_at=?
                    WHERE obligation_ref=? AND operation=? AND state='pending'
                    """,
                    (
                        next_attempt_unix,
                        last_error,
                        self._now(),
                        obligation_ref,
                        operation,
                    ),
                ).rowcount
                if changed != 1:
                    raise KeyError(
                        f"no pending {operation!r} operation for {obligation_ref!r}"
                    )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(run)

    async def wake_settlement_obligation(self, obligation_ref: str) -> None:
        def run() -> None:
            conn = self._connect()
            try:
                exists = conn.execute(
                    "SELECT 1 FROM settlement_obligations WHERE obligation_ref=?",
                    (obligation_ref,),
                ).fetchone()
                if exists is None:
                    raise KeyError(f"unknown settlement obligation {obligation_ref!r}")
                conn.execute(
                    """
                    UPDATE settlement_operations SET next_attempt_unix=NULL,
                      updated_at=?
                    WHERE obligation_ref=? AND state='pending'
                    """,
                    (self._now(), obligation_ref),
                )
                conn.commit()
            finally:
                conn.close()

        await asyncio.to_thread(run)
