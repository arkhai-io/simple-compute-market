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
    _open_order_ids,
    _open_order_resource_ids,
    _publish_round,
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
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE orders (
                order_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                offer_resource TEXT,
                demand_resource TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
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
    min_price: str | None = None,
    token: str | None = None,
) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO resources
               (resource_id, resource_type, resource_subtype, unit, value, state, attributes,
                min_price, token)
               VALUES (?, 'compute.gpu', 'rtx4090', 'count', 1, ?, ?, ?, ?)""",
            (resource_id, state, json.dumps(attrs), min_price, token),
        )
        conn.commit()
    finally:
        conn.close()


def _insert_order(path: str, order_id: str, status: str, resource_id: str | None) -> None:
    offer = {"gpu_model": "RTX 4090", "quantity": 1, "sla": 95.0, "region": "New York, US"}
    if resource_id:
        offer["resource_id"] = resource_id
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO orders (order_id, status, offer_resource) VALUES (?, ?, ?)",
            (order_id, status, json.dumps(offer)),
        )
        conn.commit()
    finally:
        conn.close()


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
    _insert_order(db, "o3", "accepted", "compute-003")
    assert _open_order_resource_ids(db) == {"compute-001"}


def test_open_order_resource_ids_skips_orders_without_resource_id(tmp_path):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", None)  # no resource_id in offer
    _insert_order(db, "o2", "open", "compute-002")
    assert _open_order_resource_ids(db) == {"compute-002"}


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

    def fake_publish(agent_url, offer, demand, duration_hours, wallet_address, private_key):
        calls.append({"offer": offer, "demand": demand})
        rid = offer["resource_id"]
        return {"status": "created", "listing_id": f"listing-for-{rid}"}

    monkeypatch.setattr("market_storefront.cli_publish._publish_offer", fake_publish)

    published, failed, skipped = _publish_round(
        db_path=db,
        base_url="http://agent",
        duration_hours=1,
        wallet_address="",
        private_key=None,
        default_min_price="100",
        default_token="MOCK",
        skip_ids={"compute-001"},
    )

    assert len(published) == 1, f"Expected exactly one publish, got {published}"
    assert len(skipped) == 1, f"Expected one skipped, got {skipped}"
    assert skipped[0]["resource_id"] == "compute-001"
    assert published[0]["resource"]["resource_id"] == "compute-002"
    assert not failed
    # The publish call carries the explicit resource_id so future `--watch`
    # cycles can tell which resource a given order covers.
    assert calls[0]["offer"]["resource_id"] == "compute-002"
    # And demand was assembled from the (default) pricing, not a flag.
    assert calls[0]["demand"] == {"token": "MOCK", "amount": "100"}


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
        db_path=db,
        base_url="http://agent",
        duration_hours=1,
        wallet_address="",
        private_key=None,
        default_min_price="100",
        default_token="MOCK",
        skip_ids=None,
    )
    assert len(published) == 1
    assert not failed
    assert not skipped


def test_open_order_ids_returns_only_open(tmp_path):
    """--abort-all's target set is just `status='open'` orders."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_order(db, "o1", "open", "compute-001")
    _insert_order(db, "o2", "closed", "compute-002")
    _insert_order(db, "o3", "open", None)  # no resource_id in offer is fine for abort
    _insert_order(db, "o4", "accepted", "compute-004")
    assert set(_open_order_ids(db)) == {"o1", "o3"}


def test_publish_round_per_row_pricing_overrides_default(tmp_path, monkeypatch):
    """Row-level min_price/token win over the [seller.pricing] defaults."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-cheap", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
        min_price="40", token="USDC",
    )
    _insert_resource(
        db, "compute-default", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, demand, *a, **k: (
            calls.append({"offer": offer, "demand": demand})
            or {"status": "created", "listing_id": f"l-{offer['resource_id']}"}
        ),
    )

    published, failed, _ = _publish_round(
        db_path=db,
        base_url="http://agent",
        duration_hours=1,
        wallet_address="",
        private_key=None,
        default_min_price="100",
        default_token="MOCK",
    )

    by_rid = {c["offer"]["resource_id"]: c["demand"] for c in calls}
    assert by_rid["compute-cheap"] == {"token": "USDC", "amount": "40"}
    assert by_rid["compute-default"] == {"token": "MOCK", "amount": "100"}
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
        min_price="50", token="MOCK",
    )
    _insert_resource(
        db, "compute-noprice", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "NY"},
    )

    calls: list[dict] = []
    monkeypatch.setattr(
        "market_storefront.cli_publish._publish_offer",
        lambda agent_url, offer, demand, *a, **k: (
            calls.append({"offer": offer, "demand": demand})
            or {"status": "created", "listing_id": f"l-{offer['resource_id']}"}
        ),
    )

    published, failed, _ = _publish_round(
        db_path=db,
        base_url="http://agent",
        duration_hours=1,
        wallet_address="",
        private_key=None,
        default_min_price=None,  # no fallback
        default_token="MOCK",
    )

    assert [c["offer"]["resource_id"] for c in calls] == ["compute-priced"]
    assert len(published) == 1
    assert len(failed) == 1
    assert failed[0][0]["resource_id"] == "compute-noprice"
    assert "min_price" in failed[0][1]


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
    published, failed, skipped = _publish_round(
        db_path=db,
        base_url="http://agent",
        duration_hours=1,
        wallet_address="",
        private_key=None,
        default_min_price="100",
        default_token="MOCK",
    )
    assert not published and not failed and not skipped
