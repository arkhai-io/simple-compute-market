from __future__ import annotations

import json
import sqlite3

from arkhai_bare_metal.storefront_publication import (
    bare_metal_listing_candidates,
    close_stale_bare_metal_listings,
    closed_available_bare_metal_listing_ids,
    ensure_derived_bare_metal_listings_table,
    load_derived_bare_metal_listing,
    mark_derived_bare_metal_listings_closed,
    open_bare_metal_listing_keys,
    record_derived_bare_metal_listing,
    reopen_derived_bare_metal_listing_if_present,
    stale_open_bare_metal_listing_ids,
)


def _init_db(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE listings (
                listing_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                offer_resource TEXT
            )
            """
        )
        ensure_derived_bare_metal_listings_table(conn)
        conn.commit()
    finally:
        conn.close()


def _insert_listing(path: str, listing_id: str, status: str, offer: dict) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "INSERT INTO listings(listing_id, status, offer_resource) VALUES (?, ?, ?)",
            (listing_id, status, json.dumps(offer)),
        )
        conn.commit()
    finally:
        conn.close()


def _exclusive_resource(
    resource_id: str = "host-1-bare-metal",
    *,
    available_units: int = 1,
    enabled: bool = True,
    machine_id: str = "bm-node-1",
) -> dict:
    return {
        "resource_id": resource_id,
        "available_units": available_units,
        "enabled": enabled,
        "attributes": {
            "allocation_mode": "exclusive",
            "physical_host_id": "host-physical-1",
            "machine_id": machine_id,
            "gpu_model": "H200",
        },
    }


def test_bare_metal_listing_candidates_from_capacity_snapshot():
    candidates = bare_metal_listing_candidates(
        [_exclusive_resource()],
        min_duration_seconds=3600,
        max_duration_seconds=7200,
        site={"region": "us-west"},
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["derivation_key"] == "bare-metal:bm-node-1"
    assert candidate["machine_id"] == "bm-node-1"
    assert candidate["physical_host_id"] == "host-physical-1"
    assert candidate["offer_resource"] == {
        "kind": "bare_metal.v1",
        "machine_id": "bm-node-1",
        "physical_host_id": "host-physical-1",
        "access_methods": ["ssh"],
        "min_duration_seconds": 3600,
        "max_duration_seconds": 7200,
        "site": {"region": "us-west"},
        "capabilities": {"gpu_model": "H200"},
    }


def test_open_bare_metal_listing_keys_ignore_vm_listings(tmp_path):
    db = str(tmp_path / "storefront.db")
    _init_db(db)
    _insert_listing(
        db,
        "bm-1",
        "open",
        {
            "kind": "bare_metal.v1",
            "machine_id": "bm-node-1",
            "physical_host_id": "host-physical-1",
        },
    )
    _insert_listing(
        db,
        "vm-1",
        "open",
        {"resource_id": "compute-1", "gpu_count": 1},
    )

    assert open_bare_metal_listing_keys(db) == {"bare-metal:bm-node-1"}


def test_stale_open_bare_metal_listing_ids_follow_snapshot_availability(tmp_path):
    db = str(tmp_path / "storefront.db")
    _init_db(db)
    offer = {
        "kind": "bare_metal.v1",
        "machine_id": "bm-node-1",
        "physical_host_id": "host-physical-1",
    }
    _insert_listing(db, "bm-1", "open", offer)

    assert stale_open_bare_metal_listing_ids(db, [_exclusive_resource()]) == []
    assert stale_open_bare_metal_listing_ids(
        db,
        [_exclusive_resource(available_units=0)],
    ) == ["bm-1"]


def test_closed_available_bare_metal_listing_ids_use_tracking_table(tmp_path):
    db = str(tmp_path / "storefront.db")
    _init_db(db)
    offer = {
        "kind": "bare_metal.v1",
        "machine_id": "bm-node-1",
        "physical_host_id": "host-physical-1",
    }
    _insert_listing(db, "bm-1", "closed", offer)
    candidate = bare_metal_listing_candidates([_exclusive_resource()])[0]
    record_derived_bare_metal_listing(
        db,
        listing_id="bm-1",
        listing=candidate["listing"],
        status="closed",
    )

    assert closed_available_bare_metal_listing_ids(
        db,
        [_exclusive_resource()],
    ) == ["bm-1"]


def test_record_derived_bare_metal_listing_upserts_by_machine_key(tmp_path):
    db = str(tmp_path / "storefront.db")
    _init_db(db)
    candidate = bare_metal_listing_candidates([_exclusive_resource()])[0]

    record_derived_bare_metal_listing(
        db,
        listing_id="bm-old",
        listing=candidate["listing"],
        status="closed",
    )
    record_derived_bare_metal_listing(
        db,
        listing_id="bm-new",
        listing=candidate["listing"],
        status="open",
    )

    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            "SELECT listing_id, status, derivation_key FROM derived_bare_metal_listings"
        ).fetchall()
    finally:
        conn.close()

    assert rows == [("bm-new", "open", "bare-metal:bm-node-1")]


def test_load_derived_bare_metal_listing_includes_storefront_status(tmp_path):
    db = str(tmp_path / "storefront.db")
    _init_db(db)
    candidate = bare_metal_listing_candidates([_exclusive_resource()])[0]
    _insert_listing(db, "bm-1", "closed", candidate["offer_resource"])
    record_derived_bare_metal_listing(
        db,
        listing_id="bm-1",
        listing=candidate["listing"],
        status="closed",
    )

    row = load_derived_bare_metal_listing(db, machine_id="bm-node-1")

    assert row == {
        "listing_id": "bm-1",
        "machine_id": "bm-node-1",
        "physical_host_id": "host-physical-1",
        "status": "closed",
        "derivation_key": "bare-metal:bm-node-1",
        "listing_status": "closed",
    }


def test_mark_derived_bare_metal_listings_closed(tmp_path):
    db = str(tmp_path / "storefront.db")
    _init_db(db)
    candidate = bare_metal_listing_candidates([_exclusive_resource()])[0]
    record_derived_bare_metal_listing(
        db,
        listing_id="bm-1",
        listing=candidate["listing"],
        status="open",
    )

    mark_derived_bare_metal_listings_closed(db, ["bm-1"])

    row = load_derived_bare_metal_listing(db, machine_id="bm-node-1")
    assert row is not None
    assert row["status"] == "closed"


def test_reopen_derived_bare_metal_listing_updates_local_row_and_callback(tmp_path):
    db = str(tmp_path / "storefront.db")
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            """
            CREATE TABLE listings (
                listing_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                paused INTEGER DEFAULT 1,
                updated_at TEXT,
                offer_resource TEXT,
                accepted_escrows TEXT,
                demands TEXT,
                max_duration_seconds INTEGER,
                seller TEXT
            )
            """
        )
        ensure_derived_bare_metal_listings_table(conn)
        conn.execute(
            "INSERT INTO listings(listing_id, status, offer_resource) VALUES (?, ?, ?)",
            ("bm-1", "closed", "{}"),
        )
        conn.commit()
    finally:
        conn.close()
    candidate = bare_metal_listing_candidates([_exclusive_resource()])[0]
    record_derived_bare_metal_listing(
        db,
        listing_id="bm-1",
        listing=candidate["listing"],
        status="closed",
    )
    calls: list[dict] = []

    def publish_existing_listing(**kwargs):
        calls.append(kwargs)
        return {"status": "published", "listing_id": kwargs["listing_id"]}

    result = reopen_derived_bare_metal_listing_if_present(
        db_path=db,
        base_url="http://seller.example",
        candidate=candidate,
        offer=candidate["offer_resource"],
        accepted_escrows=[{"chain_name": "base"}],
        demands=[{"arbiter": "0xabc"}],
        max_duration_seconds=3600,
        private_key="0xkey",
        publish_existing_listing=publish_existing_listing,
    )

    assert result == {"status": "published", "listing_id": "bm-1"}
    assert calls == [
        {
            "listing_id": "bm-1",
            "offer": candidate["offer_resource"],
            "accepted_escrows": [{"chain_name": "base"}],
            "demands": [{"arbiter": "0xabc"}],
            "max_duration_seconds": 3600,
            "storefront_url": "http://seller.example",
            "private_key": "0xkey",
        }
    ]
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            """
            SELECT status, paused, offer_resource, accepted_escrows, demands,
                   max_duration_seconds, seller
            FROM listings WHERE listing_id = ?
            """,
            ("bm-1",),
        ).fetchone()
    finally:
        conn.close()

    assert row == (
        "open",
        0,
        json.dumps(candidate["offer_resource"]),
        json.dumps([{"chain_name": "base"}]),
        json.dumps([{"arbiter": "0xabc"}]),
        3600,
        "http://seller.example",
    )
    tracked = load_derived_bare_metal_listing(db, machine_id="bm-node-1")
    assert tracked is not None
    assert tracked["status"] == "open"


def test_close_stale_bare_metal_listings_uses_callback_and_marks_closed(tmp_path):
    db = str(tmp_path / "storefront.db")
    _init_db(db)
    candidate = bare_metal_listing_candidates([_exclusive_resource()])[0]
    _insert_listing(db, "bm-1", "open", candidate["offer_resource"])
    record_derived_bare_metal_listing(
        db,
        listing_id="bm-1",
        listing=candidate["listing"],
        status="open",
    )
    closed = close_stale_bare_metal_listings(
        db_path=db,
        resources=[_exclusive_resource(available_units=0)],
        close_listing=lambda listing_id: {
            "status": "closed",
            "listing_id": listing_id,
        },
    )

    assert closed == ["bm-1"]
    tracked = load_derived_bare_metal_listing(db, machine_id="bm-node-1")
    assert tracked is not None
    assert tracked["status"] == "closed"
