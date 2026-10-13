"""Storefront schema across bootstrap, restart, and legacy migrations.

A fresh database carries no retired inventory schema; a restart preserves the
schema and every persisted identifier; and the legacy derived-listing backfill
never reads a retired table, whether or not one exists.
"""

from __future__ import annotations

import sqlite3
import asyncio
import json
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from market_core import SettlementEvidence
import pytest

from core_storefront.domain_registry import (
    StorefrontListingBinding,
    StorefrontThreadBinding,
    build_storefront_derivation_key,
)
from market_identity import Ed25519Signer

from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.utils import sqlite_client as sqlite_module

from tests.fulfillment_fixtures import vm_delivery_evidence

from market_storefront.utils.migrations import (
    _migrate_derived_compute_listing_pool_ids,
)


_RETIRED_INVENTORY_MIGRATIONS = (
    "20260604_002_compute_inventory_pools",
    "20260611_006_pool_member_sites",
    "20260716_008_rename_compute_capacity_pools",
    "20260813_010_resource_settlement_clauses",
)


def test_fresh_bootstrap_creates_no_inventory_schema_and_records_no_retired_migration(
    tmp_path,
):
    db_path = str(tmp_path / "fresh.db")
    registry = build_vm_storefront_registry(build_vm_storefront_domain())

    SQLiteClient(db_path, registry=registry)
    SQLiteClient(db_path, registry=registry)

    with sqlite3.connect(db_path) as conn:
        names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")
        }
        recorded = {row[0] for row in conn.execute("SELECT id FROM schema_migrations")}
    assert not names & {
        "resources",
        "hosts",
        "resource_transition_events",
        "compute_capacity_pools",
        "compute_pool_members",
        "trg_resources_updated_at",
        "trg_hosts_updated_at",
        "idx_compute_pool_members_pool",
    }
    assert not {name for name in names if name.startswith(("idx_resources_", "idx_resource_transition"))}
    assert not recorded & set(_RETIRED_INVENTORY_MIGRATIONS)
    assert "20260604_003_derived_compute_listing_pool_ids" in recorded


def _derived_listings(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE derived_compute_listings (listing_id TEXT PRIMARY KEY, resource_id TEXT)"
    )
    conn.executemany(
        "INSERT INTO derived_compute_listings VALUES (?, ?)",
        [("listing-member", "res-member"), ("listing-alone", "res-alone")],
    )


@pytest.mark.parametrize("retained_members", [True, False])
def test_derived_listing_pool_ids_take_the_listings_own_resource(tmp_path, retained_members):
    """A retained membership table is frozen data the backfill never reads."""
    with sqlite3.connect(tmp_path / "legacy.db") as conn:
        _derived_listings(conn)
        if retained_members:
            conn.execute("CREATE TABLE compute_pool_members (resource_id TEXT, pool_id TEXT)")
            conn.execute("INSERT INTO compute_pool_members VALUES ('res-member', 'pool-1')")

        _migrate_derived_compute_listing_pool_ids(conn)

        assert dict(conn.execute("SELECT listing_id, pool_id FROM derived_compute_listings")) == {
            "listing-member": "res-member",
            "listing-alone": "res-alone",
        }
        if retained_members:
            assert conn.execute("SELECT * FROM compute_pool_members").fetchall() == [
                ("res-member", "pool-1")
            ]


def test_restart_preserves_schema_and_all_persisted_identifiers(tmp_path) -> None:
    db_path = str(tmp_path / "pre-parameterization.db")
    domain = build_vm_storefront_domain()
    registry = build_vm_storefront_registry(domain)
    registration = registry.resolve_mode("vm")
    assert registry.resolve(registration.binding) is domain
    seller = Ed25519Signer(b"\x31" * 32).identity
    buyer = Ed25519Signer(b"\x32" * 32).identity
    client = SQLiteClient(db_path, registry=registry)
    now = datetime.now().isoformat()
    source = {
        "kind": "compute.listing_source",
        "schema_version": 1,
        "payload": {
            "site_id": "site-stable",
            "resource_id": "resource-stable",
            "gpu_count": 1,
        },
    }
    listing_binding = StorefrontListingBinding.from_source_envelope(
        listing_id="listing-stable",
        site_id="site-stable",
        binding=registration.binding,
        derivation_key=build_storefront_derivation_key(
            site_id="site-stable",
            offering_mode=registration.binding.offering_mode,
            binding=registration.binding,
            source_identity=source,
        ),
        source_envelope=source,
        last_reconciled_at=now,
        capacity_backing="backed",
        physical_resource_id="resource-stable",
    )

    asyncio.run(
        client.upsert_listing_with_binding(
            binding=listing_binding,
            status="open",
            created_at=now,
            updated_at=now,
            listing_resource={
                "offering_mode": "vm",
                "resource_type": "compute",
                "resource_id": "resource-stable",
                "gpu_model": "H200",
                "gpu_count": 1,
                "region": "test",
                "sla": 99.0,
            },
            fulfillment_resource=None,
            max_duration_seconds=3600,
            storefront_url="http://seller.test",
            seller_principal=seller,
        )
    )
    thread_binding = StorefrontThreadBinding(
        negotiation_id="negotiation-stable",
        listing_id=listing_binding.listing_id,
        site_id=listing_binding.site_id,
        binding=registration.binding,
    )
    asyncio.run(
        client.create_negotiation_thread(
            negotiation_id="negotiation-stable",
            our_listing_id="listing-stable",
            their_listing_id="",
            our_agent_id="http://seller.test",
            their_agent_id="http://buyer.test",
            buyer_principal=buyer,
            seller_principal=seller,
            owner_id="seller",
            binding=thread_binding,
        )
    )
    asyncio.run(
        client.insert_escrow(
            escrow_uid="settlement-stable",
            negotiation_id="negotiation-stable",
            chain_name="anvil",
            escrow_address="0x" + "11" * 20,
        )
    )
    asyncio.run(
        client.bind_escrow_obligation(
            escrow_uid="settlement-stable",
            obligation_ref="obligation-stable",
            obligation_index=0,
        )
    )
    asyncio.run(
        client.update_escrow(
            escrow_uid="settlement-stable",
            fulfillment_uid="fulfillment-stable",
        )
    )

    principal = json.dumps(seller.model_dump(mode="json"), sort_keys=True)
    obligation = json.dumps({"mechanism": "alkahest.v1"}, sort_keys=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """
            INSERT INTO settlement_obligations (
              obligation_ref, agreement_ref, obligation_index, obligation_hash,
              obligation, payer_principal, claimant_principal, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "operation-obligation-stable",
                "negotiation-stable",
                1,
                "sha256:stable",
                obligation,
                principal,
                principal,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO settlement_operations (
              obligation_ref, operation, request_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (
                "operation-obligation-stable",
                "collect",
                "sha256:operation-stable",
                now,
                now,
            ),
        )
        conn.commit()
        schema_before = conn.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()

    reopened = SQLiteClient(db_path, registry=registry)

    assert reopened.domain_registry is registry
    assert reopened.domain_registry.resolve(registration.binding) is domain
    assert asyncio.run(
        reopened.load_listing(listing_id="listing-stable")
    )["listing_id"] == "listing-stable"
    persisted_thread = asyncio.run(
        reopened.load_negotiation_thread_row(
            negotiation_id="negotiation-stable"
        )
    )
    assert persisted_thread["negotiation_id"] == "negotiation-stable"
    assert asyncio.run(
        reopened.load_listing_binding(listing_id="listing-stable")
    ) == listing_binding
    assert asyncio.run(
        reopened.load_thread_binding(negotiation_id="negotiation-stable")
    ) == thread_binding
    assert asyncio.run(reopened.list_storefront_domain_bindings()) == (
        registration.binding,
    )
    escrow = asyncio.run(reopened.load_escrow(escrow_uid="settlement-stable"))
    assert escrow["obligation_ref"] == "obligation-stable"
    assert escrow["fulfillment_uid"] == "fulfillment-stable"

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT obligation_ref, operation FROM settlement_operations"
        ).fetchall() == [("operation-obligation-stable", "collect")]
        schema_after = conn.execute(
            "SELECT name, type, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
    assert schema_after == schema_before


def test_settings_singleton_rejects_a_different_registry_owner(
    tmp_path,
    monkeypatch,
) -> None:
    domain = build_vm_storefront_domain()
    first_registry = build_vm_storefront_registry(domain)
    second_registry = build_vm_storefront_registry(domain)
    assert first_registry is not second_registry
    assert second_registry.resolve_mode("vm").contract is domain
    signer = Ed25519Signer(b"\x33" * 32)
    monkeypatch.setattr(
        sqlite_module.settings,
        "db_path",
        str(tmp_path / "singleton.db"),
        raising=False,
    )
    monkeypatch.setattr(sqlite_module, "resolve_marketplace_signer", lambda: signer)
    monkeypatch.setattr(sqlite_module, "_sqlite_client", None)

    resolved = sqlite_module.get_sqlite_client(registry=first_registry)

    assert resolved.domain_registry is first_registry
    assert resolved.domain_registry.resolve_mode("vm").contract is domain
    with pytest.raises(
        RuntimeError,
        match="different storefront domain registry object",
    ):
        sqlite_module.get_sqlite_client(registry=second_registry)


@pytest.mark.asyncio
async def test_evidence_and_delivery_bindings_survive_restart_without_payment_escrows(tmp_path):
    registry = build_vm_storefront_registry(build_vm_storefront_domain())
    path = str(tmp_path / "evidence.db")
    db = SQLiteClient(path, registry=registry)
    pending = SettlementEvidence(
        negotiation_id="payment-1", mechanism="arkhai.payments.v1", settlement_ref="transaction-1",
        status="pending", evidence={"schema": "vm.settlement-evidence.v1", "agreement_sha256": "1" * 64},
    )
    await db.save_vm_settlement_evidence(pending)
    with pytest.raises(ValueError, match="requires verified"):
        await db.insert_vm_delivery(negotiation_id="payment-1")
    verified = replace(
        vm_delivery_evidence(negotiation_id="payment-1", settlement_ref="transaction-1"),
        mechanism=pending.mechanism,
    )
    await db.save_vm_settlement_evidence(verified)
    assert await db.insert_vm_delivery(negotiation_id="payment-1")
    await db.update_vm_delivery(negotiation_id="payment-1", fulfillment_id="physical-1")
    db = SQLiteClient(path, registry=registry)
    await db.save_vm_settlement_evidence(verified)
    assert not await db.insert_vm_delivery(negotiation_id="payment-1")
    assert (await db.load_vm_delivery(negotiation_id="payment-1"))["fulfillment_id"] == "physical-1"
    for changed in (replace(verified, mechanism="other.v1"), replace(verified, settlement_ref="other-transaction"),
                    replace(verified, evidence={**verified.evidence, "agreement_sha256": "2" * 64})):
        with pytest.raises(ValueError, match="conflicts"):
            await db.save_vm_settlement_evidence(changed)
    with pytest.raises(ValueError, match="cannot change"):
        await db.update_vm_delivery(negotiation_id="payment-1", fulfillment_id="replacement")
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
    assert await db.claim_vm_delivery(negotiation_id="payment-1", owner="worker-a", lease_until=expiry)
    assert not await db.claim_vm_delivery(negotiation_id="payment-1", owner="worker-b", lease_until=expiry)
    await db.release_vm_delivery(negotiation_id="payment-1", owner="worker-b")
    assert not await db.claim_vm_delivery(negotiation_id="payment-1", owner="worker-b", lease_until=expiry)
    await db.release_vm_delivery(negotiation_id="payment-1", owner="worker-a")
    assert await db.claim_vm_delivery(negotiation_id="payment-1", owner="worker-b", lease_until=expiry)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM escrows").fetchone()[0] == 0
