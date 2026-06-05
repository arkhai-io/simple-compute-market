"""Unit tests for `market-storefront publish` DB helpers.

The `--watch` mode's correctness hinges on these two functions:

- `_open_order_resource_ids(db)` — returns the set of resource_ids that
  currently have an open sell order, so `--watch` can skip them.
- `_publish_round(...)` — given a `skip_ids`, publishes one order per
  available resource NOT in the skip set.

Testing these against a real SQLite schema catches the most likely
regression: `--watch` publishing duplicate orders for the same resource
on every cycle.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from market_storefront.cli_publish import (
    _available_resources,
    _open_listing_ids,
    _open_listing_resource_keys,
    _open_order_resource_ids,
    _publish_round,
    _stale_open_listing_ids,
)
from service.clients.token import ERC20TokenMetadata
from tests._settings_overrides import settings_overrides


_MOCK_ADDRESS = "0x9fe46736679d2d9a65f0992f2272de9f3c7fa6e0"
_WALLET_ADDRESS = "0x1111111111111111111111111111111111111111"
_USDC_ADDRESS = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
_TOKEN_DECIMALS = {
    _MOCK_ADDRESS.lower(): ("MOCK", 0),
    _USDC_ADDRESS.lower(): ("USDC", 6),
}


@pytest.fixture(autouse=True)
def _stub_resolve_token(monkeypatch):
    """Replace chain-RPC token resolution with a static map for tests.

    The publish path now eth_calls ``symbol()``/``decimals()`` for every
    token address it sees. Unit tests don't have an RPC, so we stub the
    resolver to return canned metadata for the two addresses these tests
    use. Also injects a synthetic [chains.anvil] entry + stubs the alkahest
    escrow-address lookup so the per-chain accepted_escrows iteration
    produces at least one row.
    """
    def fake_resolve(address: str, *, rpc_url: str, chain_id: int, refresh: bool = False):
        key = address.lower()
        if key not in _TOKEN_DECIMALS:
            from service.clients.token import TokenResolutionError
            raise TokenResolutionError(f"untested address: {address}")
        sym, dec = _TOKEN_DECIMALS[key]
        return ERC20TokenMetadata(
            symbol=sym, contract_address=address.lower(),
            decimals=dec, chain_id=chain_id,
        )
    monkeypatch.setattr(
        "market_storefront.cli_publish.resolve_token", fake_resolve, raising=False,
    )
    # cli_publish imports resolve_token lazily inside _publish_round, so
    # patch the source module too.
    monkeypatch.setattr(
        "service.clients.token.resolve_token", fake_resolve,
    )
    from service.clients import alkahest as alkahest_mod
    monkeypatch.setattr(
        alkahest_mod, "get_erc20_escrow_obligation_nontierable",
        lambda chain_name, *, config_path=None: "0x" + "cd" * 20,
    )
    monkeypatch.setattr(
        alkahest_mod, "get_recipient_arbiter",
        lambda chain_name, *, config_path=None: "0x" + "ab" * 20,
    )
    from service.config_loader import ChainConfig
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


def _init_db(path: str) -> None:
    """Create the minimal subset of the agent schema the helpers touch."""
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE resources (
                pk INTEGER PRIMARY KEY AUTOINCREMENT,
                resource_id TEXT NOT NULL UNIQUE,
                resource_type TEXT NOT NULL,
                resource_subtype TEXT,
                unit TEXT,
                value NUMERIC,
                state TEXT,
                attributes TEXT,
                min_price TEXT,
                token TEXT,
                max_duration_seconds INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE listings (
                listing_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                offer_resource TEXT,
                demand_resource TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE compute_allocations (
                allocation_id TEXT PRIMARY KEY,
                resource_id TEXT NOT NULL,
                listing_id TEXT,
                escrow_uid TEXT,
                gpu_count INTEGER NOT NULL,
                state TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                released_at TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _insert_resource(
    path: str,
    resource_id: str,
    state: str,
    attrs: dict,
    *,
    gpu_count: int = 1,
    min_price: str | None = None,
    token: str | None = None,
    max_duration_seconds: int | None = None,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO resources
               (resource_id, resource_type, resource_subtype, unit, value, state, attributes,
                min_price, token, max_duration_seconds)
               VALUES (?, 'compute.gpu', 'rtx4090', 'count', ?, ?, ?, ?, ?, ?)""",
            (
                resource_id,
                gpu_count,
                state,
                json.dumps(attrs),
                min_price,
                token,
                max_duration_seconds,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_allocation(
    path: str,
    allocation_id: str,
    resource_id: str,
    gpu_count: int,
    state: str,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO compute_allocations
               (allocation_id, resource_id, gpu_count, state)
               VALUES (?, ?, ?, ?)""",
            (allocation_id, resource_id, gpu_count, state),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_order(path: str, order_id: str, status: str, resource_id: str | None) -> None:
    offer = {"gpu_model": "RTX 4090", "gpu_count": 1, "sla": 95.0, "region": "New York, US"}
    if resource_id:
        offer["resource_id"] = resource_id
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO listings (listing_id, status, offer_resource) VALUES (?, ?, ?)",
            (order_id, status, json.dumps(offer)),
        )
        conn.commit()
    finally:
        conn.close()


def _round_kwargs(**overrides):
    """Common _publish_round kwargs; tests override specific keys."""
    base = dict(
        base_url="http://agent",
        wallet_address=_WALLET_ADDRESS,
        private_key=None,
        default_min_price="100",
        default_token_address=_MOCK_ADDRESS,
        default_max_duration_seconds=None,
        rpc_url="http://rpc",
        chain_id=1,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _open_order_resource_ids
# ---------------------------------------------------------------------------


def test_open_order_resource_ids_empty_when_no_orders(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    assert _open_order_resource_ids(db) == set()


def test_open_order_resource_ids_picks_up_open_orders(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", "compute-001")
    _insert_order(db, "o2", "open", "compute-002")
    assert _open_order_resource_ids(db) == {"compute-001", "compute-002"}


def test_open_order_resource_ids_ignores_closed_orders(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", "compute-001")
    _insert_order(db, "o2", "closed", "compute-002")
    _insert_order(db, "o3", "expired", "compute-003")
    assert _open_order_resource_ids(db) == {"compute-001"}


def test_open_order_resource_ids_skips_orders_without_resource_id(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", None)
    _insert_order(db, "o2", "open", "compute-002")
    assert _open_order_resource_ids(db) == {"compute-002"}


def test_open_listing_resource_keys_include_gpu_slice(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", "compute-001")
    _insert_order(db, "o2", "open", "compute-002")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE listings SET offer_resource = ? WHERE listing_id = ?",
            (
                json.dumps({
                    "resource_id": "compute-002",
                    "gpu_model": "RTX 4090",
                    "gpu_count": 2,
                    "sla": 95.0,
                    "region": "New York, US",
                }),
                "o2",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    assert _open_listing_resource_keys(db) == {
        "compute-001:gpus:1",
        "compute-002:gpus:2",
    }


# ---------------------------------------------------------------------------
# _publish_round
# ---------------------------------------------------------------------------


def test_publish_round_skips_covered_resources(tmp_path, monkeypatch):
    """The core --watch invariant: never publish a duplicate order for a
    resource that already has an open one."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-001", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "New York, US"},
    )
    _insert_resource(
        db, "compute-002", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "New York, US"},
    )

    calls: list[dict] = []

    def fake_publish(
        agent_url, offer, accepted_escrows, demands,
        max_duration_seconds, wallet_address, private_key,
    ):
        calls.append({
            "offer": offer,
            "accepted_escrows": accepted_escrows,
            "demands": demands,
        })
        rid = offer["resource_id"]
        return {"status": "created", "listing_id": f"listing-for-{rid}"}

    monkeypatch.setattr("market_storefront.cli_publish._publish_offer", fake_publish)

    published, failed, skipped = _publish_round(
        db_path=db, skip_ids={"compute-001"}, **_round_kwargs(),
    )

    assert len(published) == 1, f"Expected exactly one publish, got {published}"
    assert len(skipped) == 1, f"Expected one skipped, got {skipped}"
    assert skipped[0]["resource_id"] == "compute-001"
    assert published[0]["resource"]["resource_id"] == "compute-002"
    assert not failed
    assert calls[0]["offer"]["resource_id"] == "compute-002"
    entry = calls[0]["accepted_escrows"][0]
    assert entry["literal_fields"] == {"token": _MOCK_ADDRESS}
    assert calls[0]["demands"][0]["demand_data"] == {"recipient": _WALLET_ADDRESS}
    assert entry["rates"] == [{"field": "amount", "per": "hour", "value": "100"}]


def test_publish_round_publishes_all_when_skip_ids_empty(tmp_path, monkeypatch):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-001", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "New York, US"},
    )

    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda *a, **k: {"status": "created", "listing_id": "o1"},
    )

    published, failed, skipped = _publish_round(
        db_path=db, skip_ids=None, **_round_kwargs(),
    )
    assert len(published) == 1
    assert not failed
    assert not skipped


def test_available_resources_derives_slices_from_gpu_capacity(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-4x", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        gpu_count=4,
    )

    rows = _available_resources(db)

    assert [r["gpu_count"] for r in rows] == [1, 2, 3, 4]
    assert {r["resource_key"] for r in rows} == {
        "compute-4x:gpus:1",
        "compute-4x:gpus:2",
        "compute-4x:gpus:3",
        "compute-4x:gpus:4",
    }


def test_available_resources_closes_oversized_slices_when_capacity_held(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-4x", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        gpu_count=4,
    )
    _insert_allocation(db, "alloc-1", "compute-4x", 2, "leased")

    rows = _available_resources(db)

    assert [r["gpu_count"] for r in rows] == [1, 2]


def test_publish_round_publishes_one_listing_per_available_slice(tmp_path, monkeypatch):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-4x", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        gpu_count=4,
    )

    calls: list[dict] = []

    def fake_publish(agent_url, offer, accepted_escrows, *a, **k):
        calls.append(offer)
        return {
            "status": "created",
            "listing_id": f"l-{offer['resource_id']}-{offer['gpu_count']}x",
        }

    monkeypatch.setattr("market_storefront.cli_publish._publish_offer", fake_publish)

    published, failed, skipped = _publish_round(db_path=db, **_round_kwargs())

    assert [c["gpu_count"] for c in calls] == [1, 2, 3, 4]
    assert len(published) == 4
    assert not failed
    assert not skipped

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            """
            SELECT listing_id, resource_id, gpu_count, status, derivation_key
            FROM derived_compute_listings
            ORDER BY gpu_count
            """
        ).fetchall()
    finally:
        conn.close()
    assert rows == [
        ("l-compute-4x-1x", "compute-4x", 1, "open", "compute-4x:gpus:1"),
        ("l-compute-4x-2x", "compute-4x", 2, "open", "compute-4x:gpus:2"),
        ("l-compute-4x-3x", "compute-4x", 3, "open", "compute-4x:gpus:3"),
        ("l-compute-4x-4x", "compute-4x", 4, "open", "compute-4x:gpus:4"),
    ]


def test_stale_open_listing_ids_finds_slices_above_available_capacity(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-4x", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        gpu_count=4,
    )
    for gpu_count in (1, 2, 3, 4):
        _insert_order(db, f"listing-{gpu_count}x", "open", "compute-4x")
        conn = sqlite3.connect(db)
        try:
            conn.execute(
                "UPDATE listings SET offer_resource = ? WHERE listing_id = ?",
                (
                    json.dumps({
                        "resource_id": "compute-4x",
                        "gpu_model": "RTX 4090",
                        "gpu_count": gpu_count,
                        "sla": 95.0,
                        "region": "NY",
                    }),
                    f"listing-{gpu_count}x",
                ),
            )
            conn.commit()
        finally:
            conn.close()
    _insert_allocation(db, "alloc-1", "compute-4x", 2, "leased")

    assert _stale_open_listing_ids(db) == ["listing-3x", "listing-4x"]


def test_publish_round_reopens_existing_derived_listing_id(tmp_path, monkeypatch):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-4x", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        gpu_count=4,
    )
    _insert_order(db, "listing-3x-old", "closed", "compute-4x")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "UPDATE listings SET offer_resource = ? WHERE listing_id = ?",
            (
                json.dumps({
                    "resource_id": "compute-4x",
                    "gpu_model": "RTX 4090",
                    "gpu_count": 3,
                    "sla": 95.0,
                    "region": "NY",
                }),
                "listing-3x-old",
            ),
        )
        conn.execute(
            """
            CREATE TABLE derived_compute_listings (
                listing_id TEXT PRIMARY KEY,
                resource_id TEXT NOT NULL,
                gpu_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                derivation_key TEXT NOT NULL UNIQUE,
                last_reconciled_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """INSERT INTO derived_compute_listings
               (listing_id, resource_id, gpu_count, status, derivation_key)
               VALUES ('listing-3x-old', 'compute-4x', 3, 'closed', 'compute-4x:gpus:3')"""
        )
        conn.commit()
    finally:
        conn.close()

    created: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, accepted_escrows, *a, **k: (
            created.append(offer)
            or {"status": "created", "listing_id": f"new-{offer['gpu_count']}x"}
        ),
    )

    with settings_overrides(enable_registry_discovery=False):
        published, failed, skipped = _publish_round(
            db_path=db,
            skip_ids={
                "compute-4x:gpus:1",
                "compute-4x:gpus:2",
                "compute-4x:gpus:4",
            },
            **_round_kwargs(),
        )

    assert not failed
    assert [p["response"]["listing_id"] for p in published] == ["listing-3x-old"]
    assert created == []
    assert len(skipped) == 3
    conn = sqlite3.connect(db)
    try:
        status = conn.execute(
            "SELECT status FROM listings WHERE listing_id = 'listing-3x-old'"
        ).fetchone()[0]
        derived_status = conn.execute(
            "SELECT status FROM derived_compute_listings WHERE derivation_key = 'compute-4x:gpus:3'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "open"
    assert derived_status == "open"


def test_publish_round_normalizes_zero_duration_to_unlimited(tmp_path, monkeypatch):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-001", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "New York, US"},
    )

    calls: list[int | None] = []

    def fake_publish(
        agent_url, offer, accepted_escrows, demands,
        max_duration_seconds, wallet_address, private_key,
    ):
        calls.append(max_duration_seconds)
        return {"status": "created", "listing_id": "o1"}

    monkeypatch.setattr("market_storefront.cli_publish._publish_offer", fake_publish)

    published, failed, skipped = _publish_round(
        db_path=db,
        skip_ids=None,
        **_round_kwargs(default_max_duration_seconds=0),
    )

    assert len(published) == 1
    assert not failed
    assert not skipped
    assert calls == [None]


def test_publish_round_preserves_positive_row_duration(tmp_path, monkeypatch):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-001", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "New York, US"},
        max_duration_seconds=3600,
    )

    calls: list[int | None] = []

    def fake_publish(agent_url, offer, accepted_escrows, demands, max_duration_seconds, wallet_address, private_key):
        calls.append(max_duration_seconds)
        return {"status": "created", "listing_id": "o1"}

    monkeypatch.setattr("market_storefront.cli_publish._publish_offer", fake_publish)

    published, failed, skipped = _publish_round(
        db_path=db,
        skip_ids=None,
        **_round_kwargs(default_max_duration_seconds=0),
    )

    assert len(published) == 1
    assert not failed
    assert not skipped
    assert calls == [3600]


def test_open_order_ids_returns_only_open(tmp_path):
    """--abort-all's target set is just `status='open'` listings."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", "compute-001")
    _insert_order(db, "o2", "closed", "compute-002")
    _insert_order(db, "o3", "open", None)
    _insert_order(db, "o4", "expired", "compute-004")
    assert set(_open_listing_ids(db)) == {"o1", "o3"}


def test_publish_round_per_row_pricing_overrides_default(tmp_path, monkeypatch):
    """Row-level min_price/token win over the [seller.pricing] defaults."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-cheap", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        min_price="40", token=_USDC_ADDRESS,
    )
    _insert_resource(
        db, "compute-default", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, accepted_escrows, *a, **k: (
            calls.append({"offer": offer, "accepted_escrows": accepted_escrows})
            or {"status": "created", "listing_id": f"l-{offer['resource_id']}"}
        ),
    )

    published, failed, _ = _publish_round(db_path=db, **_round_kwargs())

    by_rid = {c["offer"]["resource_id"]: c["accepted_escrows"][0] for c in calls}
    assert by_rid["compute-cheap"]["literal_fields"]["token"] == _USDC_ADDRESS
    assert by_rid["compute-cheap"]["rates"][0]["value"] == "40000000"
    assert by_rid["compute-default"]["literal_fields"]["token"] == _MOCK_ADDRESS
    assert by_rid["compute-default"]["rates"][0]["value"] == "100"
    assert len(published) == 2
    assert not failed


def test_publish_round_skips_resources_without_pricing(tmp_path, monkeypatch):
    """Row has no min_price and no default → reported as failed, skipping
    publish entirely. No HTTP call for that resource."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-priced", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        min_price="50", token=_MOCK_ADDRESS,
    )
    _insert_resource(
        db, "compute-noprice", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, accepted_escrows, *a, **k: (
            calls.append({"offer": offer, "accepted_escrows": accepted_escrows})
            or {"status": "created", "listing_id": f"l-{offer['resource_id']}"}
        ),
    )

    published, failed, _ = _publish_round(
        db_path=db, **_round_kwargs(default_min_price=None),
    )

    assert [c["offer"]["resource_id"] for c in calls] == ["compute-priced"]
    assert len(published) == 1
    assert len(failed) == 1
    assert failed[0][0]["resource_id"] == "compute-noprice"
    assert "min_price" in failed[0][1]


def test_publish_round_priceless_publishes_with_empty_rates(tmp_path, monkeypatch):
    """publish_priceless=True publishes rows without a min_price as
    empty ``rates`` (hidden reserve) — distinct from a single ``"0"``
    rate (free)."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-noprice", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, accepted_escrows, *a, **k: (
            calls.append({"offer": offer, "accepted_escrows": accepted_escrows})
            or {"status": "created", "listing_id": f"l-{offer['resource_id']}"}
        ),
    )

    published, failed, _ = _publish_round(
        db_path=db,
        publish_priceless=True,
        **_round_kwargs(default_min_price=None),
    )

    assert len(published) == 1
    assert len(failed) == 0
    entry = calls[0]["accepted_escrows"][0]
    assert entry["rates"] == []
    assert entry["literal_fields"]["token"] == _MOCK_ADDRESS


def test_publish_round_explicit_zero_publishes_as_free(tmp_path, monkeypatch):
    """A row with min_price="0" publishes with rate value "0" (explicit
    free offering) — distinct semantically from empty ``rates`` (hidden
    reserve). The default_min_price does NOT override an explicit 0."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-free", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        min_price="0", token=_MOCK_ADDRESS,
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, accepted_escrows, *a, **k: (
            calls.append({"offer": offer, "accepted_escrows": accepted_escrows})
            or {"status": "created", "listing_id": f"l-{offer['resource_id']}"}
        ),
    )

    published, failed, _ = _publish_round(
        db_path=db, **_round_kwargs(default_min_price="500"),
    )

    assert len(published) == 1
    assert len(failed) == 0
    assert calls[0]["accepted_escrows"][0]["rates"][0]["value"] == "0"


def test_publish_round_priceless_off_still_skips(tmp_path, monkeypatch):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-noprice", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
    )
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda *a, **k: {"status": "created"},
    )
    published, failed, _ = _publish_round(
        db_path=db, **_round_kwargs(default_min_price=None),
    )
    assert len(published) == 0
    assert len(failed) == 1
    assert "publish_priceless" in failed[0][1]


def test_publish_round_priceless_message_mentions_opt_in(tmp_path, monkeypatch):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-noprice", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
    )
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda *a, **k: {"status": "created"},
    )
    _, failed, _ = _publish_round(
        db_path=db, **_round_kwargs(default_min_price=None),
    )
    assert "publish_priceless" in failed[0][1]


def test_publish_round_ignores_leased_resources(tmp_path, monkeypatch):
    """Only `state='available'` resources get offered."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-001", "leased",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "New York, US"},
    )

    def fake_publish(*a, **k):
        pytest.fail("Should not publish a leased resource")

    monkeypatch.setattr("market_storefront.cli_publish._publish_offer", fake_publish)
    published, failed, skipped = _publish_round(db_path=db, **_round_kwargs())
    assert not published and not failed and not skipped


def test_publish_round_rejects_non_address_token(tmp_path, monkeypatch):
    """Symbol shorthand in the CSV token column fails the row clearly."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-001", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        min_price="50", token="USDC",
    )

    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda *a, **k: pytest.fail("should not publish a bad row"),
    )
    _, failed, _ = _publish_round(db_path=db, **_round_kwargs())
    assert len(failed) == 1
    assert "0x" in failed[0][1]


def test_publish_round_missing_token_with_no_default(tmp_path, monkeypatch):
    """No CSV token, no default_token_address → skip with helpful message."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-001", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        min_price="50",
    )

    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda *a, **k: pytest.fail("should not publish"),
    )
    _, failed, _ = _publish_round(
        db_path=db, **_round_kwargs(default_token_address=None),
    )
    assert len(failed) == 1
    assert "token" in failed[0][1]
