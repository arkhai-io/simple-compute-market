"""Synthesis of ``accepted_escrows`` from legacy ``demand_resource``.

After the demand_resource cutover, ``synthesize_accepted_escrows_from_demand``
lives at module scope and is called from two places:

  * action_executor's MAKE_OFFER entry, converting the policy layer's
    ``demand`` payload into ``accepted_escrows`` before persistence;
  * the one-shot backfill in ``SQLiteClient._ensure_tables_sync`` that
    populates ``accepted_escrows`` on any pre-cutover row still carrying
    a ``demand_resource`` column before that column is dropped.

These tests pin the pure-transformation contract plus the backfill +
DROP COLUMN behavior.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from market_storefront.utils.sqlite_client import (
    SQLiteClient,
    synthesize_accepted_escrows_from_demand,
)


_TOKEN_ADDR = "0x" + "ab" * 20
_ESCROW_ADDR = "0x" + "cd" * 20


@pytest.fixture
def tmp_db_path():
    with tempfile.TemporaryDirectory() as d:
        yield os.path.join(d, "test.db")


@pytest.fixture
def stub_alkahest_address(monkeypatch):
    """Stub ``get_erc20_escrow_obligation_nontierable`` to return a known
    address regardless of which chain is configured — tests don't need a
    real alkahest network up. Also injects a synthetic ``[chains.anvil]``
    entry so the function's per-chain iteration produces at least one row.
    """
    from service.clients import alkahest as alkahest_mod
    from service.config_loader import ChainConfig
    from market_storefront.utils import config as agent_config

    monkeypatch.setattr(
        alkahest_mod, "get_erc20_escrow_obligation_nontierable",
        lambda chain_name, *, config_path=None: _ESCROW_ADDR,
    )
    monkeypatch.setattr(
        agent_config,
        "CHAINS",
        {
            "anvil": ChainConfig(
                name="anvil",
                rpc_url="http://localhost:8545",
                chain_id=31337,
                alkahest_address_config_path=None,
                identity_registry_address="0x" + "11" * 20,
                onchain_agent_id=None,
            ),
        },
        raising=False,
    )
    yield


def test_synthesize_from_token_demand(stub_alkahest_address):
    demand = {
        "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
        "amount": 1000000,  # 1 USDC per-hour
    }
    result = synthesize_accepted_escrows_from_demand(demand)
    assert result is not None
    assert len(result) == 1
    entry = result[0]
    assert entry["escrow_address"] == _ESCROW_ADDR.lower()
    assert entry["fields"] == {"token": _TOKEN_ADDR}
    # uint256-safe: price_per_hour is a decimal-digit string on the wire,
    # even when the caller passed a Python int.
    assert entry["price_per_hour"] == "1000000"
    # chain_name comes from CONFIG; just assert presence + type.
    assert isinstance(entry["chain_name"], str) and entry["chain_name"]
    # Sibling shape (escrow templates wire format) ships alongside legacy.
    assert entry["literal_fields"] == {"token": _TOKEN_ADDR}
    assert entry["rates"] == [{"field": "amount", "per": "hour", "value": "1000000"}]


def test_synthesize_from_token_demand_uint256_amount(stub_alkahest_address):
    """A 10-WETH amount (10^19 base units, overflows int64) survives the
    round-trip because the wire form is a string, not a JSON number."""
    big = 10 * 10**18  # 10 WETH in 18-decimal base units; > 2^63
    demand = {
        "token": {"symbol": "WETH", "contract_address": _TOKEN_ADDR, "decimals": 18},
        "amount": big,
    }
    result = synthesize_accepted_escrows_from_demand(demand)
    assert result is not None
    assert result[0]["price_per_hour"] == str(big)


def test_synthesize_accepts_string_amount(stub_alkahest_address):
    """Caller may pass amount as a decimal string — common when forwarded
    from inbound wire payloads that were already string-typed."""
    demand = {
        "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
        "amount": "1500",
    }
    result = synthesize_accepted_escrows_from_demand(demand)
    assert result is not None
    assert result[0]["price_per_hour"] == "1500"


def test_synthesize_from_token_demand_hidden_reserve(stub_alkahest_address):
    """``amount=None`` (hidden reserve) → entry still synthesized but
    ``price_per_hour`` stays None."""
    demand = {
        "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
        "amount": None,
    }
    result = synthesize_accepted_escrows_from_demand(demand)
    assert result is not None
    assert result[0]["price_per_hour"] is None
    assert result[0]["fields"] == {"token": _TOKEN_ADDR}
    # Hidden reserve produces no rates (no numeric value to advertise),
    # but literal_fields are still emitted so readers see a consistent shape.
    assert result[0]["literal_fields"] == {"token": _TOKEN_ADDR}
    assert result[0]["rates"] == []


def test_synthesize_accepts_json_string(stub_alkahest_address):
    """``demand`` arriving as JSON string (e.g. from a SQLite blob) is
    parsed before synthesis."""
    demand_str = json.dumps({
        "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
        "amount": 500,
    })
    result = synthesize_accepted_escrows_from_demand(demand_str)
    assert result is not None
    assert result[0]["fields"]["token"] == _TOKEN_ADDR


def test_synthesize_returns_none_for_compute_demand(stub_alkahest_address):
    # ComputeResource-shaped demand has no token field.
    result = synthesize_accepted_escrows_from_demand({
        "gpu_model": "H200", "gpu_count": 1, "sla": 0.99, "region": "California, US",
    })
    assert result is None


def test_synthesize_returns_none_for_token_without_contract_address(
    stub_alkahest_address,
):
    result = synthesize_accepted_escrows_from_demand({
        "token": {"symbol": "USDC"},  # missing contract_address
        "amount": 100,
    })
    assert result is None


def test_synthesize_returns_none_when_alkahest_unavailable(monkeypatch):
    """If the alkahest helper raises (e.g. anvil chain with no config
    path), synthesis returns None."""
    from service.clients import alkahest as alkahest_mod

    def _raise(chain_name, *, config_path=None):
        raise ValueError("no alkahest config for this chain")

    monkeypatch.setattr(
        alkahest_mod, "get_erc20_escrow_obligation_nontierable", _raise,
    )
    result = synthesize_accepted_escrows_from_demand({
        "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
        "amount": 100,
    })
    assert result is None


def test_upsert_listing_stores_explicit_accepted_escrows(tmp_db_path):
    """Caller-supplied accepted_escrows is round-tripped."""
    db = SQLiteClient(tmp_db_path)
    explicit = [{
        "chain_name": "base_sepolia",
        "escrow_address": "0x" + "11" * 20,
        "fields": {"token": "0x" + "22" * 20},
        "price_per_hour": 999,
    }]
    asyncio.run(db.upsert_listing(
        listing_id="lst2", status="open",
        created_at="2026-01-01", updated_at="2026-01-01",
        offer_resource={"gpu_model": "H200", "gpu_count": 1, "sla": 0.99, "region": "California, US"},
        fulfillment_resource=None,
        max_duration_seconds=3600,
        seller="seller_url",
        accepted_escrows=explicit,
    ))
    row = asyncio.run(db.load_listing(listing_id="lst2"))
    assert row["accepted_escrows"] == explicit


def test_backfill_runs_on_schema_init_and_drops_legacy_column(
    tmp_db_path, stub_alkahest_address,
):
    """Pre-cutover DB simulation: a row with a legacy ``demand_resource``
    column and NULL ``accepted_escrows`` should be backfilled on the
    next schema init, and the legacy column should be dropped afterwards.
    """
    import sqlite3

    # Manually create the pre-cutover schema: includes demand_resource
    # NOT NULL, no accepted_escrows. Schema init below will:
    #   1) ADD COLUMN accepted_escrows
    #   2) backfill from demand_resource
    #   3) DROP COLUMN demand_resource
    conn = sqlite3.connect(tmp_db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE listings (
              listing_id TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              offer_resource TEXT NOT NULL,
              demand_resource TEXT NOT NULL,
              fulfillment_resource TEXT,
              max_duration_seconds INTEGER,
              seller TEXT NOT NULL,
              buyer TEXT,
              matched_offer_id TEXT,
              seller_attestation TEXT,
              buyer_attestation TEXT,
              escrow_uid TEXT,
              oracle_address TEXT,
              paused INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        cur.execute(
            "INSERT INTO listings(listing_id, status, created_at, updated_at, "
            "offer_resource, demand_resource, fulfillment_resource, "
            "max_duration_seconds, seller) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (
                "lst_legacy", "open", "2026-01-01", "2026-01-01",
                json.dumps({"gpu_model": "H200", "gpu_count": 1, "sla": 0.99, "region": "California, US"}),
                json.dumps({
                    "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
                    "amount": 1000,
                }),
                3600, "seller_url",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    # Open via SQLiteClient → schema init runs the backfill + DROP COLUMN.
    db = SQLiteClient(tmp_db_path)
    row = asyncio.run(db.load_listing(listing_id="lst_legacy"))
    assert row is not None
    accepted = row["accepted_escrows"]
    assert isinstance(accepted, list) and accepted
    assert accepted[0]["fields"]["token"] == _TOKEN_ADDR

    # And the legacy column is gone.
    import sqlite3 as _sql
    conn = _sql.connect(tmp_db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(listings)")}
    finally:
        conn.close()
    assert "demand_resource" not in cols
    assert "accepted_escrows" in cols
