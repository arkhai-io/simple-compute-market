"""Negotiation-scoped payment evidence, independent of escrow obligations."""

from __future__ import annotations

import asyncio
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
                receipt = value.pop("receipt_json")
                value["receipt"] = json.loads(receipt) if receipt else None
                return value

        return await asyncio.to_thread(load)

    async def verify_vm_payment_record(
        self,
        *,
        negotiation_id: str,
        agreement_sha256: str,
        transaction_id: str,
        receipt: dict[str, Any],
    ) -> None:
        receipt_json = json.dumps(
            receipt, sort_keys=True, separators=(",", ":"), allow_nan=False
        )

        def save() -> None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    "INSERT OR IGNORE INTO vm_payment_records "
                    "(negotiation_id, agreement_sha256, transaction_id, receipt_json) "
                    "VALUES (?, ?, ?, ?)",
                    (negotiation_id, agreement_sha256, transaction_id, receipt_json),
                )
                conn.execute(
                    "UPDATE vm_payment_records SET transaction_id=?, receipt_json=? "
                    "WHERE negotiation_id=? AND agreement_sha256=? "
                    "AND (transaction_id IS NULL OR transaction_id=?) "
                    "AND (receipt_json IS NULL OR receipt_json=?)",
                    (
                        transaction_id,
                        receipt_json,
                        negotiation_id,
                        agreement_sha256,
                        transaction_id,
                        receipt_json,
                    ),
                )
                row = conn.execute(
                    "SELECT agreement_sha256, transaction_id, receipt_json "
                    "FROM vm_payment_records WHERE negotiation_id=?",
                    (negotiation_id,),
                ).fetchone()
                if row != (agreement_sha256, transaction_id, receipt_json):
                    raise ValueError(
                        "payment receipt conflicts with accepted Agreement"
                    )

        await asyncio.to_thread(save)
