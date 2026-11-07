"""Inspect installed bare-metal role contracts and a disposable evidence schema."""

from __future__ import annotations

import argparse
import importlib
from importlib import metadata
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory

from arkhai_bare_metal.domain_runtime import market_domain
from market_core import (
    DomainCapability,
    DomainCodecExample,
    DomainConformanceCase,
    assert_domain_conformance,
    validate_domain_contract,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("role", choices=("buyer", "seller"))
    role = parser.parse_args().role
    if role == "buyer":
        module = importlib.import_module("arkhai_bare_metal_buyer.plugin")
        contract = module.domain
        distribution = "arkhai-bare-metal-buyer"
        entries = metadata.entry_points(group="market.buyer_domains")
        assert (
            next(entry for entry in entries if entry.name == "bare-metal").load()
            is contract
        )
        capabilities = frozenset(
            {
                DomainCapability.PUBLICATION,
                DomainCapability.BUYER,
                DomainCapability.SETTLEMENT,
            }
        )
        assert set(contract.settlement.buyer_stages) == {"arkhai.payments.v1"}
    else:
        module = importlib.import_module("arkhai_bare_metal_storefront.domain_runtime")
        contract = module.get_market_domain_contract()
        distribution = "arkhai-bare-metal-storefront"
        entries = metadata.entry_points(group="market.storefront_contributions")
        next(entry for entry in entries if entry.name == "bare_metal").load()
        capabilities = frozenset(
            {
                DomainCapability.PUBLICATION,
                DomainCapability.STOREFRONT,
                DomainCapability.SETTLEMENT,
                DomainCapability.FULFILLMENT,
            }
        )
        assert set(contract.settlement.seller_stages) == {
            "alkahest.v1",
            "arkhai.payments.v1",
            "contact-exchange.v1",
        }
    assert "site-packages" in module.__file__, module.__file__
    assert validate_domain_contract(contract) is contract
    base = market_domain()
    examples = {
        "listing": {"machine_id": "node-1", "physical_host_id": "host-1"},
        "message": {
            "duration_seconds": 3600,
            "ssh_public_key": "ssh-ed25519 diagnostic",
        },
        "terms": {
            "machine_id": "node-1",
            "physical_host_id": "host-1",
            "duration_seconds": 3600,
            "ssh_public_key": "ssh-ed25519 diagnostic",
        },
        "materialization": {
            "escrow_uid": "opaque-reference",
            "machine_id": "node-1",
            "physical_host_id": "host-1",
            "lease_end_utc": "2030-01-01T01:00:00Z",
            "ssh_public_key": "ssh-ed25519 diagnostic",
        },
        "receipt": {
            "machine_id": "node-1",
            "physical_host_id": "host-1",
            "status": "active",
        },
        "result": {"action": "node_grant_access", "machine_id": "node-1"},
    }
    assert_domain_conformance(
        DomainConformanceCase(
            contract=contract,
            capabilities=capabilities,
            **{
                name: DomainCodecExample(value, getattr(base.codecs, name)(value))
                for name, value in examples.items()
            },
        )
    )
    print(
        f"{distribution} {metadata.version(distribution)}: installed plugin and six codecs conform"
    )
    print(
        "declared stages:",
        ", ".join(
            contract.settlement.buyer_stages or contract.settlement.seller_stages
        ),
    )
    if role == "seller":
        sqlite = importlib.import_module("arkhai_bare_metal_storefront.sqlite_client")
        with TemporaryDirectory(prefix="baremetal-evidence-") as directory:
            path = Path(directory) / "storefront.db"
            sqlite.SQLiteClient(str(path), domain=contract)
            sqlite.SQLiteClient(str(path), domain=contract)
            with sqlite3.connect(path) as conn:
                columns = [
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(bare_metal_settlement_records)"
                    )
                ]
                assert columns == [
                    "negotiation_id",
                    "mechanism",
                    "agreement_sha256",
                    "settlement_ref",
                    "status",
                    "evidence_json",
                    "created_at",
                    "updated_at",
                ]
                print("fresh evidence columns:", ", ".join(columns))
                print(
                    conn.execute(
                        "SELECT sql FROM sqlite_master WHERE name='bare_metal_settlement_records'"
                    ).fetchone()[0]
                )
                lifecycle_columns = [
                    row[1]
                    for row in conn.execute(
                        "PRAGMA table_info(bare_metal_fulfillment_lifecycle)"
                    )
                ]
                assert "settlement_ref" in lifecycle_columns
                assert "escrow_uid" not in lifecycle_columns
                print("fresh lifecycle columns:", ", ".join(lifecycle_columns))
                print(
                    conn.execute(
                        "SELECT sql FROM sqlite_master WHERE name='bare_metal_fulfillment_lifecycle'"
                    ).fetchone()[0]
                )
                conn.execute(
                    "ALTER TABLE bare_metal_fulfillment_lifecycle RENAME COLUMN settlement_ref TO escrow_uid"
                )
            try:
                sqlite.SQLiteClient(str(path), domain=contract)
            except RuntimeError as exc:
                assert "explicit database reset" in str(exc)
                print("lifecycle schema drift refused:", exc)
            else:
                raise AssertionError("old lifecycle schema was silently accepted")
            with sqlite3.connect(path) as conn:
                conn.execute(
                    "ALTER TABLE bare_metal_fulfillment_lifecycle RENAME COLUMN escrow_uid TO settlement_ref"
                )
                conn.execute(
                    "ALTER TABLE bare_metal_settlement_records RENAME COLUMN evidence_json TO receipt_json"
                )
            try:
                sqlite.SQLiteClient(str(path), domain=contract)
            except RuntimeError as exc:
                assert "explicit database reset" in str(exc)
                print("schema drift refused:", exc)
            else:
                raise AssertionError("old evidence schema was silently accepted")
        print("temporary schema removed")


if __name__ == "__main__":
    main()
