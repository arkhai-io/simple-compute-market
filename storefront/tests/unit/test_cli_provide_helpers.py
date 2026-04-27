"""Unit tests for `market provide` DB helpers.

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

from market_storefront.cli_provide import (
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


def _insert_resource(path: str, resource_id: str, state: str, attrs: dict) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """INSERT INTO resources
               (resource_id, resource_type, resource_subtype, unit, value, state, attributes)
               VALUES (?, 'compute.gpu', 'rtx4090', 'count', 1, ?, ?)""",
            (resource_id, state, json.dumps(attrs)),
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

    def fake_post(url, payload, headers):
        calls.append(payload)
        rid = payload["offer"]["resource_id"]
        return {"status": "created", "order_id": f"order-for-{rid}"}

    monkeypatch.setattr("market_storefront.cli_provide._post_json", fake_post)

    published, failed, skipped = _publish_round(
        db_path=db,
        base_url="http://agent",
        demand={"token": "MOCK", "amount": "100"},
        duration_hours=1,
        wallet_address="",
        private_key=None,
        skip_ids={"compute-001"},
    )

    assert len(published) == 1, f"Expected exactly one publish, got {published}"
    assert len(skipped) == 1, f"Expected one skipped, got {skipped}"
    assert skipped[0]["resource_id"] == "compute-001"
    assert published[0]["resource"]["resource_id"] == "compute-002"
    assert not failed
    # The POST payload carries the explicit resource_id so future `--watch`
    # cycles can tell which resource a given order covers.
    assert calls[0]["offer"]["resource_id"] == "compute-002"


def test_publish_round_publishes_all_when_skip_ids_empty(tmp_path, monkeypatch):
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-001", "available",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "New York, US"},
    )

    monkeypatch.setattr(
        "market_storefront.cli_provide._post_json",
        lambda *a, **k: {"status": "created", "order_id": "o1"},
    )

    published, failed, skipped = _publish_round(
        db_path=db,
        base_url="http://agent",
        demand={"token": "MOCK", "amount": "100"},
        duration_hours=1,
        wallet_address="",
        private_key=None,
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


def test_publish_round_ignores_leased_resources(tmp_path, monkeypatch):
    """Only `state='available'` resources get offered."""
    db = str(tmp_path / "agent.db")
    _init_db(db)
    _insert_resource(
        db, "compute-001", "leased",
        {"gpu_model": "RTX 4090", "sla": 95.0, "region": "New York, US"},
    )

    def fake_post(*a, **k):
        pytest.fail("Should not publish a leased resource")

    monkeypatch.setattr("market_storefront.cli_provide._post_json", fake_post)
    published, failed, skipped = _publish_round(
        db_path=db,
        base_url="http://agent",
        demand={"token": "MOCK", "amount": "100"},
        duration_hours=1,
        wallet_address="",
        private_key=None,
    )
    assert not published and not failed and not skipped
