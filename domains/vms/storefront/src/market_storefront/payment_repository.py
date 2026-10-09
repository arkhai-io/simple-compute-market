"""VM settlement evidence and independent negotiation-scoped delivery state."""

from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from market_core import SettlementEvidence

from market_storefront.services.vm_fulfillment_planner import (
    VERIFIED_EVIDENCE_STATUSES,
    build_vm_fulfillment_plan,
)


class VmSettlementEvidenceConflict(ValueError):
    """An accepted negotiation or established reference cannot be retargeted."""


def add_vm_settlement_records(conn: Any) -> None:
    if conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='vm_payment_records'"
    ).fetchone():
        raise RuntimeError("VM settlement schema requires an explicit database reset")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vm_settlement_evidence (
            negotiation_id TEXT PRIMARY KEY,
            mechanism TEXT NOT NULL,
            agreement_sha256 TEXT NOT NULL,
            settlement_ref TEXT UNIQUE,
            status TEXT NOT NULL
                CHECK (status IN ('pending', 'verified', 'refunding', 'refunded')),
            evidence_json TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vm_delivery_records (
            negotiation_id TEXT PRIMARY KEY REFERENCES vm_settlement_evidence(negotiation_id),
            status TEXT NOT NULL,
            fulfillment_uid TEXT,
            provisioning_job_id TEXT,
            connection_details TEXT,
            tenant_credentials TEXT,
            reason TEXT,
            capacity_reservation_id TEXT,
            settlement_resource_id TEXT,
            fulfillment_id TEXT,
            fulfillment_context TEXT,
            fulfillment_phase TEXT,
            processing_owner TEXT,
            processing_lease_until TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VmSettlementRepository:
    db_path: str

    async def list_unsettled_payment_negotiations(
        self, *, mechanism: str, limit: int
    ) -> list[str]:
        """Accepted deals of ``mechanism`` the seller has not carried to delivery, oldest first.

        A deal qualifies when it has no delivery record and no refund, whether
        its evidence is missing, pending, or verified without a delivery start,
        or when a refund was left ``refunding``. A deal with a delivery record
        belongs to the fulfillment resume sweep. The filter runs before the
        limit, so completed deals never crowd out an unsettled one, and a
        malformed Agreement is skipped rather than failing the query.
        """

        def load() -> list[str]:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT t.negotiation_id
                    FROM negotiation_threads t
                    LEFT JOIN vm_settlement_evidence e ON e.negotiation_id = t.negotiation_id
                    LEFT JOIN vm_delivery_records d ON d.negotiation_id = t.negotiation_id
                    WHERE t.terminal_state = 'success'
                      AND t.agreement_bytes IS NOT NULL
                      AND CASE WHEN json_valid(CAST(t.agreement_bytes AS TEXT))
                          THEN json_extract(CAST(t.agreement_bytes AS TEXT), '$.settlement.mechanism')
                          END = ?
                      AND (
                        e.status = 'refunding'
                        OR (
                          d.negotiation_id IS NULL
                          AND (e.negotiation_id IS NULL OR e.status IN ('pending', 'verified'))
                        )
                      )
                    ORDER BY t.created_at ASC, t.negotiation_id ASC
                    LIMIT ?
                    """,
                    (mechanism, limit),
                ).fetchall()
            return [str(row[0]) for row in rows]

        return await asyncio.to_thread(load)

    async def load_vm_settlement_evidence(
        self, *, negotiation_id: str
    ) -> SettlementEvidence | None:
        def load():
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT mechanism, settlement_ref, status, evidence_json FROM vm_settlement_evidence WHERE negotiation_id=?",
                    (negotiation_id,),
                ).fetchone()
                return (
                    SettlementEvidence(
                        negotiation_id, row[0], row[1], row[2], json.loads(row[3])
                    )
                    if row
                    else None
                )

        return await asyncio.to_thread(load)

    async def save_vm_settlement_evidence(self, evidence: SettlementEvidence) -> None:
        """Record pending or verified evidence; refund states move only by transition."""
        if evidence.status not in ("pending", "verified"):
            raise ValueError(
                "VM evidence is saved pending or verified; refund states are transitions"
            )
        payload = dict(evidence.evidence)
        if payload.get("schema") != "vm.settlement-evidence.v1" or not payload.get(
            "agreement_sha256"
        ):
            raise ValueError(
                "VM evidence requires versioned accepted Agreement identity"
            )
        digest = payload["agreement_sha256"]
        if evidence.status == "verified":
            if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                raise ValueError("verified VM evidence requires a sha256 Agreement digest")
            source = payload.get("source")
            if not isinstance(source, Mapping) or not source:
                raise ValueError("verified VM evidence requires an authoritative source")
            delivery = payload.get("delivery")
            if (
                not isinstance(delivery, Mapping)
                or delivery.get("kind") != "vm.delivery-facts"
                or type(delivery.get("schema_version")) is not int
                or delivery.get("schema_version") != 1
                or not isinstance(delivery.get("payload"), Mapping)
            ):
                raise ValueError("verified VM evidence requires supported delivery facts")
            build_vm_fulfillment_plan(evidence=evidence)
        wire = _json(payload)

        def save():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute(
                    "SELECT mechanism, agreement_sha256, settlement_ref, status, evidence_json FROM vm_settlement_evidence WHERE negotiation_id=?",
                    (evidence.negotiation_id,),
                ).fetchone()
                if current:
                    if (
                        current[0] != evidence.mechanism
                        or current[1] != digest
                        or (
                            current[2] is not None
                            and current[2] != evidence.settlement_ref
                        )
                        or (
                            current[3] in VERIFIED_EVIDENCE_STATUSES
                            and (current[3] != evidence.status or current[4] != wire)
                        )
                    ):
                        raise VmSettlementEvidenceConflict(
                            "settlement evidence conflicts with accepted Agreement"
                        )
                    conn.execute(
                        "UPDATE vm_settlement_evidence SET settlement_ref=?, status=?, evidence_json=? WHERE negotiation_id=?",
                        (
                            evidence.settlement_ref,
                            evidence.status,
                            wire,
                            evidence.negotiation_id,
                        ),
                    )
                else:
                    conn.execute(
                        "INSERT INTO vm_settlement_evidence VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            evidence.negotiation_id,
                            evidence.mechanism,
                            digest,
                            evidence.settlement_ref,
                            evidence.status,
                            wire,
                        ),
                    )

        await asyncio.to_thread(save)

    async def record_vm_refund_intent(self, *, negotiation_id: str) -> str:
        """Move verified evidence to ``refunding`` before a reversal is requested.

        Returns the status found. Intent is recorded only from ``verified``;
        ``refunding`` and ``refunded`` are returned unchanged, so an interrupted
        refund resumes and a completed one is never repeated. Any other state
        raises, so an unpaid deal never acquires refund intent. This and the
        delivery-record insert, which requires ``verified``, are each one
        serialized write, so exactly one decides whether delivery precedes the
        refund.
        """

        def record() -> str:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT status FROM vm_settlement_evidence WHERE negotiation_id=?",
                    (negotiation_id,),
                ).fetchone()
                if row is None or row[0] not in VERIFIED_EVIDENCE_STATUSES:
                    raise ValueError("refund requires verified settlement evidence")
                if row[0] == "verified":
                    conn.execute(
                        "UPDATE vm_settlement_evidence SET status='refunding' WHERE negotiation_id=?",
                        (negotiation_id,),
                    )
                return str(row[0])

        return await asyncio.to_thread(record)

    async def abandon_vm_refund_intent(self, *, negotiation_id: str) -> None:
        """Restore ``verified`` when a reversal proved impossible.

        Only ``refunding`` is restored, and it is only ever entered from
        ``verified``, so a deal with nothing to reverse is not left blocked.
        """

        def abandon() -> None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE vm_settlement_evidence SET status='verified' WHERE negotiation_id=? AND status='refunding'",
                    (negotiation_id,),
                )

        await asyncio.to_thread(abandon)

    async def complete_vm_refund(self, *, negotiation_id: str) -> None:
        """Record the reversal; ``refunded`` is terminal and never overwritten."""

        def complete() -> None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT status FROM vm_settlement_evidence WHERE negotiation_id=?",
                    (negotiation_id,),
                ).fetchone()
                if row is None or row[0] not in ("refunding", "refunded"):
                    raise ValueError("refund completion requires recorded refund intent")
                conn.execute(
                    "UPDATE vm_settlement_evidence SET status='refunded' WHERE negotiation_id=? AND status='refunding'",
                    (negotiation_id,),
                )

        await asyncio.to_thread(complete)

    async def insert_vm_delivery(self, *, negotiation_id: str) -> bool:
        def insert():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                source = conn.execute(
                    "SELECT status FROM vm_settlement_evidence WHERE negotiation_id=?",
                    (negotiation_id,),
                ).fetchone()
                if source != ("verified",):
                    raise ValueError(
                        "VM delivery requires verified settlement evidence"
                    )
                now = _now()
                cursor = conn.execute(
                    "INSERT OR IGNORE INTO vm_delivery_records (negotiation_id, status, created_at, updated_at) VALUES (?, 'provisioning', ?, ?)",
                    (negotiation_id, now, now),
                )
                return cursor.rowcount == 1

        return await asyncio.to_thread(insert)

    async def load_vm_delivery(self, *, negotiation_id: str) -> dict[str, Any] | None:
        def load():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM vm_delivery_records WHERE negotiation_id=?",
                    (negotiation_id,),
                ).fetchone()
                return dict(row) if row else None

        return await asyncio.to_thread(load)

    async def update_vm_delivery(self, *, negotiation_id: str, **fields: Any) -> None:
        allowed = {
            "status",
            "fulfillment_uid",
            "provisioning_job_id",
            "connection_details",
            "tenant_credentials",
            "reason",
            "capacity_reservation_id",
            "settlement_resource_id",
            "fulfillment_id",
            "fulfillment_context",
            "fulfillment_phase",
        }
        if fields.keys() - allowed:
            raise TypeError(
                "unknown VM delivery fields: " + ", ".join(fields.keys() - allowed)
            )
        fields = {key: value for key, value in fields.items() if value is not None}
        if not fields:
            return

        def update():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("BEGIN IMMEDIATE")
                current = conn.execute(
                    "SELECT * FROM vm_delivery_records WHERE negotiation_id=?",
                    (negotiation_id,),
                ).fetchone()
                if current is None:
                    raise ValueError("VM delivery checkpoint is not initialized")
                for key in (
                    "fulfillment_id",
                    "fulfillment_uid",
                    "fulfillment_context",
                    "capacity_reservation_id",
                    "settlement_resource_id",
                ):
                    if (
                        key in fields
                        and current[key] is not None
                        and current[key] != fields[key]
                    ):
                        raise ValueError(
                            f"VM delivery {key} cannot change after binding"
                        )
                if (
                    current["status"] in ("ready", "failed", "refunded")
                    and fields.get("status", current["status"]) != current["status"]
                ):
                    raise ValueError("terminal VM delivery cannot restart")
                conn.execute(
                    "UPDATE vm_delivery_records SET "
                    + ", ".join(key + "=?" for key in fields)
                    + ", updated_at=? WHERE negotiation_id=?",
                    (*fields.values(), _now(), negotiation_id),
                )

        await asyncio.to_thread(update)

    async def list_incomplete_vm_deliveries(
        self, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        def load():
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                return [
                    dict(row)
                    for row in conn.execute(
                        "SELECT * FROM vm_delivery_records WHERE status NOT IN ('ready', 'failed', 'refunded') ORDER BY updated_at LIMIT ?",
                        (limit,),
                    ).fetchall()
                ]

        return await asyncio.to_thread(load)

    async def claim_vm_delivery(
        self, *, negotiation_id: str, owner: str, lease_until: str
    ) -> bool:
        expiry = datetime.fromisoformat(lease_until.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            raise ValueError("delivery convergence claim requires UTC expiry")

        def claim():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute(
                    """UPDATE vm_delivery_records SET processing_owner=?, processing_lease_until=?, updated_at=?
                    WHERE negotiation_id=? AND status NOT IN ('ready', 'failed', 'refunded')
                    AND (processing_lease_until IS NULL OR processing_lease_until < ? OR processing_owner=?)""",
                    (
                        owner,
                        expiry.astimezone(timezone.utc).isoformat(),
                        _now(),
                        negotiation_id,
                        _now(),
                        owner,
                    ),
                )
                return cursor.rowcount == 1

        return await asyncio.to_thread(claim)

    async def release_vm_delivery(self, *, negotiation_id: str, owner: str) -> None:
        def release():
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE vm_delivery_records SET processing_owner=NULL, processing_lease_until=NULL, updated_at=? WHERE negotiation_id=? AND processing_owner=?",
                    (_now(), negotiation_id, owner),
                )

        await asyncio.to_thread(release)

    async def load_vm_settlement_job(self, *, reference: str) -> dict[str, Any] | None:
        row = await self.load_vm_delivery(negotiation_id=reference)
        if row is not None:
            return {**row, "escrow_uid": reference}
        escrow = await self.load_escrow(escrow_uid=reference)
        if escrow is None:
            # A deal refunded before any delivery has no delivery record; its
            # settlement evidence is the only state to report.
            evidence = await self.load_vm_settlement_evidence(negotiation_id=reference)
            if evidence is None or evidence.status not in ("refunding", "refunded"):
                return None
            return {
                "negotiation_id": reference,
                "escrow_uid": reference,
                "status": evidence.status,
            }
        delivery = await self.load_vm_delivery(negotiation_id=escrow["negotiation_id"])
        return {**escrow, **delivery} if delivery is not None else escrow
