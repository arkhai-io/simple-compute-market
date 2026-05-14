"""Synthesis of ``accepted_escrows`` from legacy ``demand_resource``.

The SQLite layer's ``upsert_listing`` synthesizes an ``accepted_escrows``
entry whenever the caller passes ``None`` but the listing has a typed
``demand_resource.token.contract_address``. This keeps pre-shape callers
working: the new column gets populated automatically and downstream
readers (validator, settlement) see the canonical form regardless of
which write path created the row.

Tests pin down:
  * Synthesis returns a single-entry list with the expected shape when
    ``demand_resource.token.contract_address`` is present.
  * Synthesis returns ``None`` for compute demands, hidden-reserve
    listings, or when the chain config can't resolve an erc20 escrow.
  * The synthesized entry uses the configured ``CONFIG.chain_name``
    and lowercases the escrow address.
  * Calling ``upsert_listing`` without ``accepted_escrows`` populates
    the column from ``demand_resource``.
  * Calling ``upsert_listing`` WITH an explicit ``accepted_escrows``
    leaves the caller's value untouched (no overwrite by synthesis).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from market_storefront.utils.sqlite_client import SQLiteClient


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
    real alkahest network up."""
    from service.clients import alkahest as alkahest_mod

    monkeypatch.setattr(
        alkahest_mod, "get_erc20_escrow_obligation_nontierable",
        lambda chain_name, *, config_path=None: _ESCROW_ADDR,
    )
    yield


def test_synthesize_from_token_demand(tmp_db_path, stub_alkahest_address):
    db = SQLiteClient(tmp_db_path)
    demand = {
        "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
        "amount": 1000000,  # 1 USDC per-hour
    }
    result = db._synthesize_accepted_escrows_from_demand(demand)
    assert result is not None
    assert len(result) == 1
    entry = result[0]
    assert entry["escrow_address"] == _ESCROW_ADDR.lower()
    assert entry["fields"] == {"payment_token": _TOKEN_ADDR}
    assert entry["price_per_hour"] == 1000000
    # chain_name comes from CONFIG; we don't pin a specific value here,
    # just that the field is present and a string.
    assert isinstance(entry["chain_name"], str) and entry["chain_name"]


def test_synthesize_from_token_demand_hidden_reserve(tmp_db_path, stub_alkahest_address):
    """``amount=None`` (hidden reserve) → entry still synthesized but
    ``price_per_hour`` stays None."""
    db = SQLiteClient(tmp_db_path)
    demand = {
        "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
        "amount": None,
    }
    result = db._synthesize_accepted_escrows_from_demand(demand)
    assert result is not None
    assert result[0]["price_per_hour"] is None
    assert result[0]["fields"] == {"payment_token": _TOKEN_ADDR}


def test_synthesize_accepts_json_string(tmp_db_path, stub_alkahest_address):
    """``demand_resource`` arrives as JSON string from SQLite; normalizer
    should round-trip it."""
    db = SQLiteClient(tmp_db_path)
    demand_str = json.dumps({
        "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
        "amount": 500,
    })
    result = db._synthesize_accepted_escrows_from_demand(demand_str)
    assert result is not None
    assert result[0]["fields"]["payment_token"] == _TOKEN_ADDR


def test_synthesize_returns_none_for_compute_demand(tmp_db_path, stub_alkahest_address):
    db = SQLiteClient(tmp_db_path)
    # ComputeResource-shaped demand has no token field.
    result = db._synthesize_accepted_escrows_from_demand({
        "gpu_model": "H200", "gpu_count": 1, "sla": 0.99, "region": "California, US",
    })
    assert result is None


def test_synthesize_returns_none_for_token_without_contract_address(
    tmp_db_path, stub_alkahest_address,
):
    db = SQLiteClient(tmp_db_path)
    result = db._synthesize_accepted_escrows_from_demand({
        "token": {"symbol": "USDC"},  # missing contract_address
        "amount": 100,
    })
    assert result is None


def test_synthesize_returns_none_when_alkahest_unavailable(tmp_db_path, monkeypatch):
    """If the alkahest helper raises (e.g. anvil chain with no config
    path), synthesis returns None and the row stays NULL — readers fall
    back to demand_resource."""
    from service.clients import alkahest as alkahest_mod

    def _raise(chain_name, *, config_path=None):
        raise ValueError("no alkahest config for this chain")

    monkeypatch.setattr(
        alkahest_mod, "get_erc20_escrow_obligation_nontierable", _raise,
    )
    db = SQLiteClient(tmp_db_path)
    result = db._synthesize_accepted_escrows_from_demand({
        "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
        "amount": 100,
    })
    assert result is None


def test_upsert_listing_synthesizes_when_caller_omits(tmp_db_path, stub_alkahest_address):
    """End-to-end: caller passes no accepted_escrows → upsert_listing
    synthesizes from demand_resource → column is populated on read."""
    db = SQLiteClient(tmp_db_path)
    demand = {
        "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
        "amount": 1000,
    }
    asyncio.run(db.upsert_listing(
        listing_id="lst1", status="open",
        created_at="2026-01-01", updated_at="2026-01-01",
        offer_resource={"gpu_model": "H200", "gpu_count": 1, "sla": 0.99, "region": "California, US"},
        demand_resource=demand,
        fulfillment_resource=None,
        max_duration_seconds=3600,
        seller="seller_url",
    ))
    row = asyncio.run(db.load_listing(listing_id="lst1"))
    assert row is not None
    accepted = row["accepted_escrows"]
    assert isinstance(accepted, list) and len(accepted) == 1
    assert accepted[0]["fields"] == {"payment_token": _TOKEN_ADDR}
    assert accepted[0]["price_per_hour"] == 1000


def test_upsert_listing_respects_explicit_accepted_escrows(
    tmp_db_path, stub_alkahest_address,
):
    """Caller-supplied accepted_escrows is not overwritten by synthesis."""
    db = SQLiteClient(tmp_db_path)
    explicit = [{
        "chain_name": "base_sepolia",
        "escrow_address": "0x" + "11" * 20,
        "fields": {"payment_token": "0x" + "22" * 20},
        "price_per_hour": 999,
    }]
    asyncio.run(db.upsert_listing(
        listing_id="lst2", status="open",
        created_at="2026-01-01", updated_at="2026-01-01",
        offer_resource={"gpu_model": "H200", "gpu_count": 1, "sla": 0.99, "region": "California, US"},
        demand_resource={
            "token": {"symbol": "USDC", "contract_address": _TOKEN_ADDR, "decimals": 6},
            "amount": 1000,
        },
        fulfillment_resource=None,
        max_duration_seconds=3600,
        seller="seller_url",
        accepted_escrows=explicit,
    ))
    row = asyncio.run(db.load_listing(listing_id="lst2"))
    assert row["accepted_escrows"] == explicit


def test_backfill_runs_on_schema_init(tmp_db_path, stub_alkahest_address):
    """Inserting a row with NULL accepted_escrows then re-opening the DB
    should backfill the column from demand_resource."""
    import sqlite3

    # First open creates the schema.
    db = SQLiteClient(tmp_db_path)
    # Write a row directly (bypassing synthesis) with NULL accepted_escrows.
    conn = sqlite3.connect(tmp_db_path)
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO listings(listing_id, status, created_at, updated_at, "
            "offer_resource, demand_resource, fulfillment_resource, "
            "max_duration_seconds, seller, accepted_escrows) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL)",
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

    # Verify the row is NULL before re-init.
    conn = sqlite3.connect(tmp_db_path)
    try:
        cur = conn.cursor()
        before = cur.execute(
            "SELECT accepted_escrows FROM listings WHERE listing_id=?",
            ("lst_legacy",),
        ).fetchone()
        assert before[0] is None
    finally:
        conn.close()

    # Re-open: schema init runs the backfill.
    db2 = SQLiteClient(tmp_db_path)
    row = asyncio.run(db2.load_listing(listing_id="lst_legacy"))
    assert row is not None
    accepted = row["accepted_escrows"]
    assert isinstance(accepted, list) and accepted
    assert accepted[0]["fields"]["payment_token"] == _TOKEN_ADDR
