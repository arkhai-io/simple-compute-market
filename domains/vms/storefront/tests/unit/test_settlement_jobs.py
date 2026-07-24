"""Unit tests for the polling-mode settlement flow.

Covers:
- escrows table round-trip through SQLiteClient helpers.
- start_settlement_job: refuses missing thread, non-terminal thread,
  no-agreed-price thread, missing seller order.
- Idempotence: second start on the same escrow_uid returns existing row.
- Durable workflow intent is created idempotently before reconciliation.
- Response serializer omits None fields and parses tenant_credentials JSON.
"""

from __future__ import annotations

import json
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from arkhai_vms import make_vm_provision_terms

from market_storefront.utils.sqlite_client import SQLiteClient
from market_storefront.utils.settlement_jobs import (
    serialize_settlement_job,
    start_settlement_job,
)


# ---------------------------------------------------------------------------
# SQLiteClient escrows helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "agent.db"))


@pytest.fixture(autouse=True)
def _anvil_chain(monkeypatch):
    """Inject a synthetic [chains.anvil] entry so start_settlement_job's
    ``CHAINS.get(chain_name)`` lookup resolves in tests that don't write a
    full storefront.toml."""
    from market_config.config_loader import ChainConfig
    from market_storefront.utils import config as agent_config

    monkeypatch.setattr(
        agent_config,
        "CHAINS",
        {
            "anvil": ChainConfig(
                name="anvil",
                rpc_url="http://localhost:8545",
                chain_id=31337,
                alkahest_address_config_path=None,
            ),
        },
        raising=False,
    )


@pytest.mark.asyncio
async def test_insert_escrow_happy_path(client):
    ok = await client.insert_escrow(
        escrow_uid="0xescrow-1",
        negotiation_id="neg-1",
        chain_name="anvil",
        escrow_address="0x" + "aa" * 20,
    )
    assert ok is True
    row = await client.load_escrow(escrow_uid="0xescrow-1")
    assert row is not None
    assert row["negotiation_id"] == "neg-1"
    assert row["status"] == "provisioning"
    assert row["chain_name"] == "anvil"
    assert row["escrow_address"] == "0x" + "aa" * 20
    assert row["is_primary"] is True
    assert row["fulfillment_uid"] is None


@pytest.mark.asyncio
async def test_insert_is_idempotent_by_primary_key(client):
    assert await client.insert_escrow(
        escrow_uid="0xescrow-1",
        negotiation_id="neg-1",
        chain_name="anvil",
        escrow_address="0x" + "aa" * 20,
    ) is True
    # Second insert for same escrow returns False, doesn't overwrite.
    assert await client.insert_escrow(
        escrow_uid="0xescrow-1",
        negotiation_id="neg-DIFFERENT",
        chain_name="other",
        escrow_address="0x" + "bb" * 20,
    ) is False
    row = await client.load_escrow(escrow_uid="0xescrow-1")
    assert row["negotiation_id"] == "neg-1"
    assert row["chain_name"] == "anvil"


@pytest.mark.asyncio
async def test_update_escrow_patches_only_provided_fields(client):
    await client.insert_escrow(
        escrow_uid="0xescrow-1", negotiation_id="neg-1",
        chain_name="anvil", escrow_address="0x" + "aa" * 20,
    )
    await client.update_escrow(
        escrow_uid="0xescrow-1",
        status="ready",
        fulfillment_uid="0xfulfill",
        connection_details="ssh alice@vm1",
    )
    row = await client.load_escrow(escrow_uid="0xescrow-1")
    assert row["status"] == "ready"
    assert row["fulfillment_uid"] == "0xfulfill"
    assert row["connection_details"] == "ssh alice@vm1"
    # reason left untouched
    assert row["reason"] is None


@pytest.mark.asyncio
async def test_load_missing_escrow_returns_none(client):
    assert await client.load_escrow(escrow_uid="0xnope") is None


@pytest.mark.asyncio
async def test_load_primary_escrow_for_negotiation(client):
    await client.insert_escrow(
        escrow_uid="0xprimary", negotiation_id="neg-1",
        chain_name="anvil", escrow_address="0x" + "aa" * 20,
        is_primary=True,
    )
    await client.insert_escrow(
        escrow_uid="0xbond", negotiation_id="neg-1",
        chain_name="anvil", escrow_address="0x" + "bb" * 20,
        is_primary=False,
    )
    primary = await client.load_primary_escrow_for_negotiation(negotiation_id="neg-1")
    assert primary is not None
    assert primary["escrow_uid"] == "0xprimary"
    assert primary["is_primary"] is True


# ---------------------------------------------------------------------------
# start_settlement_job — validation + idempotence
# ---------------------------------------------------------------------------


async def _seed_negotiation(
    client: SQLiteClient,
    *,
    neg_id: str = "neg-1",
    our_listing_id: str = "seller-ord-1",
    terminal: str | None = "success",
    agreed_price: float | None = 10**18,
    agreed_duration_seconds: int | None = 3600,
) -> None:
    conn = sqlite3.connect(client.db_path)
    try:
        conn.execute(
            """INSERT OR REPLACE INTO negotiation_threads
               (negotiation_id, our_listing_id, their_listing_id,
                our_agent_id, their_agent_id, status,
                created_at, updated_at, terminal_state,
                agreed_price, agreed_duration_seconds, agreed_at)
               VALUES (?, ?, 'buyer-ord-1',
                       'http://seller:8001', 'http://buyer:8000', 'active',
                       '2026-04-23T00:00:00Z', '2026-04-23T00:00:00Z', ?,
                       ?, ?, ?)""",
            (
                neg_id, our_listing_id, terminal,
                agreed_price, agreed_duration_seconds,
                "2026-04-23T00:00:00Z" if agreed_price is not None else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    await client.save_capacity_hold(
        negotiation_id=neg_id,
        listing_id=our_listing_id,
        capacity_reservation_id=f"reservation-{neg_id}",
        site_id="default",
        payload={"capacity_reservation_id": f"reservation-{neg_id}", "site": "default"},
    )


async def _seed_seller_order(client: SQLiteClient, listing_id: str = "seller-ord-1") -> None:
    conn = sqlite3.connect(client.db_path)
    try:
        conn.execute(
            """INSERT INTO listings (listing_id, status, created_at, updated_at,
                                   offer_resource, max_duration_seconds,
                                   seller, accepted_escrows)
               VALUES (?, 'open', '2026-04-23T00:00:00Z', '2026-04-23T00:00:00Z',
                       '{"resource_type":"compute.gpu","gpu_model":"H200","pool_id":"default","gpu_count":1,"vcpu_count":2,"ram_gb":4,"disk_gb":40}', 3600, 'http://seller:8001',
                       '[{"chain_name": "anvil", "escrow_address": "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}]')""",
            (listing_id,),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_start_refuses_unknown_negotiation(client):
    await _seed_seller_order(client)
    with pytest.raises(ValueError, match="Unknown negotiation"):
        await start_settlement_job(
            escrow_uid="0xescrow",
            negotiation_id="nope",
            ssh_public_key="ssh-rsa ...",
            sqlite_client=client,
            alkahest_client=MagicMock(),
            chain_name='anvil',
        )


@pytest.mark.asyncio
async def test_start_refuses_non_terminal_thread(client):
    await _seed_seller_order(client)
    await _seed_negotiation(client, terminal=None, agreed_price=None)
    with pytest.raises(ValueError, match="not terminal-success"):
        await start_settlement_job(
            escrow_uid="0xescrow",
            negotiation_id="neg-1",
            ssh_public_key="ssh-rsa ...",
            sqlite_client=client,
            alkahest_client=MagicMock(),
            chain_name='anvil',
        )


@pytest.mark.asyncio
async def test_start_refuses_terminal_without_agreed_price(client):
    await _seed_seller_order(client)
    await _seed_negotiation(client, agreed_price=None)
    with pytest.raises(ValueError, match="no agreed_price"):
        await start_settlement_job(
            escrow_uid="0xescrow",
            negotiation_id="neg-1",
            ssh_public_key="ssh-rsa ...",
            sqlite_client=client,
            alkahest_client=MagicMock(),
            chain_name='anvil',
        )


@pytest.mark.asyncio
async def test_start_refuses_when_seller_order_gone(client):
    # No seller order seeded.
    await _seed_negotiation(client, our_listing_id="seller-gone")
    with pytest.raises(ValueError, match="is gone from the local DB"):
        await start_settlement_job(
            escrow_uid="0xescrow",
            negotiation_id="neg-1",
            ssh_public_key="ssh-rsa ...",
            sqlite_client=client,
            alkahest_client=MagicMock(),
            chain_name='anvil',
        )


@pytest.mark.asyncio
async def test_start_happy_path_inserts_row_and_kicks_off_task(client):
    await _seed_seller_order(client)
    await _seed_negotiation(client)

    # Prevent the immediate reconciliation optimization from doing remote work.
    # Bypass on-chain escrow verification — covered in test_escrow_verification.py.
    with patch(
        "market_storefront.services.fulfillment_reconciler.StorefrontFulfillmentReconciler.run_once",
        new=AsyncMock(),
    ), patch(
        "market_storefront.utils.escrow_verification.verify_escrow_for_settlement",
        new=AsyncMock(),
    ):
        result = await start_settlement_job(
            escrow_uid="0xescrow",
            negotiation_id="neg-1",
            ssh_public_key="ssh-rsa ...",
            sqlite_client=client,
            alkahest_client=MagicMock(),
            chain_name='anvil',
        )

    assert result["status"] == "provisioning"
    assert result["escrow_uid"] == "0xescrow"
    row = await client.load_escrow(escrow_uid="0xescrow")
    assert row is not None
    assert row["status"] == "provisioning"
    # chain_name / escrow_address pinned from the listing's accepted_escrows[0]
    # when the thread has no buyer_escrow_proposal.
    assert row["chain_name"] == "anvil"
    assert row["escrow_address"] == "0x" + "a" * 40
    assert row["is_primary"] is True


@pytest.mark.asyncio
async def test_start_aborts_when_escrow_verification_rejects(client):
    """If on-chain verification fails, no escrows row is inserted and no
    background task is scheduled — fail-closed."""
    from market_storefront.utils.escrow_verification import EscrowVerificationError

    await _seed_seller_order(client)
    await _seed_negotiation(client)

    verify_mock = AsyncMock(side_effect=EscrowVerificationError("amount insufficient"))
    with patch(
        "market_storefront.utils.escrow_verification.verify_escrow_for_settlement",
        new=verify_mock,
    ):
        with pytest.raises(EscrowVerificationError, match="amount insufficient"):
            await start_settlement_job(
                escrow_uid="0xescrow",
                negotiation_id="neg-1",
                ssh_public_key="ssh-rsa ...",
                sqlite_client=client,
                alkahest_client=MagicMock(),
            chain_name='anvil',
            )

    assert await client.load_escrow(escrow_uid="0xescrow") is None


@pytest.mark.asyncio
async def test_start_is_idempotent_by_escrow_uid(client):
    await _seed_seller_order(client)
    await _seed_negotiation(client)

    with patch(
        "market_storefront.services.fulfillment_reconciler.StorefrontFulfillmentReconciler.run_once",
        new=AsyncMock(),
    ), patch(
        "market_storefront.utils.escrow_verification.verify_escrow_for_settlement",
        new=AsyncMock(),
    ):
        first = await start_settlement_job(
            escrow_uid="0xescrow", negotiation_id="neg-1",
            ssh_public_key="ssh-rsa ...",
            sqlite_client=client, alkahest_client=MagicMock(),
            chain_name='anvil',
        )
        # Flip the existing job to 'ready' to prove the second call reads, not overwrites.
        await client.update_escrow(
            escrow_uid="0xescrow", status="ready",
            fulfillment_uid="0xattest", connection_details="ssh bob@vm",
        )
        second = await start_settlement_job(
            escrow_uid="0xescrow", negotiation_id="neg-1",
            ssh_public_key="ssh-rsa ...",
            sqlite_client=client, alkahest_client=MagicMock(),
            chain_name='anvil',
        )

    assert first["status"] == "provisioning"
    # Second call returned existing row, did not overwrite to provisioning again.
    assert second.get("status") == "ready"
    assert second.get("fulfillment_uid") == "0xattest"


# ---------------------------------------------------------------------------
# serialize_settlement_job
# ---------------------------------------------------------------------------


def test_serialize_omits_none_fields():
    raw = {
        "escrow_uid": "0xe",
        "negotiation_id": "neg-1",
        "status": "provisioning",
        "fulfillment_uid": None,
        "connection_details": None,
        "tenant_credentials": None,
        "reason": None,
        "created_at": "2026-04-23T00:00:00Z",
        "updated_at": "2026-04-23T00:00:00Z",
    }
    out = serialize_settlement_job(raw)
    assert "reason" not in out
    assert "attestation_uid" not in out
    assert "fulfillment_uid" not in out
    assert "tenant_credentials" not in out
    assert out["status"] == "provisioning"


def test_serialize_parses_tenant_credentials_json():
    raw = {
        "escrow_uid": "0xe",
        "negotiation_id": "neg-1",
        "status": "ready",
        "fulfillment_uid": "0xa",
        "connection_details": "ssh alice@vm",
        "tenant_credentials": json.dumps({"password": "secret"}),
        "reason": None,
        "created_at": "2026-04-23T00:00:00Z",
        "updated_at": "2026-04-23T00:00:00Z",
    }
    out = serialize_settlement_job(raw)
    assert out["tenant_credentials"] == {"password": "secret"}
    assert out["fulfillment_uid"] == "0xa"
    assert "attestation_uid" not in out
