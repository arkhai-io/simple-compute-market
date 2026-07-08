from __future__ import annotations

import json
import sqlite3

from market_storefront.services.bare_metal_publication import (
    bare_metal_listing_candidates,
    closed_available_bare_metal_listing_ids,
    ensure_derived_bare_metal_listings_table,
    load_derived_bare_metal_listing,
    mark_derived_bare_metal_listings_closed,
    open_bare_metal_listing_keys,
    record_derived_bare_metal_listing,
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
