"""Unit tests for domains.vms.listings.reconciler.

External boundary: a real sqlite3 file DB with a minimal hand-built
schema (not the full SQLiteClient migration chain) -- reconciler.py is
itself plain synchronous sqlite3 code with no async dependencies, so a
minimal schema exercising exactly the tables it reads/writes is the
right level, matching test_compute_allocations.py's precedent.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from market_identity import Identity

from domains.vms.listings.pricing_resolution import GpuPricingFields
from domains.vms.listings.reconciler import (
    PoolHintResolutionSettings,
    _accumulate_capacity_pool_member,
    _fungible_availability_from_buckets,
    _member_available_units,
    _project_legacy_resource_row,
    _projected_pool_rows,
    _projected_resource_usage,
    available_compute_slices,
    closed_available_listing_ids,
    current_available_resource_keys,
    ensure_derived_compute_listings_table,
    listing_pool_key,
    listing_resource_key,
    load_derived_listing_for_slice,
    mark_derived_listings_closed,
    mark_derived_listings_open,
    open_listing_resource_keys,
    pool_id_for_listing,
    record_derived_listing,
    reopen_local_derived_listing,
    site_id_for_listing,
    stale_open_listing_ids,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path) -> str:
    path = str(tmp_path / "reconciler_test.db")
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            CREATE TABLE listings (
              listing_id TEXT PRIMARY KEY,
              status TEXT NOT NULL,
              offer_resource TEXT,
              accepted_escrows TEXT,
              demands TEXT,
              max_duration_seconds INTEGER,
              seller TEXT,
              paused INTEGER,
              updated_at TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE compute_capacity_pools (
              pool_id TEXT PRIMARY KEY,
              resource_type TEXT,
              gpu_model TEXT,
              region TEXT,
              sla REAL,
              total_gpu_count INTEGER,
              status TEXT,
              min_price TEXT,
              token TEXT,
              max_duration_seconds INTEGER,
              accepted_escrows TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE compute_pool_members (
              pool_id TEXT,
              resource_id TEXT,
              gpu_count INTEGER,
              status TEXT,
              attributes TEXT,
              site TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    return path


def _seed_fungible_pool(
    db_path: str,
    *,
    pool_id: str = "gpu-pool",
    member_gpu_counts: tuple[int, ...] = (2, 2),
    pool_status: str = "active",
    member_status: str = "active",
):
    """A pool with more than one member, so available_compute_slices
    treats it as genuinely fungible (pool-keyed) rather than collapsing
    to a single-resource-keyed pool -- see is_fungible_pool."""
    total = sum(member_gpu_counts)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO compute_capacity_pools(
              pool_id, resource_type, gpu_model, region, sla, total_gpu_count,
              status, min_price, token, max_duration_seconds, accepted_escrows
            ) VALUES (?, 'compute.gpu', 'H100', 'us-east', 99.9, ?, ?, '10', '0xtoken', 3600, '[]')
            """,
            (pool_id, total, pool_status),
        )
        for i, count in enumerate(member_gpu_counts):
            conn.execute(
                """
                INSERT INTO compute_pool_members(
                  pool_id, resource_id, gpu_count, status, attributes, site
                ) VALUES (?, ?, ?, ?, '{}', NULL)
                """,
                (pool_id, f"resource-{i}", count, member_status),
            )
        conn.commit()
    finally:
        conn.close()


def _seed_pool(
    db_path: str,
    *,
    pool_id: str = "gpu-pool",
    resource_id: str = "resource-1",
    gpu_count: int = 4,
    pool_status: str = "active",
    member_status: str = "active",
):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            INSERT INTO compute_capacity_pools(
              pool_id, resource_type, gpu_model, region, sla, total_gpu_count,
              status, min_price, token, max_duration_seconds, accepted_escrows
            ) VALUES (?, 'compute.gpu', 'H100', 'us-east', 99.9, ?, ?, '10', '0xtoken', 3600, '[]')
            """,
            (pool_id, gpu_count, pool_status),
        )
        conn.execute(
            """
            INSERT INTO compute_pool_members(
              pool_id, resource_id, gpu_count, status, attributes, site
            ) VALUES (?, ?, ?, ?, '{}', NULL)
            """,
            (pool_id, resource_id, gpu_count, member_status),
        )
        conn.commit()
    finally:
        conn.close()


def _seed_listing(
    db_path: str,
    *,
    listing_id: str,
    status: str = "open",
    pool_id: str | None = "gpu-pool",
    resource_id: str | None = None,
    gpu_count: int = 2,
):
    offer = {"gpu_count": gpu_count}
    if pool_id:
        offer["pool_id"] = pool_id
    if resource_id:
        offer["resource_id"] = resource_id
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO listings(listing_id, status, offer_resource) VALUES (?, ?, ?)",
            (listing_id, status, json.dumps(offer)),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# listing_pool_key / listing_resource_key -- validation
# ---------------------------------------------------------------------------

class TestKeyValidation:
    def test_pool_key_requires_nonempty_site_id(self):
        with pytest.raises(ValueError):
            listing_pool_key("", "pool-a", 2)

    def test_resource_key_requires_nonempty_site_id(self):
        with pytest.raises(ValueError):
            listing_resource_key("   ", "resource-a", 2)

    def test_different_sites_produce_different_keys_for_the_same_pool(self):
        assert listing_pool_key("site-a", "pool-a", 2) != listing_pool_key("site-b", "pool-a", 2)

    def test_same_site_and_pool_are_deterministic(self):
        assert listing_pool_key("site-a", "pool-a", 2) == listing_pool_key("site-a", "pool-a", 2)

    def test_no_collision_when_a_colon_shifts_the_field_boundary(self):
        """site_id/pool_id are operator-chosen strings with no character
        restrictions -- a naive colon-delimited join would let
        (site_id='a', pool_id='b:c') and (site_id='a:b', pool_id='c')
        produce an identical string. The length-prefixed encoding must
        not collide here."""
        assert listing_pool_key("a", "b:c", 2) != listing_pool_key("a:b", "c", 2)
        assert listing_resource_key("a", "b:c", 2) != listing_resource_key("a:b", "c", 2)

    def test_no_collision_with_digit_and_colon_adversarial_inputs(self):
        """A field value that looks like a length prefix itself (e.g.
        "3:xyz") must not be confusable with the real encoding."""
        assert listing_pool_key("1:a", "b", 2) != listing_pool_key("1", "a:b", 2)

    def test_no_collision_across_many_boundary_shifts(self):
        """Broader sweep: many different (site_id, pool_id) splits of the
        same underlying characters must all produce distinct keys."""
        pairs = [
            ("a", "bcde"), ("ab", "cde"), ("abc", "de"), ("abcd", "e"),
        ]
        keys = {listing_pool_key(site, pool, 2) for site, pool in pairs}
        assert len(keys) == len(pairs)


# ---------------------------------------------------------------------------
# available_compute_slices
# ---------------------------------------------------------------------------

class TestAvailableComputeSlices:
    def test_every_slice_is_tagged_with_home_site(self, db_path):
        _seed_pool(db_path)
        slices = available_compute_slices(db_path, home_site="site-a")
        assert slices
        assert all(row["site_id"] == "site-a" for row in slices)

    def test_resource_key_is_site_scoped(self, db_path):
        _seed_pool(db_path, gpu_count=1)
        slices = available_compute_slices(db_path, home_site="site-a")
        assert slices[0]["resource_key"] == listing_resource_key(
            "site-a", "resource-1", 1,
        )

    def test_different_home_site_produces_different_keys_for_identical_data(self, db_path):
        _seed_pool(db_path, gpu_count=1)
        keys_a = {r["resource_key"] for r in available_compute_slices(db_path, home_site="site-a")}
        keys_b = {r["resource_key"] for r in available_compute_slices(db_path, home_site="site-b")}
        assert keys_a and keys_b
        assert keys_a.isdisjoint(keys_b)

    def test_none_projection_preserves_local_table_behavior(self, db_path):
        """The default (omitted/None/empty site_pool_projection) must be
        byte-identical to today's local-table-only behavior."""
        _seed_pool(db_path, gpu_count=2)
        without_arg = available_compute_slices(db_path, home_site="site-a")
        with_none = available_compute_slices(
            db_path, home_site="site-a", site_pool_projection=None,
        )
        with_empty = available_compute_slices(
            db_path, home_site="site-a", site_pool_projection={},
        )
        assert without_arg == with_none == with_empty

    def test_a_site_mapped_to_an_authoritative_empty_projection_does_not_fall_back(
        self, db_path,
    ):
        """The downstream half of the site_pool_projection() None-vs-[]
        fix: {"site-a": []} is a non-empty mapping (one key), so it must
        take the projection path and correctly contribute zero rows for
        that site -- not be treated the same as {} (no site data at
        all), which would incorrectly fall back to stale local data even
        though the authoritative answer is "this site has zero pools
        right now"."""
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)  # local data exists
        slices = available_compute_slices(
            db_path, home_site="site-a", site_pool_projection={"site-a": []},
        )
        assert slices == []

    def test_projection_sourced_pool_uses_local_pricing_for_home_site(self, db_path):
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)  # local pricing row
        projection = {
            "site-a": [
                {
                    "resource_pool_id": "gpu-pool",
                    "resources": [
                        {
                            "physical_resource_id": "res-1",
                            "capacity": {"gpu_count": 8},
                            "attributes": {"gpu_model": "H100"},
                            "enabled": True,
                        },
                    ],
                },
            ],
        }
        slices = available_compute_slices(
            db_path, home_site="site-a", site_pool_projection=projection,
        )
        assert slices
        assert all(row["site_id"] == "site-a" for row in slices)
        # Structure/GPU model from the projection (8, not the local
        # table's seeded 4), pricing from the local table.
        assert max(row["gpu_count"] for row in slices) == 8
        assert all(row["gpu_model"] == "H100" for row in slices)
        assert all(row["min_price"] == "10" for row in slices)  # _seed_pool's fixed price

    def test_projection_pool_for_non_home_site_never_uses_another_sites_local_row(
        self, db_path,
    ):
        """The core safety property: a non-home-site pool must never pick
        up another site's local pricing row, even when the pool_id
        happens to match -- compute_capacity_pools is not site-scoped,
        so this is the only thing preventing a cross-site mix-up. It
        still publishes (priceless, since it has no hint/config default
        of its own either) -- a missing storefront override is not a
        reason to suppress the pool."""
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)
        projection = {
            "site-b": [  # not home_site
                {
                    "resource_pool_id": "gpu-pool",  # same pool_id as the local row
                    "resources": [
                        {
                            "physical_resource_id": "res-1",
                            "capacity": {"gpu_count": 8},
                            "attributes": {},
                            "enabled": True,
                        },
                    ],
                },
            ],
        }
        slices = available_compute_slices(
            db_path, home_site="site-a", site_pool_projection=projection,
        )
        assert slices
        assert all(s.get("min_price") is None for s in slices)
        assert all(s.get("region") is None for s in slices)

    def test_projection_pool_with_no_local_pricing_row_publishes_priceless(
        self, db_path,
    ):
        """A home-site pool with no matching local compute_capacity_pools
        row has no storefront-override price -- it still publishes,
        priceless, rather than being excluded."""
        projection = {
            "site-a": [
                {
                    "resource_pool_id": "unpriced-pool",
                    "resources": [
                        {
                            "physical_resource_id": "res-1",
                            "capacity": {"gpu_count": 4},
                            "attributes": {},
                            "enabled": True,
                        },
                    ],
                },
            ],
        }
        slices = available_compute_slices(
            db_path, home_site="site-a", site_pool_projection=projection,
        )
        assert slices
        assert all(s.get("min_price") is None for s in slices)

    def test_projection_disabled_resource_excluded_from_capacity(self, db_path):
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)
        projection = {
            "site-a": [
                {
                    "resource_pool_id": "gpu-pool",
                    "resources": [
                        {
                            "physical_resource_id": "res-1",
                            "capacity": {"gpu_count": 8},
                            "attributes": {},
                            "enabled": False,
                        },
                    ],
                },
            ],
        }
        slices = available_compute_slices(
            db_path, home_site="site-a", site_pool_projection=projection,
        )
        assert slices == []

    def test_multiple_sites_both_publish_but_only_home_site_gets_local_pricing(
        self, db_path,
    ):
        """Corrected from an earlier "only home_site pool is published"
        expectation: both sites' pools now publish (a missing storefront
        override is not a reason to suppress a pool), but only the
        home-site pool's local `compute_capacity_pools` row is ever
        consulted -- site-b's pool has no hint/config default either, so
        it publishes priceless, not with site-a's price."""
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)
        projection = {
            "site-a": [{
                "resource_pool_id": "gpu-pool",
                "resources": [{
                    "physical_resource_id": "res-1",
                    "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                }],
            }],
            "site-b": [{
                "resource_pool_id": "other-pool",
                "resources": [{
                    "physical_resource_id": "res-2",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "A100"},
                    "enabled": True,
                }],
            }],
        }
        slices = available_compute_slices(
            db_path, home_site="site-a", site_pool_projection=projection,
        )
        by_site = {}
        for row in slices:
            by_site.setdefault(row["site_id"], []).append(row)
        assert set(by_site) == {"site-a", "site-b"}
        assert all(row["min_price"] == "10" for row in by_site["site-a"])
        assert all(row["min_price"] is None for row in by_site["site-b"])

    def test_resource_keys_are_identical_regardless_of_hint_resolution(self, db_path):
        """The invariant `current_available_resource_keys`/
        `stale_open_listing_ids`/`closed_available_listing_ids` all rely
        on without any of them threading `hint_resolution` through:
        `resource_key`/`legacy_resource_key` never depend on resolved
        region/SLA/pricing, however different `hint_resolution` makes
        those fields. Capacity-delta reconciliation compares structural
        derivation keys and availability; it never recomputes or
        republishes commercial listing terms -- this proves that holds,
        rather than only asserting it in a comment. No local
        `compute_capacity_pools` row on purpose -- a storefront override
        would win regardless of `hint_resolution` and this test would
        prove nothing about the tiers that actually vary."""
        projection = {
            "site-a": [{
                "resource_pool_id": "gpu-pool",
                "resources": [{
                    "physical_resource_id": "res-1",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                }],
            }],
        }
        default_rows = available_compute_slices(
            db_path, home_site="site-a", site_pool_projection=projection,
        )
        varied_rows = available_compute_slices(
            db_path, home_site="site-a", site_pool_projection=projection,
            hint_resolution=PoolHintResolutionSettings(
                accept_pool_declared_sla=True, default_sla=7.0,
                gpu_pricing_defaults_by_model={
                    "H100": GpuPricingFields(min_price="0.01"),
                },
            ),
        )
        default_keys = {r["resource_key"] for r in default_rows}
        varied_keys = {r["resource_key"] for r in varied_rows}
        assert default_keys == varied_keys
        assert default_keys  # not vacuously true
        # Confirm the two runs actually resolved *different* commercial
        # values -- otherwise this test wouldn't be exercising anything.
        assert {r["sla"] for r in default_rows} != {r["sla"] for r in varied_rows}


# ---------------------------------------------------------------------------
# site_id_for_listing
# ---------------------------------------------------------------------------

class TestSiteIdForListing:
    def test_returns_none_when_no_derived_compute_listings_table(self, db_path):
        assert site_id_for_listing(db_path, "listing-1") is None

    def test_returns_none_when_listing_is_unmapped(self, db_path):
        record_derived_listing(
            db_path, listing_id="listing-other", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        assert site_id_for_listing(db_path, "listing-1") is None

    def test_returns_the_mapped_site(self, db_path):
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        assert site_id_for_listing(db_path, "listing-1") == "site-a"


# ---------------------------------------------------------------------------
# record_derived_listing / load_derived_listing_for_slice round trip
# ---------------------------------------------------------------------------

class TestRecordAndLoad:
    def test_round_trips_site_id(self, db_path):
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        loaded = load_derived_listing_for_slice(
            db_path, site_id="site-a", pool_id="gpu-pool", gpu_count=2,
        )
        assert loaded is not None
        assert loaded["site_id"] == "site-a"
        assert loaded["listing_id"] == "listing-1"

    def test_same_pool_different_site_does_not_match(self, db_path):
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        loaded = load_derived_listing_for_slice(
            db_path, site_id="site-b", pool_id="gpu-pool", gpu_count=2,
        )
        assert loaded is None

    def test_two_specific_resource_listings_from_the_same_pool_coexist(
        self, db_path,
    ):
        """Regression for the `use_pool_key` collision bug: two
        specific_resource candidates from the same multi-member pool, at
        the same gpu_count, must persist as two independent rows -- not
        collapse onto one shared pool-keyed derivation_key and silently
        overwrite each other."""
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id="res-1", gpu_count=4,
        )
        record_derived_listing(
            db_path, listing_id="listing-2", site_id="site-a",
            pool_id="gpu-pool", resource_id="res-2", gpu_count=4,
        )
        loaded_1 = load_derived_listing_for_slice(
            db_path, site_id="site-a", resource_id="res-1", gpu_count=4,
        )
        loaded_2 = load_derived_listing_for_slice(
            db_path, site_id="site-a", resource_id="res-2", gpu_count=4,
        )
        assert loaded_1 is not None
        assert loaded_2 is not None
        assert loaded_1["listing_id"] == "listing-1"
        assert loaded_2["listing_id"] == "listing-2"

    def test_fungible_listing_still_uses_the_pool_key(self, db_path):
        """The fix must not disturb the fungible case: a candidate with
        no resource_id still derives its key from pool_id."""
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=4,
        )
        loaded = load_derived_listing_for_slice(
            db_path, site_id="site-a", pool_id="gpu-pool", gpu_count=4,
        )
        assert loaded is not None
        assert loaded["listing_id"] == "listing-1"


# ---------------------------------------------------------------------------
# pool_id_for_listing
# ---------------------------------------------------------------------------

class TestPoolIdForListing:
    def test_returns_mapped_pool_id(self, db_path):
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        assert pool_id_for_listing(db_path, "listing-1") == "gpu-pool"

    def test_none_for_unmapped_listing(self, db_path):
        ensure_derived_compute_listings_table(sqlite3.connect(db_path))
        assert pool_id_for_listing(db_path, "listing-none") is None

    def test_returns_backfilled_pool_id_for_specific_resource_only_mapping(
        self, db_path,
    ):
        """No way to distinguish this from a genuine pool at this table
        alone -- see pool_id_for_listing's own docstring. Downstream
        lookups against the live projection cache are the actual guard
        against a false match, not this function."""
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id=None, resource_id="res-1", gpu_count=4,
        )
        assert pool_id_for_listing(db_path, "listing-1") == "res-1"

    def test_returns_the_real_pool_id_for_a_specific_resource_within_a_pool(
        self, db_path,
    ):
        """A multi-member pool's specific_resource candidate carries both
        a real pool_id and a real resource_id -- this must return the
        pool, not the resource."""
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id="res-1", gpu_count=4,
        )
        assert pool_id_for_listing(db_path, "listing-1") == "gpu-pool"


# ---------------------------------------------------------------------------
# open_listing_resource_keys -- unmapped listings excluded, not guessed
# ---------------------------------------------------------------------------

class TestOpenListingResourceKeys:
    def test_mapped_open_listing_is_covered(self, db_path):
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        covered = open_listing_resource_keys(
            db_path, home_site="site-a", configured_site_count=1,
        )
        assert listing_pool_key("site-a", "gpu-pool", 2) in covered

    def test_unmapped_listing_falls_back_to_home_site_when_only_one_site_configured(
        self, db_path,
    ):
        """With exactly one site currently configured, an unmapped
        listing's site is not ambiguous -- home_site is the only
        possible answer, not a guess."""
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        covered = open_listing_resource_keys(
            db_path, home_site="site-a", configured_site_count=1,
        )
        assert listing_pool_key("site-a", "gpu-pool", 2) in covered

    def test_unmapped_listing_is_excluded_when_multiple_sites_configured(self, db_path):
        """The moment more than one site is configured, defaulting an
        unmapped listing to home_site would be a genuine guess -- it
        must be excluded instead, not silently attributed anywhere."""
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        covered = open_listing_resource_keys(
            db_path, home_site="site-a", configured_site_count=2,
        )
        assert covered == set()

    def test_mapped_listing_is_covered_regardless_of_configured_site_count(self, db_path):
        """A listing's own recorded mapping always takes precedence over
        the fallback question entirely -- multi-site configuration must
        not affect an already-mapped listing."""
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-b",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        covered = open_listing_resource_keys(
            db_path, home_site="site-a", configured_site_count=3,
        )
        assert listing_pool_key("site-b", "gpu-pool", 2) in covered

    def test_no_derived_compute_listings_table_at_all(self, db_path):
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        covered = open_listing_resource_keys(
            db_path, home_site="site-a", configured_site_count=1,
        )
        assert listing_pool_key("site-a", "gpu-pool", 2) in covered


# ---------------------------------------------------------------------------
# stale_open_listing_ids -- unmapped listings' fallback is gated on the
# caller's actual current site count, never assumed
# ---------------------------------------------------------------------------

class TestStaleOpenListingIds:
    def test_listing_that_still_fits_is_not_stale(self, db_path):
        _seed_fungible_pool(db_path, member_gpu_counts=(4, 4))
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_site_count=1)
        assert stale == []

    def test_listing_whose_slice_no_longer_fits_is_stale(self, db_path):
        _seed_pool(db_path, gpu_count=1)  # only 1 GPU available
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_site_count=1)
        assert stale == ["listing-1"]

    def test_unmapped_listing_falls_back_to_home_site_when_only_one_site_configured(
        self, db_path,
    ):
        """With exactly one site configured, an unmapped listing's site
        is exact, not a guess -- it participates in staleness evaluation
        like any mapped listing would."""
        _seed_pool(db_path, gpu_count=1)  # too small for the 2-GPU listing
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        # deliberately no record_derived_listing call -- listing-1 is unmapped
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_site_count=1)
        assert stale == ["listing-1"]

    def test_unmapped_listing_is_skipped_when_multiple_sites_configured(self, db_path):
        """The same unmapped listing, evaluated with more than one site
        configured, cannot be attributed to any one site -- it is
        skipped rather than defaulted to home_site as a guess. This is
        not a permanent single-site assumption: it is decided fresh
        from configured_site_count on every call."""
        _seed_pool(db_path, gpu_count=1)
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_site_count=2)
        assert stale == []

    def test_listing_mapped_to_a_different_site_is_evaluated_against_that_site(self, db_path):
        _seed_pool(db_path, gpu_count=4)
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        # Mapped to site-b, but only site-a has capacity data seeded.
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-b",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_site_count=1)
        # available_compute_slices only ever tags rows with home_site
        # currently, so a site-b-mapped listing can never match -- it
        # goes stale, not silently treated as fine.
        assert stale == ["listing-1"]

    def test_mapped_listing_evaluated_against_its_own_site_regardless_of_site_count(
        self, db_path,
    ):
        """A listing's own mapping takes precedence over the fallback
        question entirely -- configured_site_count must not change how
        an already-mapped listing is evaluated."""
        _seed_fungible_pool(db_path, member_gpu_counts=(4, 4))
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_site_count=5)
        assert stale == []


# ---------------------------------------------------------------------------
# closed_available_listing_ids
# ---------------------------------------------------------------------------

class TestClosedAvailableListingIds:
    def test_closed_listing_that_now_fits_is_reopenable(self, db_path):
        _seed_fungible_pool(db_path, member_gpu_counts=(4, 4))
        _seed_listing(db_path, listing_id="listing-1", status="closed", pool_id="gpu-pool", gpu_count=2)
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2, status="closed",
        )
        reopenable = closed_available_listing_ids(db_path, home_site="site-a")
        assert reopenable == ["listing-1"]

    def test_empty_when_nothing_is_available(self, db_path):
        assert closed_available_listing_ids(db_path, home_site="site-a") == []


# ---------------------------------------------------------------------------
# reopen_local_derived_listing
# ---------------------------------------------------------------------------

class TestReopenLocalDerivedListing:
    def test_reopens_the_listing_and_the_mapping_row(self, db_path):
        _seed_listing(db_path, listing_id="listing-1", status="closed", pool_id="gpu-pool", gpu_count=2)
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2, status="closed",
        )
        reopen_local_derived_listing(
            db_path,
            listing_id="listing-1",
            site_id="site-a",
            gpu_count=2,
            offer_resource={"pool_id": "gpu-pool", "gpu_count": 2},
            accepted_escrows=[],
            demands=[],
            max_duration_seconds=3600,
            storefront_url="http://seller.test",
            seller_principal=Identity(
                scheme="eip191",
                identifier="0x2222222222222222222222222222222222222222",
            ),
            resource_id=None,
            pool_id="gpu-pool",
        )
        conn = sqlite3.connect(db_path)
        try:
            listing_status = conn.execute(
                "SELECT status FROM listings WHERE listing_id = 'listing-1'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert listing_status == "open"
        loaded = load_derived_listing_for_slice(
            db_path, site_id="site-a", pool_id="gpu-pool", gpu_count=2,
        )
        assert loaded["status"] == "open"


# ---------------------------------------------------------------------------
# mark_derived_listings_closed -- defensive backfill site resolution
# ---------------------------------------------------------------------------

class TestMarkDerivedListingsClosed:
    def test_closes_a_mapped_listing(self, db_path):
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2,
        )
        mark_derived_listings_closed(
            db_path, ["listing-1"], home_site="site-a", configured_site_count=1,
        )
        loaded = load_derived_listing_for_slice(
            db_path, site_id="site-a", pool_id="gpu-pool", gpu_count=2,
        )
        assert loaded["status"] == "closed"

    def test_unmapped_listing_backfills_to_home_site_when_only_one_site_configured(
        self, db_path,
    ):
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        mark_derived_listings_closed(
            db_path, ["listing-1"], home_site="site-a", configured_site_count=1,
        )
        assert site_id_for_listing(db_path, "listing-1") == "site-a"

    def test_unmapped_listing_backfill_is_skipped_when_multiple_sites_configured(
        self, db_path,
    ):
        """With more than one site configured, the backfill must not
        guess which one an unmapped listing belongs to -- it leaves no
        mapping row rather than writing a potentially wrong one. The
        function must not raise."""
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        mark_derived_listings_closed(
            db_path, ["listing-1"], home_site="site-a", configured_site_count=2,
        )  # must not raise
        assert site_id_for_listing(db_path, "listing-1") is None

    def test_empty_listing_ids_is_a_noop(self, db_path):
        mark_derived_listings_closed(
            db_path, [], home_site="site-a", configured_site_count=1,
        )  # must not raise


# ---------------------------------------------------------------------------
# mark_derived_listings_open -- unaffected by site scoping (status-only)
# ---------------------------------------------------------------------------

class TestMarkDerivedListingsOpen:
    def test_reopens_by_listing_id_alone(self, db_path):
        record_derived_listing(
            db_path, listing_id="listing-1", site_id="site-a",
            pool_id="gpu-pool", resource_id=None, gpu_count=2, status="closed",
        )
        mark_derived_listings_open(db_path, ["listing-1"])
        loaded = load_derived_listing_for_slice(
            db_path, site_id="site-a", pool_id="gpu-pool", gpu_count=2,
        )
        assert loaded["status"] == "open"


# ---------------------------------------------------------------------------
# ensure_derived_compute_listings_table -- schema/backward compatibility
# ---------------------------------------------------------------------------

class TestSchema:
    def test_adds_site_id_column_to_a_pre_existing_table(self, db_path):
        """Simulates an old DB whose derived_compute_listings table
        predates site scoping -- the column must be added additively."""
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                """
                CREATE TABLE derived_compute_listings (
                  listing_id TEXT PRIMARY KEY,
                  pool_id TEXT,
                  resource_id TEXT NOT NULL,
                  gpu_count INTEGER NOT NULL,
                  status TEXT NOT NULL,
                  derivation_key TEXT NOT NULL UNIQUE,
                  last_reconciled_at TEXT NOT NULL DEFAULT (STRFTIME('%Y-%m-%dT%H:%M:%fZ', 'now'))
                )
                """
            )
            conn.commit()
            ensure_derived_compute_listings_table(conn)
            cols = {row[1] for row in conn.execute("PRAGMA table_info(derived_compute_listings)")}
            assert "site_id" in cols
        finally:
            conn.close()

    def test_idempotent_rerun(self, db_path):
        conn = sqlite3.connect(db_path)
        try:
            ensure_derived_compute_listings_table(conn)
            ensure_derived_compute_listings_table(conn)  # must not raise
        finally:
            conn.close()

    def test_works_against_a_cursor_not_only_a_connection(self, db_path):
        """SQLiteClient._ensure_domain_tables calls this with a cursor,
        not a connection -- both must work, since this is the single
        source of truth for the table's schema for both callers."""
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            ensure_derived_compute_listings_table(cur)
            conn.commit()
            cols = {row[1] for row in conn.execute("PRAGMA table_info(derived_compute_listings)")}
            assert "site_id" in cols
        finally:
            conn.close()

    def test_sqlite_client_delegates_rather_than_duplicating_the_schema(self, db_path):
        """Regression guard for the two-independent-copies bug: SQLiteClient
        must produce a derived_compute_listings table with every column
        this module's own schema defines, proving it delegates here
        rather than maintaining a second, driftable copy."""
        from market_storefront.utils.sqlite_client import SQLiteClient

        client = SQLiteClient(db_path=db_path)
        conn = sqlite3.connect(client.db_path)
        try:
            client_cols = {
                row[1] for row in conn.execute("PRAGMA table_info(derived_compute_listings)")
            }
        finally:
            conn.close()

        reference_conn = sqlite3.connect(":memory:")
        try:
            ensure_derived_compute_listings_table(reference_conn)
            reference_cols = {
                row[1] for row in reference_conn.execute(
                    "PRAGMA table_info(derived_compute_listings)"
                )
            }
        finally:
            reference_conn.close()

        assert client_cols == reference_cols

# ---------------------------------------------------------------------------
# _member_available_units -- the shared cap-by-availability helper
# ---------------------------------------------------------------------------

class TestMemberAvailableUnits:
    def test_none_availability_means_fully_available(self):
        assert _member_available_units(8, ("site-a", "res-1"), None) == 8

    def test_capped_by_the_availability_lookup(self):
        avail = {("site-a", "res-1"): 3}
        assert _member_available_units(8, ("site-a", "res-1"), avail) == 3

    def test_capped_by_member_total_even_if_availability_says_more(self):
        avail = {("site-a", "res-1"): 99}
        assert _member_available_units(8, ("site-a", "res-1"), avail) == 8

    def test_missing_key_in_availability_means_zero(self):
        avail = {("site-a", "other-res"): 5}
        assert _member_available_units(8, ("site-a", "res-1"), avail) == 0

    def test_never_negative(self):
        avail = {("site-a", "res-1"): -5}
        assert _member_available_units(8, ("site-a", "res-1"), avail) == 0


# ---------------------------------------------------------------------------
# _accumulate_capacity_pool_member -- local capacity-pools aggregation
# ---------------------------------------------------------------------------

class TestAccumulateCapacityPoolMember:
    def _fresh_pool(self):
        return {
            "total_gpu_count": 0, "available_gpu_count": 0,
            "max_member_available_gpu_count": 0, "single_resource_id": None,
            "member_count": 0,
        }

    def test_first_member_sets_single_resource_id(self):
        pool = self._fresh_pool()
        row = {"gpu_count": 4, "site": None, "resource_id": "res-1"}
        _accumulate_capacity_pool_member(pool, row, None)
        assert pool["single_resource_id"] == "res-1"
        assert pool["member_count"] == 1
        assert pool["total_gpu_count"] == 4
        assert pool["available_gpu_count"] == 4

    def test_second_member_clears_single_resource_id(self):
        """A pool with more than one member is fungible, not
        single-resource-keyed -- single_resource_id must become None
        again once a second member is folded in."""
        pool = self._fresh_pool()
        _accumulate_capacity_pool_member(
            pool, {"gpu_count": 4, "site": None, "resource_id": "res-1"}, None,
        )
        _accumulate_capacity_pool_member(
            pool, {"gpu_count": 4, "site": None, "resource_id": "res-2"}, None,
        )
        assert pool["single_resource_id"] is None
        assert pool["member_count"] == 2
        assert pool["total_gpu_count"] == 8

    def test_max_member_available_tracks_the_largest_single_member(self):
        pool = self._fresh_pool()
        avail = {(None, "res-1"): 2, (None, "res-2"): 6}
        _accumulate_capacity_pool_member(
            pool, {"gpu_count": 4, "site": None, "resource_id": "res-1"}, avail,
        )
        _accumulate_capacity_pool_member(
            pool, {"gpu_count": 8, "site": None, "resource_id": "res-2"}, avail,
        )
        assert pool["max_member_available_gpu_count"] == 6
        assert pool["available_gpu_count"] == 8  # sum, not max

    def test_site_tagged_member_uses_its_own_site_in_the_availability_key(self):
        pool = self._fresh_pool()
        avail = {("dc-b", "res-1"): 3}
        _accumulate_capacity_pool_member(
            pool, {"gpu_count": 4, "site": "dc-b", "resource_id": "res-1"}, avail,
        )
        assert pool["available_gpu_count"] == 3


# ---------------------------------------------------------------------------
# _project_legacy_resource_row -- one legacy `resources` row -> pool_rows entry
# ---------------------------------------------------------------------------

class TestProjectLegacyResourceRow:
    def _row(self, **overrides):
        base = {
            "resource_id": "res-1",
            "attributes": '{"gpu_model": "H100", "region": "us-east", "sla": 99.9}',
            "value": 4,
            "min_price": "10",
            "token": "0xtoken",
            "accepted_escrows": "[]",
            "max_duration_seconds": 3600,
        }
        base.update(overrides)
        return base

    def test_reads_descriptive_attributes(self):
        row = self._project(self._row())
        assert row["gpu_model"] == "H100"
        assert row["region"] == "us-east"
        assert row["sla"] == 99.9

    def test_defaults_pool_id_to_resource_id_when_attributes_lack_it(self):
        row = self._project(self._row())
        assert row["pool_id"] == "res-1"
        assert row["single_resource_id"] == "res-1"

    def test_uses_attributes_pool_id_when_present(self):
        row = self._project(self._row(
            attributes='{"pool_id": "shared-pool", "gpu_model": "H100"}',
        ))
        assert row["pool_id"] == "shared-pool"

    def test_malformed_attributes_json_does_not_raise(self):
        row = self._project(self._row(attributes="not json"))
        assert row["gpu_model"] is None

    def test_missing_optional_columns_become_none(self):
        row = self._project(
            self._row(), has_accepted=False, has_max_duration=False,
        )
        assert row["accepted_escrows"] is None
        assert row["max_duration_seconds"] is None

    def test_availability_caps_total(self):
        row = self._project(
            self._row(value=8),
            member_availability={(None, "res-1"): 3},
        )
        assert row["available_gpu_count"] == 3
        assert row["total_gpu_count"] == 8

    def _project(
        self, row, *, has_accepted=True, has_max_duration=True, member_availability=None,
    ):
        return _project_legacy_resource_row(
            row, has_accepted=has_accepted, has_max_duration=has_max_duration,
            member_availability=member_availability,
        )


# ---------------------------------------------------------------------------
# _projected_resource_usage -- pure per-resource derivation
# ---------------------------------------------------------------------------

class TestProjectedResourceUsage:
    def test_returns_none_without_a_physical_resource_id(self):
        usage = _projected_resource_usage(
            {}, site_id="site-a", member_availability=None,
        )
        assert usage is None

    def test_none_availability_means_fully_available(self):
        usage = _projected_resource_usage(
            {"physical_resource_id": "res-1", "capacity": {"gpu_count": 8}},
            site_id="site-a", member_availability=None,
        )
        assert usage.total == 8
        assert usage.available == 8

    def test_prefers_the_projections_own_available_field_when_present(self):
        """When the projection row already carries live availability,
        that value is used directly, not the member_availability lookup
        (which is only a fallback for when it's absent)."""
        usage = _projected_resource_usage(
            {
                "physical_resource_id": "res-1",
                "capacity": {"gpu_count": 8},
                "available": {"gpu_count": 5},
            },
            site_id="site-a",
            member_availability={("site-a", "res-1"): 1},  # would give a different answer
        )
        assert usage.available == 5

    def test_prefers_the_projections_own_available_field_even_when_member_availability_is_none(self):
        """The projection's own available field must be used even when
        member_availability is None -- it is authoritative live data
        from the projection itself, not conditional on whether a
        *different* fallback source happens to be present."""
        usage = _projected_resource_usage(
            {
                "physical_resource_id": "res-1",
                "capacity": {"gpu_count": 8},
                "available": {"gpu_count": 5},
            },
            site_id="site-a",
            member_availability=None,
        )
        assert usage.available == 5

    def test_falls_back_to_member_availability_when_no_available_field(self):
        usage = _projected_resource_usage(
            {"physical_resource_id": "res-1", "capacity": {"gpu_count": 8}},
            site_id="site-a",
            member_availability={("site-a", "res-1"): 2},
        )
        assert usage.available == 2

    def test_gpu_model_read_from_attributes(self):
        usage = _projected_resource_usage(
            {
                "physical_resource_id": "res-1",
                "capacity": {"gpu_count": 1},
                "attributes": {"gpu_model": "A100"},
            },
            site_id="site-a", member_availability=None,
        )
        assert usage.gpu_model == "A100"

    def test_gpu_model_none_when_absent(self):
        usage = _projected_resource_usage(
            {"physical_resource_id": "res-1", "capacity": {"gpu_count": 1}},
            site_id="site-a", member_availability=None,
        )
        assert usage.gpu_model is None


# ---------------------------------------------------------------------------
# _fungible_availability_from_buckets -- direct contract tests, isolated
# from _projected_pool_rows' pricing/resource-walk scaffolding
# ---------------------------------------------------------------------------

class TestFungibleAvailabilityFromBuckets:
    def test_none_family_falls_back(self):
        assert _fungible_availability_from_buckets("gpu-pool", None) is None

    def test_loaded_empty_family_is_trusted_zero(self):
        assert _fungible_availability_from_buckets("gpu-pool", []) == (0, 0, None)

    def test_loaded_family_with_no_matching_pool_is_trusted_zero(self):
        buckets = [
            {"resource_pool_id": "other-pool", "available": {"gpu_count": 9}, "resource_count": 2},
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) == (0, 0, None)

    def test_matching_readable_bucket_is_used(self):
        buckets = [
            {
                "resource_pool_id": "gpu-pool",
                "available": {"gpu_count": 6},
                "resource_count": 2,
                "grouping_attributes": {"gpu_model": "H100"},
            },
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) == (6, 12, "H100")

    def test_max_across_multiple_matching_buckets_not_sum(self):
        buckets = [
            {"resource_pool_id": "gpu-pool", "available": {"gpu_count": 2}, "resource_count": 1},
            {"resource_pool_id": "gpu-pool", "available": {"gpu_count": 6}, "resource_count": 1},
        ]
        max_available, total_available, _ = _fungible_availability_from_buckets(
            "gpu-pool", buckets,
        )
        assert max_available == 6
        assert total_available == 2 + 6

    def test_matching_but_unreadable_bucket_falls_back(self):
        """A bucket entry exists for this pool but predates per-resource
        `available` (empty dict, no `gpu_count` key) -- not the same as
        a confirmed absence, must fall back rather than read as zero."""
        buckets = [
            {"resource_pool_id": "gpu-pool", "available": {}, "resource_count": 1},
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) is None

    def test_one_readable_and_one_unreadable_matching_bucket_uses_the_readable_one(self):
        buckets = [
            {"resource_pool_id": "gpu-pool", "available": {}, "resource_count": 1},
            {"resource_pool_id": "gpu-pool", "available": {"gpu_count": 4}, "resource_count": 1},
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) == (4, 4, None)


# ---------------------------------------------------------------------------
# _projected_pool_rows -- one projected pool -> zero or more pool_rows entries
# ---------------------------------------------------------------------------

class TestProjectedPoolRows:
    def _pricing_row(self, **overrides):
        base = {
            "gpu_model": "H100", "region": "us-east", "sla": 99.9,
            "min_price": "10", "token": "0xtoken", "accepted_escrows": "[]",
            "max_duration_seconds": 3600,
        }
        base.update(overrides)
        return base

    def test_empty_without_a_pool_id(self):
        rows = _projected_pool_rows(
            {}, site_id="site-a", home_site="site-a",
            local_pricing={}, member_availability=None, capacity_buckets=None,
        )
        assert rows == []

    def test_non_home_site_pool_with_a_matching_local_pool_id_never_uses_it(self):
        """`compute_capacity_pools` is never consulted for a non-home-site
        pool (cross-site pool_id collision risk -- see `_local_pool_pricing`),
        even when a same-named local row exists -- but the pool still
        publishes, priceless, since a missing storefront-override tier is
        not a reason to suppress the pool entirely."""
        rows = _projected_pool_rows(
            {"resource_pool_id": "gpu-pool", "resources": []},
            site_id="site-b", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["min_price"] is None
        assert rows[0]["region"] is None

    def test_non_home_site_pool_publishes_from_a_complete_hint_alone(self):
        """The actual point of the three-tier mechanism: a pool this
        storefront has never locally priced still publishes with real
        commercial terms, sourced entirely from its own projected hint."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "attributes": {"gpu_model": "H100"},
                        "enabled": True,
                    },
                ],
                "pool_metadata": {
                    "policy_tags": {
                        "region": "Nevada, US",
                        "pricing": {
                            "gpu": {
                                "H100": {
                                    "min_price": "5.00", "token": "0xhint",
                                    "max_duration_seconds": 3600,
                                },
                            },
                        },
                    },
                },
            },
            site_id="site-b", home_site="site-a",
            local_pricing={}, member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["region"] == "Nevada, US"
        assert rows[0]["min_price"] == "5.00"
        assert rows[0]["token"] == "0xhint"

    def test_home_site_pool_with_no_local_row_publishes_priceless_by_default(self):
        rows = _projected_pool_rows(
            {"resource_pool_id": "unpriced", "resources": []},
            site_id="site-a", home_site="site-a",
            local_pricing={}, member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["min_price"] is None
        assert rows[0]["region"] is None
        assert rows[0]["sla"] == 0.0

    def test_home_site_pool_with_no_local_row_publishes_from_config_default(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "unpriced",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "attributes": {"gpu_model": "A100"},
                        "enabled": True,
                    },
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={}, member_availability=None, capacity_buckets=None,
            hint_resolution=PoolHintResolutionSettings(
                gpu_pricing_defaults_by_model={
                    "A100": GpuPricingFields(min_price="3.00"),
                },
            ),
        )
        assert len(rows) == 1
        assert rows[0]["min_price"] == "3.00"

    def test_home_site_pool_with_local_row_still_uses_it_as_the_override(self):
        """The corrected behavior doesn't disturb the ordinary case: a
        real local row still wins as the top-precedence override."""
        rows = _projected_pool_rows(
            {"resource_pool_id": "gpu-pool", "resources": []},
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(min_price="10")},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["min_price"] == "10"

    def test_builds_one_fungible_row_for_home_site_pool_with_pricing(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "attributes": {"gpu_model": "H100"},
                        "enabled": True,
                    },
                ],
                # Explicit tag: a single-member pool's *structural*
                # default is specific_resource (backward compatibility,
                # see test_single_member_pool_defaults_to_specific_resource_without_a_tag
                # below) -- an explicit fungible tag is what this test
                # actually wants to exercise.
                "pool_metadata": {"policy_tags": {"listing_mode": "fungible"}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["pool_id"] == "gpu-pool"
        assert row["site_id"] == "site-a"
        assert row["total_gpu_count"] == 4
        assert row["min_price"] == "10"
        assert row["listing_mode"] == "fungible"
        assert row["listing_mode_explanation"] is None
        assert row["single_resource_id"] is None

    def test_single_member_pool_defaults_to_specific_resource_without_a_tag(self):
        """Backward compatibility: `available_compute_slices` always
        treated a single-member pool as specific-resource before
        `listing_mode` existed (`member_count == 1` heuristic). An
        untagged pool with exactly one member must keep resolving that
        way, or an existing derived-listing mapping keyed on that
        resource's identity would silently break the moment a
        projection without `pool_metadata` reaches this function."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "attributes": {"gpu_model": "H100"},
                        "enabled": True,
                    },
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["listing_mode"] == "specific_resource"
        assert rows[0]["single_resource_id"] == "res-1"

    def test_multi_member_pool_defaults_to_fungible_without_a_tag(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "enabled": True,
                    },
                    {
                        "physical_resource_id": "res-2",
                        "capacity": {"gpu_count": 4},
                        "enabled": True,
                    },
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["listing_mode"] == "fungible"
        assert rows[0]["single_resource_id"] is None

    def test_disabled_resources_are_excluded(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "enabled": False,
                    },
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["total_gpu_count"] == 0
        assert rows[0]["member_count"] == 0

    def test_gpu_model_prefers_resource_attributes_over_local_pricing(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "attributes": {"gpu_model": "A100"},
                        "enabled": True,
                    },
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(gpu_model="H100")},
            member_availability=None, capacity_buckets=None,
        )
        assert rows[0]["gpu_model"] == "A100"

    def test_gpu_model_falls_back_to_local_pricing_when_resources_lack_it(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "enabled": True,
                    },
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(gpu_model="H100")},
            member_availability=None, capacity_buckets=None,
        )
        assert rows[0]["gpu_model"] == "H100"

    # -- region/sla hint resolution ---------------------------------------

    def test_region_hint_overrides_local_pricing_fallback(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {"physical_resource_id": "res-1", "capacity": {"gpu_count": 4}, "enabled": True},
                ],
                "pool_metadata": {"policy_tags": {"region": "Nevada, US"}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(region="us-east")},
            member_availability=None, capacity_buckets=None,
        )
        assert rows[0]["region"] == "Nevada, US"

    def test_region_falls_back_to_local_pricing_without_a_hint(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {"physical_resource_id": "res-1", "capacity": {"gpu_count": 4}, "enabled": True},
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(region="us-east")},
            member_availability=None, capacity_buckets=None,
        )
        assert rows[0]["region"] == "us-east"

    def test_sla_storefront_override_wins_over_pool_hint_by_default(self):
        """No hint_resolution passed -- the default settings apply, and
        the local pricing row's sla acts as the storefront's per-pool
        override, taking precedence over any pool-declared hint
        regardless of the (default-closed) trust gate."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {"physical_resource_id": "res-1", "capacity": {"gpu_count": 4}, "enabled": True},
                ],
                "pool_metadata": {"policy_tags": {"sla": 50.0}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(sla=99.9)},
            member_availability=None, capacity_buckets=None,
        )
        assert rows[0]["sla"] == 99.9

    def test_sla_pool_hint_used_when_no_local_override_and_gate_open(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {"physical_resource_id": "res-1", "capacity": {"gpu_count": 4}, "enabled": True},
                ],
                "pool_metadata": {"policy_tags": {"sla": 95.0}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(sla=None)},
            member_availability=None, capacity_buckets=None,
            hint_resolution=PoolHintResolutionSettings(
                accept_pool_declared_sla=True, default_sla=0.0,
            ),
        )
        assert rows[0]["sla"] == 95.0

    def test_sla_pool_hint_ignored_when_gate_closed_even_with_no_override(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {"physical_resource_id": "res-1", "capacity": {"gpu_count": 4}, "enabled": True},
                ],
                "pool_metadata": {"policy_tags": {"sla": 95.0}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(sla=None)},
            member_availability=None, capacity_buckets=None,
            hint_resolution=PoolHintResolutionSettings(
                accept_pool_declared_sla=False, default_sla=12.5,
            ),
        )
        assert rows[0]["sla"] == 12.5

    def test_sla_falls_back_to_config_default_with_no_override_or_hint(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {"physical_resource_id": "res-1", "capacity": {"gpu_count": 4}, "enabled": True},
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(sla=None)},
            member_availability=None, capacity_buckets=None,
            hint_resolution=PoolHintResolutionSettings(
                accept_pool_declared_sla=True, default_sla=42.0,
            ),
        )
        assert rows[0]["sla"] == 42.0

    # -- pricing hint resolution ------------------------------------------

    def test_pricing_storefront_override_wins_over_pool_hint(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1", "capacity": {"gpu_count": 4},
                        "attributes": {"gpu_model": "H100"}, "enabled": True,
                    },
                ],
                "pool_metadata": {
                    "policy_tags": {"pricing": {"gpu": {"H100": {"min_price": "5.00"}}}},
                },
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(min_price="10")},
            member_availability=None, capacity_buckets=None,
        )
        assert rows[0]["min_price"] == "10"

    def test_pricing_pool_hint_used_when_no_storefront_override(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1", "capacity": {"gpu_count": 4},
                        "attributes": {"gpu_model": "H100"}, "enabled": True,
                    },
                ],
                "pool_metadata": {
                    "policy_tags": {"pricing": {"gpu": {"H100": {"min_price": "5.00"}}}},
                },
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(min_price=None)},
            member_availability=None, capacity_buckets=None,
        )
        assert rows[0]["min_price"] == "5.00"

    def test_pricing_falls_back_to_per_model_config_default(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1", "capacity": {"gpu_count": 4},
                        "attributes": {"gpu_model": "H100"}, "enabled": True,
                    },
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(min_price=None)},
            member_availability=None, capacity_buckets=None,
            hint_resolution=PoolHintResolutionSettings(
                gpu_pricing_defaults_by_model={
                    "H100": GpuPricingFields(min_price="3.00"),
                },
            ),
        )
        assert rows[0]["min_price"] == "3.00"

    def test_pricing_falls_back_to_flat_config_default_as_last_resort(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1", "capacity": {"gpu_count": 4},
                        "attributes": {"gpu_model": "H100"}, "enabled": True,
                    },
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(min_price=None)},
            member_availability=None, capacity_buckets=None,
            hint_resolution=PoolHintResolutionSettings(
                gpu_pricing_flat_default=GpuPricingFields(min_price="1.00"),
            ),
        )
        assert rows[0]["min_price"] == "1.00"

    def test_specific_resource_multi_member_prices_each_by_its_own_model(self):
        """Two members with different GPU models must resolve pricing
        independently -- proving pricing resolution is per-row, not
        computed once for the whole pool."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1", "capacity": {"gpu_count": 8},
                        "attributes": {"gpu_model": "H100"}, "enabled": True,
                    },
                    {
                        "physical_resource_id": "res-2", "capacity": {"gpu_count": 8},
                        "attributes": {"gpu_model": "A100"}, "enabled": True,
                    },
                ],
                "pool_metadata": {
                    "policy_tags": {
                        "listing_mode": "specific_resource",
                        "pricing": {
                            "gpu": {
                                "H100": {"min_price": "5.00"},
                                "A100": {"min_price": "3.00"},
                            },
                        },
                    },
                },
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row(min_price=None)},
            member_availability=None, capacity_buckets=None,
        )
        by_resource = {row["single_resource_id"]: row for row in rows}
        assert by_resource["res-1"]["min_price"] == "5.00"
        assert by_resource["res-2"]["min_price"] == "3.00"

    # -- listing_mode resolution --------------------------------------

    def test_unrecognized_listing_mode_falls_back_with_explanation(self):
        """One member -> structural default is specific_resource (see
        test_single_member_pool_defaults_to_specific_resource_without_a_tag)
        -- an unrecognized explicit value falls back to *that* default,
        not a hardcoded constant."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "enabled": True,
                    },
                ],
                "pool_metadata": {"policy_tags": {"listing_mode": "bogus"}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["listing_mode"] == "specific_resource"
        assert rows[0]["listing_mode_explanation"] is not None
        assert "bogus" in rows[0]["listing_mode_explanation"]

    def test_unrecognized_listing_mode_falls_back_to_fungible_for_multi_member(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {"physical_resource_id": "res-1", "capacity": {"gpu_count": 4}, "enabled": True},
                    {"physical_resource_id": "res-2", "capacity": {"gpu_count": 4}, "enabled": True},
                ],
                "pool_metadata": {"policy_tags": {"listing_mode": "bogus"}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["listing_mode"] == "fungible"
        assert rows[0]["listing_mode_explanation"] is not None
        assert "bogus" in rows[0]["listing_mode_explanation"]

    # -- specific_resource, including multi-member ----------------------

    def test_specific_resource_single_member_yields_one_resource_keyed_row(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 8},
                        "attributes": {"gpu_model": "H100"},
                        "enabled": True,
                    },
                ],
                "pool_metadata": {
                    "policy_tags": {"listing_mode": "specific_resource"},
                },
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["single_resource_id"] == "res-1"
        assert rows[0]["listing_mode"] == "specific_resource"

    def test_specific_resource_multi_member_yields_one_row_per_member(self):
        """A multi-member pool declared specific_resource must publish
        one independently identified row per member, not collapse to a
        single aggregate the way fungible mode does."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 8},
                        "available": {"gpu_count": 8},
                        "attributes": {"gpu_model": "H100"},
                        "enabled": True,
                    },
                    {
                        "physical_resource_id": "res-2",
                        "capacity": {"gpu_count": 8},
                        "available": {"gpu_count": 6},
                        "attributes": {"gpu_model": "H100"},
                        "enabled": True,
                    },
                    {
                        "physical_resource_id": "res-3",
                        "capacity": {"gpu_count": 8},
                        "available": {"gpu_count": 0},
                        "attributes": {"gpu_model": "H100"},
                        "enabled": True,
                    },
                ],
                "pool_metadata": {
                    "policy_tags": {"listing_mode": "specific_resource"},
                },
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 3
        by_resource = {row["single_resource_id"]: row for row in rows}
        assert set(by_resource) == {"res-1", "res-2", "res-3"}
        assert by_resource["res-1"]["available_gpu_count"] == 8
        assert by_resource["res-2"]["available_gpu_count"] == 6
        assert by_resource["res-3"]["available_gpu_count"] == 0
        # Each row's own availability, not summed/maxed across the pool.
        assert by_resource["res-1"]["max_member_available_gpu_count"] == 8
        assert by_resource["res-2"]["max_member_available_gpu_count"] == 6

    def test_specific_resource_disabled_member_excluded(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 8},
                        "enabled": True,
                    },
                    {
                        "physical_resource_id": "res-2",
                        "capacity": {"gpu_count": 8},
                        "enabled": False,
                    },
                ],
                "pool_metadata": {
                    "policy_tags": {"listing_mode": "specific_resource"},
                },
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert len(rows) == 1
        assert rows[0]["single_resource_id"] == "res-1"

    # -- fungible mode sourced from site_capacity_buckets ----------------

    def test_fungible_prefers_bucket_availability_over_resource_walk(self):
        """The max_member_available ceiling must reflect a single bucket's
        (i.e. a single member's) availability, not a sum across buckets,
        and must come from the bucket data when it's usable."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 8},
                        "attributes": {"gpu_model": "H100"},
                        "enabled": True,
                    },
                    {
                        "physical_resource_id": "res-2",
                        "capacity": {"gpu_count": 8},
                        "attributes": {"gpu_model": "H100"},
                        "enabled": True,
                    },
                ],
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None,
            capacity_buckets=[
                {
                    "resource_pool_id": "gpu-pool",
                    "available": {"gpu_count": 2},
                    "resource_count": 1,
                    "grouping_attributes": {"gpu_model": "H100"},
                },
                {
                    "resource_pool_id": "gpu-pool",
                    "available": {"gpu_count": 6},
                    "resource_count": 1,
                    "grouping_attributes": {"gpu_model": "H100"},
                },
            ],
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["max_member_available_gpu_count"] == 6
        assert row["available_gpu_count"] == 2 * 1 + 6 * 1

    def test_fungible_trusts_zero_when_family_loaded_with_no_matching_entries(self):
        """Corrected behavior: a *loaded* capacity-bucket family (however
        many entries it has) that contains no entry for this specific
        pool is itself the authoritative answer -- zero -- not missing
        data. `capacity_bucket_projection` covers the site's complete
        enabled-resource inventory, so a pool with any enabled member
        would necessarily contribute at least one matching entry once
        the family has loaded; absence means the pool currently has none.
        Falling back to a separately-fetched resource-pool projection
        here would let two independently-polled projection generations
        silently contradict each other."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 8},
                        "enabled": True,
                    },
                ],
                "pool_metadata": {"policy_tags": {"listing_mode": "fungible"}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None,
            capacity_buckets=[
                {
                    "resource_pool_id": "other-pool",
                    "available": {"gpu_count": 99},
                    "resource_count": 5,
                },
            ],
        )
        assert rows[0]["max_member_available_gpu_count"] == 0
        assert rows[0]["available_gpu_count"] == 0

    def test_fungible_trusts_zero_when_family_loaded_as_a_whole_empty_list(self):
        """The site-wide "authoritative zero buckets anywhere" case --
        e.g. the capacity-bucket family loaded successfully but the site
        currently has no enabled resources at all. Must be trusted the
        same way a per-pool absence is, not treated as unknown."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 8},
                        "enabled": True,
                    },
                ],
                "pool_metadata": {"policy_tags": {"listing_mode": "fungible"}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None,
            capacity_buckets=[],
        )
        assert rows[0]["max_member_available_gpu_count"] == 0
        assert rows[0]["available_gpu_count"] == 0

    def test_fungible_falls_back_to_resource_walk_when_no_bucket_data(self):
        """No site_capacity_buckets supplied at all (None) -- must not
        publish zero capacity, must use the pre-existing computation."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "available": {"gpu_count": 3},
                        "enabled": True,
                    },
                ],
                "pool_metadata": {"policy_tags": {"listing_mode": "fungible"}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None, capacity_buckets=None,
        )
        assert rows[0]["max_member_available_gpu_count"] == 3

    def test_fungible_falls_back_when_bucket_predates_available_field(self):
        """A bucket whose `available` dict lacks `gpu_count` entirely
        (an older producer that never emitted per-resource availability)
        must not be read as an authoritative zero -- falls back to the
        resource-list computation instead."""
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "available": {"gpu_count": 4},
                        "enabled": True,
                    },
                ],
                "pool_metadata": {"policy_tags": {"listing_mode": "fungible"}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None,
            capacity_buckets=[
                {"resource_pool_id": "gpu-pool", "available": {}, "resource_count": 1},
            ],
        )
        assert rows[0]["max_member_available_gpu_count"] == 4

    def test_fungible_trusts_a_genuine_zero_from_buckets(self):
        rows = _projected_pool_rows(
            {
                "resource_pool_id": "gpu-pool",
                "resources": [
                    {
                        "physical_resource_id": "res-1",
                        "capacity": {"gpu_count": 4},
                        "available": {"gpu_count": 4},
                        "enabled": True,
                    },
                ],
                "pool_metadata": {"policy_tags": {"listing_mode": "fungible"}},
            },
            site_id="site-a", home_site="site-a",
            local_pricing={"gpu-pool": self._pricing_row()},
            member_availability=None,
            capacity_buckets=[
                {
                    "resource_pool_id": "gpu-pool",
                    "available": {"gpu_count": 0},
                    "resource_count": 1,
                },
            ],
        )
        # A real zero from a usable bucket is trusted, even though the
        # resource-list walk (never consulted for max/available once a
        # usable bucket exists) would have said 4.
        assert rows[0]["max_member_available_gpu_count"] == 0
        assert rows[0]["available_gpu_count"] == 0

