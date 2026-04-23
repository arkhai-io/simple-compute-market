"""Unit tests for the negotiation/settlement seam.

The point of this split is: a successful negotiation's terms become a
durable, queryable artifact (agreed_price + agreed_duration_hours on
negotiation_threads). Settlement reads that artifact and does the on-chain
step — and because it reads, it can be retried without replaying rounds.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent.app.utils.sqlite_client import SQLiteClient


async def _seed_thread(
    client: SQLiteClient,
    *,
    negotiation_id: str,
    our_order_id: str | None = "buyer-ord-1",
    their_order_id: str | None = "seller-ord-1",
    their_agent_id: str | None = "http://seller:8001",
    terminal_state: str | None = None,
    agreed_price: int | None = None,
    agreed_duration_hours: int | None = None,
) -> None:
    conn = sqlite3.connect(client.db_path)
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO negotiation_threads
              (negotiation_id, our_order_id, their_order_id,
               our_agent_id, their_agent_id, status,
               created_at, updated_at, terminal_state,
               agreed_price, agreed_duration_hours, agreed_at)
            VALUES (?, ?, ?, 'http://buyer:8000', ?, 'active',
                    '2026-04-23T00:00:00Z', '2026-04-23T00:00:00Z', ?,
                    ?, ?, ?)
            """,
            (
                negotiation_id,
                our_order_id,
                their_order_id,
                their_agent_id,
                terminal_state,
                agreed_price,
                agreed_duration_hours,
                "2026-04-23T00:00:00Z" if agreed_price is not None else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# SQLiteClient.commit_agreed_terms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commit_agreed_terms_persists_to_row(tmp_path):
    client = SQLiteClient(db_path=str(tmp_path / "agent.db"))
    await _seed_thread(client, negotiation_id="neg-1", terminal_state="success")

    await client.commit_agreed_terms(
        negotiation_id="neg-1",
        agreed_price=1_500_000_000_000_000_000,  # 1.5 MOCK raw
        agreed_duration_hours=2,
    )

    row = await client.load_negotiation_thread_row(negotiation_id="neg-1")
    assert row["agreed_price"] == 1_500_000_000_000_000_000
    assert row["agreed_duration_hours"] == 2
    assert row["agreed_at"] is not None


@pytest.mark.asyncio
async def test_load_missing_thread_returns_none(tmp_path):
    client = SQLiteClient(db_path=str(tmp_path / "agent.db"))
    row = await client.load_negotiation_thread_row(negotiation_id="nope")
    assert row is None


# ---------------------------------------------------------------------------
# settle_negotiation — end-to-end with mocked I/O
# ---------------------------------------------------------------------------


@pytest.fixture
def _patch_agent_env(tmp_path):
    """Patch the action_executor module-level deps settle_negotiation touches."""
    client = SQLiteClient(db_path=str(tmp_path / "agent.db"))

    # Insert our buyer order so update_order has a row to target.
    conn = sqlite3.connect(client.db_path)
    conn.execute(
        """INSERT INTO orders (order_id, status, created_at, updated_at,
                               offer_resource, demand_resource, duration_hours,
                               order_maker, order_taker, escrow_uid)
           VALUES ('buyer-ord-1', 'open', '2026-04-23T00:00:00Z',
                   '2026-04-23T00:00:00Z', '{}', '{}', 1,
                   'http://buyer:8000', NULL, NULL)""",
    )
    conn.commit()
    conn.close()

    return client


@pytest.mark.asyncio
async def test_settle_refuses_when_thread_not_terminal(_patch_agent_env):
    from core.agent.app.utils.action_executor import settle_negotiation

    client = _patch_agent_env
    await _seed_thread(client, negotiation_id="neg-2", terminal_state=None, agreed_price=None)

    with patch("core.agent.app.utils.action_executor.get_sqlite_client", return_value=client):
        with pytest.raises(ValueError, match="terminal_state"):
            await settle_negotiation(
                negotiation_id="neg-2",
                alkahest_client=MagicMock(),
            )


@pytest.mark.asyncio
async def test_settle_refuses_when_no_agreed_price(_patch_agent_env):
    from core.agent.app.utils.action_executor import settle_negotiation

    client = _patch_agent_env
    await _seed_thread(
        client, negotiation_id="neg-3",
        terminal_state="success",
        agreed_price=None,  # committed terminal, never committed price
    )

    with patch("core.agent.app.utils.action_executor.get_sqlite_client", return_value=client):
        with pytest.raises(ValueError, match="no agreed_price"):
            await settle_negotiation(
                negotiation_id="neg-3",
                alkahest_client=MagicMock(),
            )


@pytest.mark.asyncio
async def test_settle_idempotent_when_escrow_already_set(_patch_agent_env):
    """Second settle call on an already-settled order is a no-op."""
    from core.agent.app.utils.action_executor import settle_negotiation

    client = _patch_agent_env
    # Mark the order as already having an escrow_uid.
    conn = sqlite3.connect(client.db_path)
    conn.execute(
        "UPDATE orders SET escrow_uid = '0xalready' WHERE order_id = 'buyer-ord-1'"
    )
    conn.commit()
    conn.close()

    await _seed_thread(
        client, negotiation_id="neg-4",
        terminal_state="success",
        agreed_price=10**18,
        agreed_duration_hours=1,
    )

    with patch("core.agent.app.utils.action_executor.get_sqlite_client", return_value=client):
        result = await settle_negotiation(
            negotiation_id="neg-4",
            alkahest_client=MagicMock(),  # should not be touched
        )

    assert result["status"] == "already_settled"
    assert result["escrow_uid"] == "0xalready"


@pytest.mark.asyncio
async def test_settle_refuses_without_alkahest_client(_patch_agent_env):
    """No alkahest → refuse (don't silently skip the on-chain step)."""
    from core.agent.app.utils.action_executor import settle_negotiation

    client = _patch_agent_env
    await _seed_thread(
        client, negotiation_id="neg-5",
        terminal_state="success",
        agreed_price=10**18,
        agreed_duration_hours=1,
    )

    # Stub fetch_agent_wallet_address + extract_compute_and_token so we reach
    # the alkahest_client check without exploding on earlier dependencies.
    fake_order_dict = {
        "order_id": "seller-ord-1",
        "order_maker": "http://seller:8001",
        "offer_resource": {"gpu_model": "H200"},
        "demand_resource": {
            "token": {
                "symbol": "MOCK",
                "contract_address": "0x" + "a" * 40,
                "decimals": 18,
            },
            "amount": 10**18,
        },
        "duration_hours": 1,
    }

    with (
        patch("core.agent.app.utils.action_executor.get_sqlite_client", return_value=client),
        patch("core.agent.app.utils.action_executor.get_registry_client",
              return_value=AsyncMock(get_order=AsyncMock(return_value=fake_order_dict))),
        patch("core.agent.app.utils.action_executor.fetch_agent_wallet_address",
              AsyncMock(return_value="0x" + "b" * 40)),
    ):
        with pytest.raises(RuntimeError, match="AlkahestClient is required"):
            await settle_negotiation(
                negotiation_id="neg-5",
                alkahest_client=None,
            )


@pytest.mark.asyncio
async def test_commit_after_failed_settle_leaves_terms_for_retry(_patch_agent_env):
    """Regression intent: if settle_negotiation raises, the committed terms
    remain on the thread so a retry has everything it needs.
    """
    from core.agent.app.utils.action_executor import settle_negotiation

    client = _patch_agent_env
    await _seed_thread(
        client, negotiation_id="neg-6",
        terminal_state="success",
        agreed_price=3 * 10**18,
        agreed_duration_hours=3,
    )

    with patch("core.agent.app.utils.action_executor.get_sqlite_client", return_value=client):
        with pytest.raises(Exception):  # either ValueError or RuntimeError — we only care that we got here
            await settle_negotiation(
                negotiation_id="neg-6",
                alkahest_client=None,  # forces failure
            )

    # Terms are still on the row.
    row = await client.load_negotiation_thread_row(negotiation_id="neg-6")
    assert row["agreed_price"] == 3 * 10**18
    assert row["agreed_duration_hours"] == 3
