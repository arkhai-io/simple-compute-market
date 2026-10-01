"""Negotiation-scoped payment evidence, independent of escrow obligations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from typing import Any


def add_vm_payment_records(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE vm_payment_records (
            negotiation_id TEXT PRIMARY KEY,
            agreement_sha256 TEXT NOT NULL,
            mandate_json TEXT NOT NULL,
            transaction_id TEXT UNIQUE,
            receipt_json TEXT
        )
    """)


class VmPaymentRepository:
    db_path: str

    async def save_vm_payment_acceptance(
        self, *, negotiation_id: str, agreement_bytes: bytes, mandate: dict[str, Any]
    ) -> None:
        digest = hashlib.sha256(agreement_bytes).hexdigest()
        payload = json.dumps(
            mandate, sort_keys=True, separators=(",", ":"), allow_nan=False
        )

        def save() -> None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT OR IGNORE INTO vm_payment_records "
                    "(negotiation_id, agreement_sha256, mandate_json) VALUES (?, ?, ?)",
                    (negotiation_id, digest, payload),
                )
                row = conn.execute(
                    "SELECT agreement_sha256, mandate_json FROM vm_payment_records "
                    "WHERE negotiation_id=?",
                    (negotiation_id,),
                ).fetchone()
                if row != (digest, payload):
                    raise ValueError(
                        "payment mandate conflicts with accepted Agreement"
                    )

        await asyncio.to_thread(save)

    async def load_vm_payment_record(
        self, *, negotiation_id: str
    ) -> dict[str, Any] | None:
        def load() -> dict[str, Any] | None:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM vm_payment_records WHERE negotiation_id=?",
                    (negotiation_id,),
                ).fetchone()
                if row is None:
                    return None
                value = dict(row)
                value["mandate"] = json.loads(value.pop("mandate_json"))
                receipt = value.pop("receipt_json")
                value["receipt"] = json.loads(receipt) if receipt else None
                return value

        return await asyncio.to_thread(load)

    async def verify_vm_payment_record(
        self,
        *,
        negotiation_id: str,
        agreement_sha256: str,
        mandate: dict[str, Any],
        transaction_id: str,
        receipt: dict[str, Any],
    ) -> None:
        mandate_json = json.dumps(
            mandate, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        receipt_json = json.dumps(
            receipt, sort_keys=True, separators=(",", ":"), allow_nan=False
        )

        def save() -> None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                changed = conn.execute(
                    "UPDATE vm_payment_records SET transaction_id=?, receipt_json=? "
                    "WHERE negotiation_id=? AND agreement_sha256=? AND mandate_json=? "
                    "AND (transaction_id IS NULL OR transaction_id=?) "
                    "AND (receipt_json IS NULL OR receipt_json=?)",
                    (
                        transaction_id,
                        receipt_json,
                        negotiation_id,
                        agreement_sha256,
                        mandate_json,
                        transaction_id,
                        receipt_json,
                    ),
                )
                if changed.rowcount != 1:
                    raise ValueError(
                        "payment receipt conflicts with accepted Agreement"
                    )

        await asyncio.to_thread(save)
