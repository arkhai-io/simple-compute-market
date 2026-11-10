"""SQLite persistence for the settlement runtime.

The runtime's tables belong to the storefront chain that composes
:data:`market_settlement_runtime.migrations.BASELINE`; the repository reads and
writes them and issues no DDL.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Literal

from market_identity import Identity

from .models import canonical_json


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
        "awaiting_delivery",
    )

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _obligation(self, row: tuple[Any, ...]) -> dict[str, Any]:
        value = dict(zip(self._OBLIGATION_COLUMNS, row))
        for field in self._OBLIGATION_JSON_FIELDS:
            raw = value.get(field)
            if field in {"payer_principal", "claimant_principal"}:
                if not raw:
                    raise ValueError(f"settlement obligation has no canonical {field}")
                try:
                    principal = Identity.model_validate(json.loads(raw))
                except (TypeError, ValueError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        f"settlement obligation has malformed {field}"
                    ) from exc
                canonical = canonical_json(principal.model_dump(mode="json"))
                if raw != canonical:
                    raise ValueError(f"settlement obligation has non-canonical {field}")
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
        value["awaiting_delivery"] = bool(value["awaiting_delivery"])
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
                        raise ValueError(
                            "mechanism_params binding lost its compare-and-set"
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
            "cleanup",
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
                    "condition_state, mechanism_status FROM settlement_obligations "
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
                    mechanism_status,
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
                    cleanup_complete = conn.execute(
                        "SELECT 1 FROM settlement_operations "
                        "WHERE obligation_ref=? AND operation='cleanup' "
                        "AND state='succeeded'",
                        (obligation_ref,),
                    ).fetchone()
                    returned_cleanup_complete = (
                        mechanism_status == "failed" and cleanup_complete is not None
                    )
                    if (
                        collection_state in {"in_progress", "succeeded"}
                        or (
                            fulfillment_ref is not None
                            and not returned_cleanup_complete
                        )
                        or condition_state == "ready"
                        and not returned_cleanup_complete
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
                        next_attempt_unix=NULL, awaiting_delivery=0,
                        updated_at=?
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
                        "AND ((fulfillment_ref IS NULL AND condition_state!='ready') "
                        "OR (mechanism_status='failed' AND EXISTS ("
                        "SELECT 1 FROM settlement_operations cleanup_op "
                        "WHERE cleanup_op.obligation_ref=settlement_obligations.obligation_ref "
                        "AND cleanup_op.operation='cleanup' "
                        "AND cleanup_op.state='succeeded')))",
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

    async def write_operation_receipt_field(
        self,
        *,
        obligation_ref: str,
        operation: str,
        lease_owner: str,
        key: str,
        value: Any,
        uncertain_acknowledgement: bool,
    ) -> Literal["written", "unchanged", "conflict", "lost"]:
        """Write one receipt field of a leased operation, first write wins.

        The field records something the holder did outside this journal, so it
        is never overwritten: an equal value is a replay and changes nothing, a
        different value is a changed reuse of the operation and is refused.
        Only the lease holder writes, so a worker whose lease was taken over
        cannot record an effect for an attempt that is no longer its own.
        """

        def run() -> Literal["written", "unchanged", "conflict", "lost"]:
            now = self._now()
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT receipt FROM settlement_operations "
                    "WHERE obligation_ref=? AND operation=? "
                    "AND state='in_progress' AND lease_owner=?",
                    (obligation_ref, operation, lease_owner),
                ).fetchone()
                if row is None:
                    conn.rollback()
                    return "lost"
                receipt = json.loads(row[0]) if row[0] else {}
                if key in receipt:
                    conn.rollback()
                    if canonical_json(receipt[key]) == canonical_json(value):
                        return "unchanged"
                    return "conflict"
                receipt[key] = value
                conn.execute(
                    "UPDATE settlement_operations SET receipt=?, "
                    "uncertain_acknowledgement=MAX(uncertain_acknowledgement, ?), "
                    "updated_at=? WHERE obligation_ref=? AND operation=?",
                    (
                        canonical_json(receipt),
                        int(uncertain_acknowledgement),
                        now,
                        obligation_ref,
                        operation,
                    ),
                )
                conn.commit()
                return "written"
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def clear_operation_receipt_field(
        self,
        *,
        obligation_ref: str,
        operation: str,
        lease_owner: str,
        key: str,
        unless_key: str,
    ) -> Literal["cleared", "refused", "lost"]:
        """Remove one receipt field of a leased operation unless another is set.

        ``unless_key`` names the field whose presence makes the removal unsafe:
        once an operation has recorded what its effect created, the record that
        the effect was attempted is part of that evidence.
        """

        def run() -> Literal["cleared", "refused", "lost"]:
            now = self._now()
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT receipt FROM settlement_operations "
                    "WHERE obligation_ref=? AND operation=? "
                    "AND state='in_progress' AND lease_owner=?",
                    (obligation_ref, operation, lease_owner),
                ).fetchone()
                if row is None:
                    conn.rollback()
                    return "lost"
                receipt = json.loads(row[0]) if row[0] else {}
                if unless_key in receipt:
                    conn.rollback()
                    return "refused"
                receipt.pop(key, None)
                conn.execute(
                    "UPDATE settlement_operations SET receipt=?, updated_at=? "
                    "WHERE obligation_ref=? AND operation=?",
                    (
                        canonical_json(receipt) if receipt else None,
                        now,
                        obligation_ref,
                        operation,
                    ),
                )
                conn.commit()
                return "cleared"
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        return await asyncio.to_thread(run)

    async def count_manual_required(self) -> int:
        """Count the obligations waiting for an operator, each once.

        An obligation waits when its mechanism parked it or when any of its
        operations did; the two are counted together so an obligation parked
        both ways is still one obligation an operator has to look at.
        """

        def run() -> int:
            conn = self._connect()
            try:
                row = conn.execute(
                    """
                    SELECT COUNT(*) FROM settlement_obligations o
                    WHERE o.mechanism_status='manual_required'
                       OR EXISTS (
                         SELECT 1 FROM settlement_operations op
                         WHERE op.obligation_ref=o.obligation_ref
                           AND op.state='manual_required'
                       )
                    """
                ).fetchone()
                return int(row[0]) if row is not None else 0
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
                elif operation == "fulfill" and state == "manual_required":
                    # A fulfillment has no lifecycle column of its own; a park
                    # records its reason where every other park does.
                    conn.execute(
                        """
                        UPDATE settlement_obligations SET
                          mechanism_state=COALESCE(?, mechanism_state),
                          last_error=?, version=version+1, updated_at=?
                        WHERE obligation_ref=?
                        """,
                        (mechanism_json, last_error, now, obligation_ref),
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

    async def mark_fulfillment_awaiting_delivery(
        self,
        *,
        obligation_ref: str,
        lease_owner: str,
        now_unix: float,
    ) -> bool:
        """Release a held fulfillment whose delivery is not yet ready, in one write.

        The attempt the lease counted is returned and the operation stays
        ``pending``, due at ``now_unix`` and marked awaiting delivery, with no
        error, since waiting is not a failure. Answers ``False``, writing
        nothing, when the caller no longer holds the lease.
        """

        def run() -> bool:
            conn = self._connect()
            try:
                changed = conn.execute(
                    """
                    UPDATE settlement_operations SET state='pending',
                      attempts=MAX(attempts - 1, 0), awaiting_delivery=1,
                      uncertain_acknowledgement=0, last_error=NULL,
                      lease_owner=NULL, lease_until_unix=NULL,
                      next_attempt_unix=?, updated_at=?
                    WHERE obligation_ref=? AND operation='fulfill'
                      AND state='in_progress' AND lease_owner=?
                    """,
                    (now_unix, self._now(), obligation_ref, lease_owner),
                ).rowcount
                conn.commit()
                return changed == 1
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
                       WHEN o.mechanism_status='ready'
                         AND o.fulfillment_ref IS NULL THEN 'fulfill'
                       WHEN o.condition_state='ready' THEN 'collect'
                       WHEN o.mechanism_status='ready' THEN 'check'
                       ELSE 'status' END
                    -- A ready obligation whose fulfillment never started is
                    -- due through its 'fulfill' operation, so the worker's
                    -- ready hook starts it and its retry schedule governs
                    -- every later attempt.
                    WHERE (
                        o.fulfillment_ref IS NOT NULL
                        OR o.mechanism_status='ready'
                      )
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
                # A scheduled retry ends any wait on delivery: the worker
                # honours a mark once, and the next ready step writes its own.
                changed = conn.execute(
                    """
                    UPDATE settlement_operations SET next_attempt_unix=?,
                      last_error=COALESCE(?, last_error), awaiting_delivery=0,
                      updated_at=?
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
