from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

pytest.importorskip("core_storefront.publication_sources")

from core_storefront.publication_runner import publish_round  # noqa: E402
from arkhai_bare_metal.storefront_adapter import (  # noqa: E402
    bare_metal_candidate_skip_keys,
    bare_metal_publication_adapter,
    close_stale_bare_metal_publications,
    open_bare_metal_publication_keys,
)
from arkhai_bare_metal.storefront_publication import (  # noqa: E402
    bare_metal_listing_candidates,
    record_derived_bare_metal_listing,
)


def _db(path: str) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE listings (
              listing_id TEXT PRIMARY KEY,
              offer_resource TEXT,
              accepted_escrows TEXT,
              demands TEXT,
              max_duration_seconds INTEGER,
              seller TEXT,
              status TEXT,
              paused INTEGER DEFAULT 0,
              updated_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def _resource(*, available_units: int = 1) -> dict[str, Any]:
    return {
        "resource_id": "host-1-bare-metal",
        "total_units": 1,
        "available_units": available_units,
        "enabled": True,
        "status": "available",
        "attributes": {
            "allocation_mode": "exclusive",
            "machine_id": "bm-node-1",
            "physical_host_id": "host-physical-1",
            "gpu_model": "H200",
            "gpu_count": 8,
            "region": "California, US",
            "access_methods": ["ssh"],
        },
    }


def test_bare_metal_adapter_derives_candidates_from_capacity_snapshot(tmp_path):
    db_path = str(tmp_path / "storefront.db")
    _db(db_path)
    adapter = bare_metal_publication_adapter(
        capacity_snapshot=lambda: [_resource()],
        close_listing=lambda *args: {"status": "closed"},
        publish_existing_listing=lambda **kwargs: {"status": "published"},
    )

    candidates = adapter.available_candidates(db_path)

    assert adapter.name == "bare_metal"
    assert len(candidates) == 1
    assert adapter.offer_resource(candidates[0])["kind"] == "bare_metal.v1"
    assert adapter.pricing_resource(
        candidates[0],
        {"kind": "bare_metal.v1"},
    ) == {"kind": "bare_metal.v1"}
    assert adapter.skip_keys(candidates[0]) == {
        "bare-metal:bm-node-1",
        "bm-node-1",
    }


def test_open_keys_and_close_stale_publications_use_bare_metal_tracking(tmp_path):
    db_path = str(tmp_path / "storefront.db")
    _db(db_path)
    candidate = bare_metal_listing_candidates([_resource()])[0]
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO listings(listing_id, offer_resource, status)
            VALUES (?, ?, 'open')
            """,
            (
                "bm-listing-1",
                json.dumps(candidate["offer_resource"]),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    record_derived_bare_metal_listing(
        db_path,
        listing_id="bm-listing-1",
        listing=candidate["listing"],
    )
    closed: list[tuple[str, str, str | None]] = []

    assert open_bare_metal_publication_keys(db_path) == {"bare-metal:bm-node-1"}

    result = close_stale_bare_metal_publications(
        db_path=db_path,
        base_url="http://storefront",
        private_key="0xkey",
        capacity_snapshot=lambda: [_resource(available_units=0)],
        close_listing=lambda *args: closed.append(args) or {"status": "closed"},
    )

    assert result == ["bm-listing-1"]
    assert closed == [("http://storefront", "bm-listing-1", "0xkey")]


def test_candidate_skip_keys_ignore_absent_values() -> None:
    assert bare_metal_candidate_skip_keys({"machine_id": "bm-node-1"}) == {
        "bm-node-1",
    }


def test_bare_metal_adapter_runs_through_core_publication_runner(tmp_path) -> None:
    db_path = str(tmp_path / "storefront.db")
    _db(db_path)
    adapter = bare_metal_publication_adapter(
        capacity_snapshot=lambda: [_resource()],
        close_listing=lambda *args: {"status": "closed"},
        publish_existing_listing=lambda **kwargs: {"status": "published"},
    )

    def publish_offer(
        offer: dict[str, Any],
        _escrows: list[dict[str, Any]],
        _demands: list[dict[str, Any]],
        _duration: int | None,
    ) -> dict[str, Any]:
        listing_id = f"listing-{offer['machine_id']}"
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "INSERT INTO listings(listing_id, offer_resource, status) VALUES (?, ?, 'open')",
                (listing_id, json.dumps(offer)),
            )
            conn.commit()
        finally:
            conn.close()
        return {"status": "published", "listing_id": listing_id}

    published, failed, skipped = publish_round(
        [adapter],
        db_path=db_path,
        base_url="http://storefront",
        private_key=None,
        build_payload=lambda _source, _candidate, _offer: ([{"escrow": "e"}], [{"demand": "d"}], None),
        publish_offer=publish_offer,
    )

    assert failed == []
    assert skipped == []
    assert published[0]["response"]["listing_id"] == "listing-bm-node-1"
    assert open_bare_metal_publication_keys(db_path) == {"bare-metal:bm-node-1"}
