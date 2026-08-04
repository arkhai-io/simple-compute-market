from __future__ import annotations

import sqlite3

from arkhai_bare_metal import (
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
)
from arkhai_bare_metal.storefront_adapter import (
    available_bare_metal_listing_candidates,
    bare_metal_candidate_skip_keys,
    bare_metal_publication_adapter,
)
from arkhai_bare_metal.storefront_publication import (
    bare_metal_listing_candidates,
    record_derived_bare_metal_listing,
)
from arkhai_bare_metal.publication import bare_metal_listing_key


def _projection(*, complete=True, resources=True):
    projected = []
    if complete and resources:
        projected = [
            BareMetalResourceProjection(
                physical_resource_id="resource-1",
                physical_host_id="physical-host-1",
                machine_id="machine-1",
                available=True,
                allocation_mode="exclusive",
                access_methods=["ssh"],
                capacity={"gpu_count": 8},
            ),
        ]
    return TrustedBareMetalProjection(
        site_id="site-a",
        revision=1,
        digest="generation-1",
        complete=complete,
        resources=projected,
    )


def test_adapter_returns_exact_projection_candidate():
    source = bare_metal_publication_adapter(
        projection_snapshot=lambda: [_projection()],
        close_listing=lambda *_args: {"status": "closed"},
        publish_existing_listing=lambda **kwargs: kwargs,
    )

    candidates = source.available_candidates("unused.db")

    assert source.name == "bare_metal"
    assert len(candidates) == 1
    assert candidates[0]["site_id"] == "site-a"
    assert candidates[0]["physical_resource_id"] == "resource-1"
    assert source.offer_resource(candidates[0]) == candidates[0]["offer_resource"]
    assert bare_metal_candidate_skip_keys(candidates[0]) == {
        bare_metal_listing_key(site_id="site-a", physical_resource_id="resource-1"),
    }


def test_unavailable_projection_snapshot_publishes_nothing():
    assert available_bare_metal_listing_candidates(
        "unused.db",
        projection_snapshot=lambda: None,
    ) == []
    assert available_bare_metal_listing_candidates(
        "unused.db",
        projection_snapshot=lambda: [_projection(complete=False)],
    ) == []


def test_authoritative_empty_projection_closes_tracked_listing(tmp_path):
    path = str(tmp_path / "storefront.db")
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE listings (
              listing_id TEXT PRIMARY KEY,
              status TEXT NOT NULL
            );
            CREATE TABLE derived_bare_metal_listings (
              listing_id TEXT PRIMARY KEY,
              site_id TEXT NOT NULL,
              physical_resource_id TEXT NOT NULL,
              machine_id TEXT NOT NULL,
              physical_host_id TEXT NOT NULL,
              status TEXT NOT NULL,
              derivation_key TEXT NOT NULL UNIQUE,
              last_reconciled_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO listings(listing_id, status)
            VALUES ('listing-1', 'open');
            """,
        )
        conn.commit()
    finally:
        conn.close()
    candidate = bare_metal_listing_candidates([_projection()])[0]
    record_derived_bare_metal_listing(
        path,
        listing_id="listing-1",
        candidate=candidate,
    )
    calls = []
    source = bare_metal_publication_adapter(
        projection_snapshot=lambda: [_projection(resources=False)],
        close_listing=lambda base_url, listing_id, private_key: (
            calls.append((base_url, listing_id, private_key))
            or {"status": "closed"}
        ),
        publish_existing_listing=lambda **kwargs: kwargs,
    )

    closed = source.close_stale(path, "https://seller", "private-key")

    assert closed == ["listing-1"]
    assert calls == [("https://seller", "listing-1", "private-key")]
