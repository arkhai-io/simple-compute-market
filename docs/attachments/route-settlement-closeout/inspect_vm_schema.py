"""Inspect disposable VM settlement tables and malformed-evidence acceptance."""

import asyncio
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from market_core import SettlementEvidence
from market_storefront.payment_repository import (
    VmSettlementRepository,
    add_vm_settlement_records,
)


async def main():
    with TemporaryDirectory(prefix="closeout-vm-schema-") as directory:
        path = Path(directory) / "db.sqlite"
        with sqlite3.connect(path) as conn:
            add_vm_settlement_records(conn)
            add_vm_settlement_records(conn)
            for table in ("vm_settlement_evidence", "vm_delivery_records"):
                print(table, [row[1] for row in conn.execute(f"PRAGMA table_info({table})")])
                print(conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0])
        repository = VmSettlementRepository()
        repository.db_path = str(path)
        evidence = SettlementEvidence(
            "diagnostic-neg", "arkhai.payments.v1", "diagnostic-ref", "verified",
            {"schema": "vm.settlement-evidence.v1", "agreement_sha256": "diagnostic-digest",
             "delivery": {"kind": "not-a-vm-payload", "schema_version": 999}},
        )
        try:
            await repository.save_vm_settlement_evidence(evidence)
            loaded = await repository.load_vm_settlement_evidence(negotiation_id="diagnostic-neg")
            print("unsupported_delivery_persisted=", loaded.evidence["delivery"])
        except Exception as error:
            print("rejected=", type(error).__name__, str(error))
    print("temporary_database_removed=", not path.exists())


if __name__ == "__main__":
    asyncio.run(main())
