"""VM settlement evidence and independent negotiation-scoped delivery state."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from market_core import SettlementEvidence


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
            status TEXT NOT NULL,
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
        payload = dict(evidence.evidence)
        if payload.get("schema") != "vm.settlement-evidence.v1" or not payload.get(
            "agreement_sha256"
        ):
            raise ValueError(
                "VM evidence requires versioned accepted Agreement identity"
            )
        digest = payload["agreement_sha256"]
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
                            current[3] == "verified"
                            and (current[3] != evidence.status or current[4] != wire)
                        )
                    ):
                        raise ValueError(
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
            return None
        delivery = await self.load_vm_delivery(negotiation_id=escrow["negotiation_id"])
        return {**escrow, **delivery} if delivery is not None else escrow

    def vm_delivery_repository(self, negotiation_id: str):
        return VmDeliveryRepository(self, negotiation_id)


class VmDeliveryRepository:
    """Bind legacy delivery helper coordinates to a negotiation, never an escrow row.

    The public escrow coordinate remains a projection while delivery helpers use
    this scoped repository. Genuine escrow/obligation servicing uses the owner.
    """

    def __init__(self, owner: Any, negotiation_id: str):
        self.owner = owner
        self.negotiation_id = negotiation_id

    def __getattr__(self, name: str):
        return getattr(self.owner, name)

    async def load_escrow(self, *, escrow_uid: str):
        row = await self.owner.load_vm_delivery(negotiation_id=self.negotiation_id)
        if row is None:
            return None
        evidence = await self.owner.load_vm_settlement_evidence(
            negotiation_id=self.negotiation_id
        )
        if evidence is None or escrow_uid != evidence.settlement_ref:
            raise ValueError("delivery coordinate disagrees with settlement evidence")
        source = evidence.evidence.get("source") or {}
        return {
            **row,
            "escrow_uid": evidence.settlement_ref,
            "is_primary": True,
            "chain_name": source.get("chain_name"),
            "escrow_address": source.get("escrow_address"),
            "obligation_ref": source.get("obligation_ref"),
        }

    async def update_escrow(self, *, escrow_uid: str, **fields: Any):
        await self.load_escrow(escrow_uid=escrow_uid)
        if fields.get("fulfillment_context") is not None:
            binding = await self.owner.load_thread_binding(
                negotiation_id=self.negotiation_id
            )
            fields["fulfillment_context"] = _json(
                self.owner.bind_fulfillment_context(
                    json.loads(fields["fulfillment_context"]),
                    thread_binding=binding,
                )
            )
        await self.owner.update_vm_delivery(
            negotiation_id=self.negotiation_id, **fields
        )

    async def claim_escrow_convergence(
        self, *, escrow_uid: str, owner: str, lease_until: str
    ):
        await self.load_escrow(escrow_uid=escrow_uid)
        return await self.owner.claim_vm_delivery(
            negotiation_id=self.negotiation_id, owner=owner, lease_until=lease_until
        )

    async def release_escrow_convergence(self, *, escrow_uid: str, owner: str):
        await self.owner.release_vm_delivery(
            negotiation_id=self.negotiation_id, owner=owner
        )
