"""Escrow persistence: capacity_reservation_id/settlement_resource_id/fulfillment_id.

These three columns were added to the shared ``escrows`` table so a caller
can resume checking a VM fulfillment's durable progress by escrow after a
storefront restart, without redispatching. Distinct from the pre-existing
``fulfillment_uid`` column (the on-chain settlement-claim identity) --
covers that both may be set independently on the same row.
"""

from __future__ import annotations

import pytest

from core_storefront.sqlite_client import SQLiteClient


@pytest.fixture
def client(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "escrow-test.db"))


async def _seed_escrow(client: SQLiteClient, escrow_uid: str) -> None:
    import sqlite3
    from datetime import datetime

    conn = sqlite3.connect(client.db_path)
    try:
        now = datetime.now().isoformat()
        conn.execute(
            """
            INSERT INTO escrows (escrow_uid, negotiation_id, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (escrow_uid, "neg-1", "pending", now, now),
        )
        conn.commit()
    finally:
        conn.close()


class TestEscrowFulfillmentIdentityPersistence:
    async def test_new_columns_default_to_none(self, client: SQLiteClient):
        await _seed_escrow(client, "escrow-1")
        row = await client.load_escrow(escrow_uid="escrow-1")
        assert row["capacity_reservation_id"] is None
        assert row["settlement_resource_id"] is None
        assert row["fulfillment_id"] is None

    async def test_update_escrow_persists_all_three_fields(self, client: SQLiteClient):
        await _seed_escrow(client, "escrow-2")
        await client.update_escrow(
            escrow_uid="escrow-2",
            capacity_reservation_id="res-1",
            settlement_resource_id="kvm1",
            fulfillment_id="fulfillment-1",
        )
        row = await client.load_escrow(escrow_uid="escrow-2")
        assert row["capacity_reservation_id"] == "res-1"
        assert row["settlement_resource_id"] == "kvm1"
        assert row["fulfillment_id"] == "fulfillment-1"

    async def test_partial_update_leaves_other_fields_untouched(self, client: SQLiteClient):
        await _seed_escrow(client, "escrow-3")
        await client.update_escrow(
            escrow_uid="escrow-3",
            capacity_reservation_id="res-1",
            settlement_resource_id="kvm1",
        )
        # Later call only knows fulfillment_id -- must not clobber the two
        # already-written fields (None means "don't touch", per this
        # method's own contract).
        await client.update_escrow(escrow_uid="escrow-3", fulfillment_id="fulfillment-1")

        row = await client.load_escrow(escrow_uid="escrow-3")
        assert row["capacity_reservation_id"] == "res-1"
        assert row["settlement_resource_id"] == "kvm1"
        assert row["fulfillment_id"] == "fulfillment-1"

    async def test_fulfillment_id_and_fulfillment_uid_coexist_independently(
        self, client: SQLiteClient,
    ):
        """fulfillment_id (physical-provisioning aggregate identity) and
        fulfillment_uid (on-chain settlement-claim identity) are different
        concepts that may both legitimately be set on the same row."""
        await _seed_escrow(client, "escrow-4")
        await client.update_escrow(escrow_uid="escrow-4", fulfillment_uid="0xonchain...")
        await client.update_escrow(escrow_uid="escrow-4", fulfillment_id="fulfillment-1")

        row = await client.load_escrow(escrow_uid="escrow-4")
        assert row["fulfillment_uid"] == "0xonchain..."
        assert row["fulfillment_id"] == "fulfillment-1"
        assert row["fulfillment_uid"] != row["fulfillment_id"]
