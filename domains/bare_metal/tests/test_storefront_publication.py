from __future__ import annotations

import sqlite3

import pytest

from arkhai_bare_metal import (
    BareMetalResourceProjection,
    TrustedBareMetalProjection,
)
from arkhai_bare_metal.storefront_publication import (
    bare_metal_listing_candidates,
    close_stale_bare_metal_listings,
    load_derived_bare_metal_listing,
    open_bare_metal_listing_keys,
    record_derived_bare_metal_listing,
    stale_open_bare_metal_listing_ids,
)


def _projection(
    *,
    site_id="site-a",
    resource_id="resource-1",
    machine_id="machine-1",
    available=True,
    complete=True,
):
    resources = []
    if complete:
        resources = [
            BareMetalResourceProjection(
                physical_resource_id=resource_id,
                physical_host_id=f"physical-{resource_id}",
                machine_id=machine_id,
                available=available,
                allocation_mode="exclusive",
                access_methods=["ssh"],
                capacity={"gpu_count": 8},
                capabilities={"gpu_model": "H200"},
            ),
        ]
    return TrustedBareMetalProjection(
        site_id=site_id,
        revision=1,
        digest=f"{site_id}-generation",
        complete=complete,
        resources=resources,
    )


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "storefront.db"
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE listings (
              listing_id TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              paused INTEGER NOT NULL DEFAULT 0,
              updated_at TEXT,
              offer_resource TEXT,
              accepted_escrows TEXT,
              demands TEXT,
              max_duration_seconds INTEGER,
              seller TEXT
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
            """,
        )
        conn.commit()
    finally:
        conn.close()
    return str(path)


def _insert_open_listing(db, candidate, listing_id="listing-1"):
    conn = sqlite3.connect(db)
    try:
        conn.execute(
            "INSERT INTO listings(listing_id, status) VALUES (?, 'open')",
            (listing_id,),
        )
        conn.commit()
    finally:
        conn.close()
    record_derived_bare_metal_listing(
        db,
        listing_id=listing_id,
        candidate=candidate,
    )


def test_candidates_preserve_projection_provenance_and_site_scoped_key():
    first = bare_metal_listing_candidates([_projection(site_id="site-a")])[0]
    second = bare_metal_listing_candidates([_projection(site_id="site-b")])[0]

    assert first["site_id"] == "site-a"
    assert first["physical_resource_id"] == "resource-1"
    assert first["machine_id"] == "machine-1"
    assert first["offer_resource"]["capabilities"] == {
        "gpu_count": 8,
        "gpu_model": "H200",
    }
    assert first["derivation_key"] != second["derivation_key"]


def test_record_and_load_use_migrated_schema(db):
    candidate = bare_metal_listing_candidates([_projection()])[0]

    _insert_open_listing(db, candidate)

    loaded = load_derived_bare_metal_listing(
        db,
        derivation_key=candidate["derivation_key"],
    )
    assert loaded["site_id"] == "site-a"
    assert loaded["physical_resource_id"] == "resource-1"
    assert open_bare_metal_listing_keys(db) == {candidate["derivation_key"]}


def test_record_fails_when_migration_has_not_run(tmp_path):
    path = tmp_path / "unmigrated.db"
    candidate = bare_metal_listing_candidates([_projection()])[0]

    with pytest.raises(sqlite3.OperationalError):
        record_derived_bare_metal_listing(
            str(path),
            listing_id="listing-1",
            candidate=candidate,
        )


def test_unavailable_generation_closes_nothing(db):
    candidate = bare_metal_listing_candidates([_projection()])[0]
    _insert_open_listing(db, candidate)

    assert stale_open_bare_metal_listing_ids(
        db,
        [_projection(complete=False)],
    ) == []


def test_authoritative_empty_generation_closes_site_listings(db):
    candidate = bare_metal_listing_candidates([_projection()])[0]
    _insert_open_listing(db, candidate)
    empty = TrustedBareMetalProjection(
        site_id="site-a",
        revision=2,
        digest="empty",
        complete=True,
        resources=[],
    )
    calls = []

    closed = close_stale_bare_metal_listings(
        db_path=db,
        projections=[empty],
        close_listing=lambda listing_id: calls.append(listing_id) or {"status": "closed"},
    )

    assert closed == ["listing-1"]
    assert calls == ["listing-1"]


def test_complete_generation_does_not_close_other_trusted_site(db):
    candidate = bare_metal_listing_candidates([_projection(site_id="site-b")])[0]
    _insert_open_listing(db, candidate)
    empty_site_a = TrustedBareMetalProjection(
        site_id="site-a",
        revision=2,
        digest="empty",
        complete=True,
        resources=[],
    )

    assert stale_open_bare_metal_listing_ids(db, [empty_site_a]) == []
