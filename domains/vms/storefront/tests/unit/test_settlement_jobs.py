"""Unit tests for the polling-mode settlement flow.

Covers:
- escrows table round-trip through SQLiteClient helpers.
- start_settlement_job: refuses missing thread, non-terminal thread,
  no-agreed-price thread, missing seller order.
- Idempotence: second start on the same escrow_uid returns existing row.
- Background task: mocked fulfill_compute_obligation drives the row to
  ready / failed states.
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
    _run_settlement_job_bg,
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


async def _seed_seller_order(client: SQLiteClient, listing_id: str = "seller-ord-1") -> None:
    conn = sqlite3.connect(client.db_path)
    try:
        conn.execute(
            """INSERT INTO listings (listing_id, status, created_at, updated_at,
                                   offer_resource, max_duration_seconds,
                                   seller, accepted_escrows)
               VALUES (?, 'open', '2026-04-23T00:00:00Z', '2026-04-23T00:00:00Z',
                       '{}', 3600, 'http://seller:8001',
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

    # Prevent the background task from doing real work during the test.
    # Bypass on-chain escrow verification — covered in test_escrow_verification.py.
    with patch(
        "market_storefront.utils.settlement_jobs._run_settlement_job_bg",
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

    bg_mock = AsyncMock()
    verify_mock = AsyncMock(side_effect=EscrowVerificationError("amount insufficient"))
    with patch(
        "market_storefront.utils.settlement_jobs._run_settlement_job_bg",
        new=bg_mock,
    ), patch(
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

    # No DB row, no background task.
    assert await client.load_escrow(escrow_uid="0xescrow") is None
    bg_mock.assert_not_called()


@pytest.mark.asyncio
async def test_start_is_idempotent_by_escrow_uid(client):
    await _seed_seller_order(client)
    await _seed_negotiation(client)

    with patch(
        "market_storefront.utils.settlement_jobs._run_settlement_job_bg",
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
# _run_settlement_job_bg — patches escrow row from fulfill_compute_obligation result
# ---------------------------------------------------------------------------


async def _seed_escrow_provisioning(
    client: SQLiteClient,
    *,
    escrow_uid: str = "0xescrow",
    negotiation_id: str = "neg-1",
) -> None:
    await client.insert_escrow(
        escrow_uid=escrow_uid,
        negotiation_id=negotiation_id,
        chain_name="anvil",
        escrow_address="0x" + "aa" * 20,
    )


@pytest.mark.asyncio
async def test_background_task_writes_ready_on_success(client):
    await _seed_escrow_provisioning(client)
    mock_fulfill = AsyncMock(return_value={
        "status": "fulfilled",
        "fulfillment_uid": "0xattest",
        "connection_details": "ssh alice@vm1",
        "tenant_credentials": {"password": "secret"},
    })

    with patch(
        "market_storefront.services.fulfillment_service.fulfill_compute_obligation",
        new=mock_fulfill,
    ):
        await _run_settlement_job_bg(
            escrow_uid="0xescrow",
            provision=make_vm_provision_terms(duration_seconds=3600, ssh_public_key="ssh-rsa ..."),
            listing_id="seller-ord-1",
            order_dict={"listing_id": "seller-ord-1", "max_duration_seconds": 3600},
            sqlite_client=client,
            alkahest_client=MagicMock(),
        )

    row = await client.load_escrow(escrow_uid="0xescrow")
    assert row["status"] == "ready"
    assert row["fulfillment_uid"] == "0xattest"
    assert row["connection_details"] == "ssh alice@vm1"
    assert json.loads(row["tenant_credentials"]) == {"password": "secret"}


@pytest.mark.asyncio
async def test_background_task_threads_the_listings_mapped_site_to_fulfillment(client):
    """A listing already mapped to a site (derived_compute_listings)
    must have that site_id reach the domain-agnostic fulfillment.fulfill
    dispatch -- proves the site_id resolution added in
    _run_settlement_job_bg actually reaches its call, not just that
    fulfill_vm_obligation honors a site_id kwarg when given one."""
    from domains.vms.listings.reconciler import record_derived_listing

    await _seed_escrow_provisioning(client)
    record_derived_listing(
        client.db_path, listing_id="seller-ord-1", site_id="dc-mapped",
        resource_id="res-1", gpu_count=2,
    )
    mock_fulfill = AsyncMock(return_value={
        "status": "fulfilled",
        "fulfillment_uid": "0xattest",
        "connection_details": "ssh alice@vm1",
        "tenant_credentials": {"password": "secret"},
    })

    with patch(
        "market_storefront.services.fulfillment_service.fulfill_compute_obligation",
        new=mock_fulfill,
    ):
        await _run_settlement_job_bg(
            escrow_uid="0xescrow",
            provision=make_vm_provision_terms(duration_seconds=3600, ssh_public_key="ssh-rsa ..."),
            listing_id="seller-ord-1",
            order_dict={"listing_id": "seller-ord-1", "max_duration_seconds": 3600},
            sqlite_client=client,
            alkahest_client=MagicMock(),
        )

    assert mock_fulfill.call_args.kwargs["site_id"] == "dc-mapped"


@pytest.mark.asyncio
async def test_background_task_writes_failed_on_exception(client):
    await _seed_escrow_provisioning(client)
    mock_fulfill = AsyncMock(side_effect=RuntimeError("vm host unreachable"))

    with patch(
        "market_storefront.services.fulfillment_service.fulfill_compute_obligation",
        new=mock_fulfill,
    ):
        await _run_settlement_job_bg(
            escrow_uid="0xescrow",
            provision=make_vm_provision_terms(duration_seconds=3600, ssh_public_key="ssh-rsa ..."),
            listing_id="seller-ord-1",
            order_dict={"listing_id": "seller-ord-1", "max_duration_seconds": 3600},
            sqlite_client=client,
            alkahest_client=MagicMock(),
        )

    row = await client.load_escrow(escrow_uid="0xescrow")
    assert row["status"] == "failed"
    assert "vm host unreachable" in row["reason"]


@pytest.mark.asyncio
async def test_background_task_leaves_listing_open_on_failure(client):
    """A failed deal updates only per-escrow state; listing state is unchanged."""
    await _seed_seller_order(client, listing_id="seller-ord-1")
    await _seed_escrow_provisioning(client)
    mock_fulfill = AsyncMock(side_effect=RuntimeError("vm host unreachable"))

    with patch(
        "market_storefront.services.fulfillment_service.fulfill_compute_obligation",
        new=mock_fulfill,
    ):
        await _run_settlement_job_bg(
            escrow_uid="0xescrow",
            provision=make_vm_provision_terms(duration_seconds=3600, ssh_public_key="ssh-rsa ..."),
            listing_id="seller-ord-1",
            order_dict={"listing_id": "seller-ord-1", "max_duration_seconds": 3600},
            sqlite_client=client,
            alkahest_client=MagicMock(),
        )

    assert (await client.load_escrow(escrow_uid="0xescrow"))["status"] == "failed"
    listing = await client.load_listing(listing_id="seller-ord-1")
    assert listing["status"] == "open"


@pytest.mark.asyncio
async def test_background_task_writes_failed_on_non_fulfilled_status(client):
    """fulfill_compute_obligation returned a non-exception but non-success result."""
    await _seed_escrow_provisioning(client)
    mock_fulfill = AsyncMock(return_value={
        "status": "error",
        "message": "Provisioning failed: No available compute VM",
    })

    with patch(
        "market_storefront.services.fulfillment_service.fulfill_compute_obligation",
        new=mock_fulfill,
    ):
        await _run_settlement_job_bg(
            escrow_uid="0xescrow",
            provision=make_vm_provision_terms(duration_seconds=3600, ssh_public_key="ssh-rsa ..."),
            listing_id="seller-ord-1",
            order_dict={"listing_id": "seller-ord-1", "max_duration_seconds": 3600},
            sqlite_client=client,
            alkahest_client=MagicMock(),
        )

    row = await client.load_escrow(escrow_uid="0xescrow")
    assert row["status"] == "failed"
    assert "No available compute VM" in row["reason"]


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


def test_serialize_includes_fulfillment_id_distinct_from_fulfillment_uid():
    """fulfillment_id (durable physical-fulfillment identity) and
    fulfillment_uid (on-chain settlement-claim identity) are different
    concepts and may both be set on the same row."""
    raw = {
        "escrow_uid": "0xe",
        "negotiation_id": "neg-1",
        "status": "provisioning",
        "fulfillment_uid": "0xa",
        "fulfillment_id": "fulfillment-123",
        "created_at": "2026-04-23T00:00:00Z",
        "updated_at": "2026-04-23T00:00:00Z",
    }
    out = serialize_settlement_job(raw)
    assert out["fulfillment_id"] == "fulfillment-123"
    assert out["fulfillment_uid"] == "0xa"
    assert out["fulfillment_id"] != out["fulfillment_uid"]


def test_serialize_omits_fulfillment_id_when_none():
    raw = {
        "escrow_uid": "0xe",
        "negotiation_id": "neg-1",
        "status": "provisioning",
        "fulfillment_id": None,
        "created_at": "2026-04-23T00:00:00Z",
        "updated_at": "2026-04-23T00:00:00Z",
    }
    out = serialize_settlement_job(raw)
    assert "fulfillment_id" not in out

@pytest.mark.asyncio
async def test_fulfillment_context_and_processing_claim_round_trip(client):
    await client.insert_escrow(
        escrow_uid="0xresume", negotiation_id="neg-resume",
        chain_name="anvil", escrow_address="0x" + "cc" * 20,
    )
    context = json.dumps({
        "kind": "vm.storefront.fulfillment-context",
        "schema_version": 1,
        "payload": {"escrow_uid": "0xresume", "fulfillment_request": {}},
    })
    await client.update_escrow(
        escrow_uid="0xresume",
        fulfillment_context=context,
        fulfillment_phase="context_persisted",
    )
    rows = await client.list_incomplete_primary_escrows(limit=10)
    assert [row["escrow_uid"] for row in rows] == ["0xresume"]
    assert rows[0]["fulfillment_context"] == context
    assert await client.claim_escrow_convergence(
        escrow_uid="0xresume", owner="worker-a", lease_until="2999-01-01T00:00:00+00:00"
    ) is True
    assert await client.claim_escrow_convergence(
        escrow_uid="0xresume", owner="worker-b", lease_until="2999-01-01T00:00:00+00:00"
    ) is False
    await client.release_escrow_convergence(escrow_uid="0xresume", owner="worker-a")
    assert await client.claim_escrow_convergence(
        escrow_uid="0xresume", owner="worker-b", lease_until="2999-01-01T00:00:00+00:00"
    ) is True
