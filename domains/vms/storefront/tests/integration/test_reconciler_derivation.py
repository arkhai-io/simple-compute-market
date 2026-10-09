"""Integration tests for arkhai_vms_listings.reconciler against SQLite.

External boundary: a real sqlite3 file DB with a minimal hand-built schema
(not the full SQLiteClient migration chain) -- reconciler.py is itself plain
synchronous sqlite3 code with no async dependencies, so a minimal schema
exercising exactly the tables it reads/writes is the right level, matching
test_compute_allocations.py's precedent.
"""

from __future__ import annotations

import json
import sqlite3
import pytest
from core_storefront.sqlite_migrations import migrate_storefront_domain_bindings_schema
from arkhai_vms_listings.pricing_resolution import GpuPricingFields
from arkhai_vms_listings.reconciler import (
    PoolHintResolutionSettings,
    declared_shape_feasibility,
    listing_pool_key,
    open_listing_resource_keys,
    pool_id_for_listing,
    site_id_for_listing,
)
from arkhai_vms_listings.listing_shapes import CONFIGURED_DEFAULT_TIER, resolve_shape
from market_capability_admissibility import parse_declaration

from arkhai_vms import VM_CAPABILITY_SCHEMA
from tests._reconciler_cases import (
    _BACKED,
    _FEASIBILITY,
    _BIG,
    _SMALL_SHAPE,
    _UNBACKED,
    _VM_BINDING,
    _VM_DOMAIN,
    _VM_REGISTRY,
    _available_vm_slices,
    _declared_pool,
    _gpu_key,
    _member,
    _override_rows,
    _rate,
    _seed_fungible_pool,
    _seed_listing,
    _seed_pool,
    _shape_slices,
    _shaped_pool,
    _site_report,
    _slices,
    available_compute_slices,
    closed_available_listing_ids,
    db_path,
    stale_open_listing_ids,
)


class TestAvailableComputeSlices:
    def test_every_slice_is_tagged_with_home_site(self, db_path):
        _seed_pool(db_path)
        slices = _available_vm_slices(db_path, home_site="site-a")
        assert slices
        assert all(row["site_id"] == "site-a" for row in slices)

    def test_resource_key_is_site_scoped(self, db_path):
        _seed_pool(db_path, gpu_count=1)
        slices = _available_vm_slices(db_path, home_site="site-a")
        assert slices[0]["resource_key"] == _gpu_key(
            "site-a", gpu_count=1, model="H100", resource_id="resource-1",
        )

    def test_different_home_site_produces_different_keys_for_identical_data(self, db_path):
        _seed_pool(db_path, gpu_count=1)
        keys_a = {r["resource_key"] for r in _available_vm_slices(db_path, home_site="site-a")}
        keys_b = {r["resource_key"] for r in _available_vm_slices(db_path, home_site="site-b")}
        assert keys_a and keys_b
        assert keys_a.isdisjoint(keys_b)

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
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection={"site-a": []},)
        assert slices == []

    def test_projection_sourced_pool_uses_local_pricing_for_home_site(self, db_path):
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)  # local pricing row
        projection = {
            "site-a": [
                {
                    "pool_id": "gpu-pool",
                    "resources": [
                        {
                            "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                            "capacity": {"gpu_count": 8},
                            # The local row publishes region us-east; a claim
                            # matches it against the declaration.
                            "attributes": {"gpu_model": "H100", "region": "us-east"},
                            "enabled": True,
                        },
                    ],
                },
            ],
        }
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        assert slices
        assert all(row["site_id"] == "site-a" for row in slices)
        # Structure/GPU model from the projection (8, not the local
        # table's seeded 4), terms from the local table.
        assert max(row["gpu_count"] for row in slices) == 8
        assert all(row["gpu_model"] == "H100" for row in slices)
        assert all(row["max_duration_seconds"] == 3600 for row in slices)  # _seed_pool's term
        # min_price and token are not listing terms, from any tier.
        assert all("min_price" not in row and "token" not in row for row in slices)

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
                    "pool_id": "gpu-pool",  # same pool_id as the local row
                    "resources": [
                        {
                            "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                            "capacity": {"gpu_count": 8},
                            "attributes": {"gpu_model": "H100"},
                            "enabled": True,
                        },
                    ],
                },
            ],
        }
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        assert slices
        assert all(s.get("max_duration_seconds") is None for s in slices)
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
                    "pool_id": "unpriced-pool",
                    "resources": [
                        {
                            "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                            "capacity": {"gpu_count": 4},
                            "attributes": {"gpu_model": "H100"},
                            "enabled": True,
                        },
                    ],
                },
            ],
        }
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        assert slices
        assert all(s.get("max_duration_seconds") is None for s in slices)

    def test_projection_disabled_resource_excluded_from_capacity(self, db_path):
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=4)
        projection = {
            "site-a": [
                {
                    "pool_id": "gpu-pool",
                    "resources": [
                        {
                            "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                            "capacity": {"gpu_count": 8},
                            "attributes": {},
                            "enabled": False,
                        },
                    ],
                },
            ],
        }
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
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
                "pool_id": "gpu-pool",
                "resources": [{
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100", "region": "us-east"},
                    "enabled": True,
                }],
            }],
            "site-b": [{
                "pool_id": "other-pool",
                "resources": [{
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "A100"},
                    "enabled": True,
                }],
            }],
        }
        slices = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        by_site = {}
        for row in slices:
            by_site.setdefault(row["site_id"], []).append(row)
        assert set(by_site) == {"site-a", "site-b"}
        assert all(row["max_duration_seconds"] == 3600 for row in by_site["site-a"])
        assert all(row["max_duration_seconds"] is None for row in by_site["site-b"])

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
                "pool_id": "gpu-pool",
                "resources": [{
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                }],
            }],
        }
        default_rows = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,)
        varied_rows = _available_vm_slices(db_path, home_site="site-a", site_pool_projection=projection,
        hint_resolution=PoolHintResolutionSettings(
            accept_pool_declared_sla=True, default_sla=7.0,
            gpu_pricing_defaults_by_model={
                "H100": GpuPricingFields(max_duration_seconds=60),
            },
            family_rate_defaults={
                "gpu": {"H100": {"rates": [
                    {"asset": "usd", "rate": "1", "per": "hour"},
                ]}},
            },
        ),)
        default_keys = {r["resource_key"] for r in default_rows}
        varied_keys = {r["resource_key"] for r in varied_rows}
        assert default_keys == varied_keys
        assert default_keys  # not vacuously true
        # Confirm the two runs actually resolved *different* commercial
        # values -- otherwise this test wouldn't be exercising anything.
        assert {r["sla"] for r in default_rows} != {r["sla"] for r in varied_rows}


class TestSiteIdForListing:
    def test_returns_none_when_listing_has_no_durable_binding(self, db_path):
        assert site_id_for_listing(db_path, "listing-1") is None

    def test_returns_the_registry_owned_binding_site(self, db_path):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        assert site_id_for_listing(db_path, "listing-1") == "site-a"


class TestPoolIdForListing:
    def test_returns_registry_owned_pool_id(self, db_path):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        assert pool_id_for_listing(db_path, "listing-1") == "gpu-pool"

    def test_none_for_unmapped_listing(self, db_path):
        assert pool_id_for_listing(db_path, "listing-none") is None

    def test_resource_only_binding_does_not_invent_a_pool_id(self, db_path):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id=None,
            resource_id="res-1",
            gpu_count=4,
            site_id="site-a",
        )
        assert pool_id_for_listing(db_path, "listing-1") is None

    def test_returns_the_real_pool_id_for_a_specific_resource_within_a_pool(
        self, db_path,
    ):
        """A specific-resource binding preserves its pool and resource IDs."""
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            resource_id="res-1",
            gpu_count=4,
            site_id="site-a",
        )
        assert pool_id_for_listing(db_path, "listing-1") == "gpu-pool"


class TestOpenListingResourceKeys:
    def test_bound_open_listing_is_covered(self, db_path):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        covered = open_listing_resource_keys(
            db_path, home_site="site-a",
        )
        assert _gpu_key("site-a", gpu_count=2, model="H100", pool_id="gpu-pool") in covered

    def test_unbound_listing_is_excluded_even_with_one_configured_site(
        self, db_path,
    ):
        """A single configured site never substitutes for durable ownership."""
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        covered = open_listing_resource_keys(
            db_path, home_site="site-a",
        )
        assert covered == set()

    def test_unbound_listing_is_excluded_with_multiple_sites(self, db_path):
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        covered = open_listing_resource_keys(
            db_path, home_site="site-a",
        )
        assert covered == set()

    def test_a_bound_listing_is_covered_at_whichever_site_it_names(
        self, db_path,
    ):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-b",
        )
        covered = open_listing_resource_keys(
            db_path, home_site="site-a",
        )
        assert _gpu_key("site-b", gpu_count=2, model="H100", pool_id="gpu-pool") in covered

    def test_bound_listing_does_not_require_a_derived_row(self, db_path):
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        covered = open_listing_resource_keys(
            db_path, home_site="site-a",
        )
        assert _gpu_key("site-a", gpu_count=2, model="H100", pool_id="gpu-pool") in covered


class TestStaleOpenListingIds:
    def test_listing_that_still_fits_is_not_stale(self, db_path):
        _seed_fungible_pool(db_path, member_gpu_counts=(4, 4))
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_sites=("site-a",), backed_only=False)
        assert stale == []

    def test_listing_whose_slice_no_longer_fits_is_stale(self, db_path):
        _seed_pool(db_path, gpu_count=1)  # only 1 GPU available
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_sites=("site-a",), backed_only=False)
        assert stale == ["listing-1"]

    def test_unbound_listing_is_skipped_even_with_one_configured_site(
        self, db_path,
    ):
        _seed_pool(db_path, gpu_count=1)
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        stale = stale_open_listing_ids(
            db_path,
            home_site="site-a",
            configured_sites=("site-a",),
            backed_only=False,
        )
        assert stale == []

    def test_unbound_listing_is_skipped_with_multiple_sites(self, db_path):
        """Configured topology never supplies a missing durable binding."""
        _seed_pool(db_path, gpu_count=1)
        _seed_listing(db_path, listing_id="listing-1", pool_id="gpu-pool", gpu_count=2)
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_sites=("site-a", "site-b"), backed_only=False)
        assert stale == []

    def test_listing_bound_to_a_different_site_uses_that_site(self, db_path):
        _seed_pool(db_path, gpu_count=4)
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-b",
        )
        # Only site-a has capacity data seeded.
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_sites=("site-a",), backed_only=False)
        # VM availability is scoped to site-a, so the site-b-bound listing
        # is stale rather than silently reassigned.
        assert stale == ["listing-1"]

    def test_bound_listing_uses_its_site_regardless_of_site_count(
        self, db_path,
    ):
        """Configured site count cannot override the durable site binding."""
        _seed_fungible_pool(db_path, member_gpu_counts=(4, 4))
        _seed_listing(
            db_path,
            listing_id="listing-1",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        stale = stale_open_listing_ids(db_path, home_site="site-a", configured_sites=("site-a", "site-b", "site-c", "site-d", "site-e"), backed_only=False)
        assert stale == []


class TestClosedAvailableListingIds:
    def test_closed_listing_that_now_fits_is_reopenable(self, db_path):
        _seed_fungible_pool(db_path, member_gpu_counts=(4, 4))
        _seed_listing(
            db_path,
            listing_id="listing-1",
            status="closed",
            pool_id="gpu-pool",
            gpu_count=2,
            site_id="site-a",
        )
        reopenable = closed_available_listing_ids(db_path, home_site="site-a")
        assert reopenable == ["listing-1"]

    def test_empty_when_nothing_is_available(self, db_path):
        assert closed_available_listing_ids(db_path, home_site="site-a") == []


class TestSchema:
    def test_domain_binding_schema_migration_is_idempotent(self, db_path):
        conn = sqlite3.connect(db_path)
        try:
            migrate_storefront_domain_bindings_schema(conn)
            migrate_storefront_domain_bindings_schema(conn)
            columns = {
                row[1]
                for row in conn.execute(
                    "PRAGMA table_info(storefront_listing_bindings)"
                )
            }
        finally:
            conn.close()
        assert {
            "listing_id",
            "site_id",
            "offering_mode",
            "domain_identity",
            "contract_major",
            "contract_minor",
        } <= columns

    def test_fresh_storefront_database_has_no_legacy_mapping_table(self, tmp_path):
        """The common listing binding is the only VM listing mapping.

        A fresh database never creates ``derived_compute_listings``; only a
        database written before the binding existed still carries it, for the
        storefront-domain migration tool to read.
        """
        from market_storefront.utils.sqlite_client import SQLiteClient

        client = SQLiteClient(
            db_path=str(tmp_path / "sqlite-client.db"),
            registry=_VM_REGISTRY,
        )
        assert client.domain_registry.resolve(_VM_BINDING) is _VM_DOMAIN
        conn = sqlite3.connect(client.db_path)
        try:
            assert conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='derived_compute_listings'"
            ).fetchone() is None
        finally:
            conn.close()


class TestUnbackedDerivation:
    def test_unbacked_pool_ranges_over_declared_not_available_quantity(self, db_path):
        pool = _declared_pool("broker-a", [("res-1", 8, 0)], tags=_UNBACKED)

        counts = sorted(s["gpu_count"] for s in _slices(db_path, [pool]))

        assert counts == list(range(1, 9))
        assert {s["capacity_backing"] for s in _slices(db_path, [pool])} == {
            "unbacked"
        }

    def test_backed_pool_ranges_over_available_quantity(self, db_path):
        pool = _declared_pool("pool-b", [("res-1", 8, 2)], tags=_BACKED)

        assert sorted(s["gpu_count"] for s in _slices(db_path, [pool])) == [1, 2]

    def test_unbacked_fungible_range_is_one_members_declared_count(self, db_path):
        pool = _declared_pool(
            "broker-a", [("res-1", 8, 0), ("res-2", 4, 0)], tags=_UNBACKED
        )

        assert max(s["gpu_count"] for s in _slices(db_path, [pool])) == 8

    def test_a_pool_that_does_not_advertise_vm_yields_nothing(self, db_path):
        pool = _declared_pool(
            "broker-a",
            [("res-1", 8, 8)],
            tags={**_UNBACKED, "advertisable_modes": ["bare_metal"]},
        )

        assert _slices(db_path, [pool]) == []

    def test_a_disabled_pool_yields_nothing(self, db_path):
        pool = _declared_pool("broker-a", [("res-1", 8, 8)], tags=_UNBACKED, enabled=False)

        assert _slices(db_path, [pool]) == []


class TestEnumerationQuantity:
    def test_absent_count_yields_nothing_and_is_reported(self, db_path):
        from arkhai_vms_listings.reconciler import derivation_reports

        pool = _declared_pool("broker-a", [("res-1", None, 0)], tags=_UNBACKED)

        assert _slices(db_path, [pool]) == []
        assert derivation_reports()["site-a"]["members_without_gpu_count"] == {
            "res-1": "broker-a"
        }

    def test_declared_zero_yields_nothing_silently(self, db_path):
        from arkhai_vms_listings.reconciler import derivation_reports

        pool = _declared_pool("broker-a", [("res-1", 0, 0)], tags=_UNBACKED)

        assert _slices(db_path, [pool]) == []
        assert derivation_reports()["site-a"]["members_without_gpu_count"] == {}

    def test_malformed_count_holds_a_whole_fungible_pool(self, db_path):
        pool = _declared_pool(
            "broker-a", [("res-1", 8, 8), ("res-2", "eight", 0)], tags=_UNBACKED
        )
        holds: set = set()

        assert _slices(db_path, [pool], holds=holds) == []
        assert ("pool", "site-a", "broker-a") in holds

    def test_malformed_count_holds_only_its_member_in_a_specific_pool(self, db_path):
        pool = _declared_pool(
            "broker-a",
            [("res-1", 2, 2), ("res-2", "two", 0)],
            tags=_UNBACKED,
            cardinality="specific_resource",
        )
        holds: set = set()

        slices = _slices(db_path, [pool], holds=holds)

        assert {s["resource_id"] for s in slices} == {"res-1"}
        assert holds == {("resource", "site-a", "res-2")}

    def test_key_builders_never_substitute_a_count(self):
        for bad in (None, 0, "1", True):
            with pytest.raises(ValueError):
                listing_pool_key("site-a", "pool-a", bad)


class TestHeldAndWithdrawnListings:
    def test_listings_of_an_unresolvable_pool_are_held_not_closed(self, db_path):
        _seed_listing(db_path, listing_id="held-1", pool_id="broker-a", site_id="site-a")
        declared = _declared_pool("other", [("res-9", 8, 8)], tags=_UNBACKED)
        undeclared = _declared_pool("broker-a", [("res-1", 8, 8)], tags={})

        stale = stale_open_listing_ids(
            db_path,
            home_site="site-a",
            configured_sites=("site-a",),
            backed_only=False,
            site_pool_projection={"site-a": [declared, undeclared]},
        )

        assert "held-1" not in stale

    def test_a_disabled_pools_listings_are_stale(self, db_path):
        _seed_listing(db_path, listing_id="gone-1", pool_id="broker-a", site_id="site-a")
        pool = _declared_pool("broker-a", [("res-1", 8, 8)], tags=_BACKED, enabled=False)

        stale = stale_open_listing_ids(
            db_path,
            home_site="site-a",
            configured_sites=("site-a",),
            backed_only=False,
            site_pool_projection={"site-a": [pool]},
        )

        assert stale == ["gone-1"]

    def test_a_seller_closed_listing_is_never_offered_for_reopen(self, db_path):
        _seed_listing(
            db_path,
            listing_id="withdrawn",
            status="closed",
            closed_by="seller",
            pool_id="pool-b",
            site_id="site-a",
        )
        pool = _declared_pool("pool-b", [("res-1", 8, 8)], tags=_BACKED)

        assert (
            closed_available_listing_ids(
                db_path,
                home_site="site-a",
                site_pool_projection={"site-a": [pool]},
            )
            == []
        )

    def test_a_reconciliation_closed_listing_reopens_when_its_slice_returns(
        self, db_path
    ):
        _seed_listing(
            db_path,
            listing_id="returns",
            status="closed",
            pool_id="pool-b",
            site_id="site-a",
        )
        pool = _declared_pool("pool-b", [("res-1", 8, 8)], tags=_BACKED)

        assert closed_available_listing_ids(
            db_path,
            home_site="site-a",
            site_pool_projection={"site-a": [pool]},
        ) == ["returns"]

    def test_a_listing_whose_published_model_diverged_is_not_reopened(self, db_path):
        _seed_listing(
            db_path,
            listing_id="diverged",
            status="closed",
            pool_id="pool-b",
            site_id="site-a",
        )
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE listings SET listing_resource = ? WHERE listing_id = ?",
                (
                    json.dumps(
                        {
                            "offering_mode": "vm",
                            "gpu_count": 2,
                            "pool_id": "pool-b",
                            "gpu_model": "A100",
                        }
                    ),
                    "diverged",
                ),
            )
            conn.commit()
        finally:
            conn.close()
        pool = _declared_pool("pool-b", [("res-1", 8, 8)], tags=_BACKED)

        assert (
            closed_available_listing_ids(
                db_path,
                home_site="site-a",
                site_pool_projection={"site-a": [pool]},
            )
            == []
        )

    def test_a_stored_key_comes_from_the_binding_not_the_published_fields(self, db_path):
        _seed_listing(db_path, listing_id="countless", pool_id="pool-b", site_id="site-a")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute(
                "UPDATE listings SET listing_resource = ? WHERE listing_id = ?",
                (json.dumps({"offering_mode": "vm", "pool_id": "pool-b"}), "countless"),
            )
            conn.commit()
        finally:
            conn.close()

        # Flattening need not be invertible, so a key is never rebuilt from what
        # the listing publishes.
        assert open_listing_resource_keys(
            db_path, home_site="site-a"
        ) == {_gpu_key("site-a", gpu_count=2, model="H100", pool_id="pool-b")}

    def test_a_listing_bound_before_shapes_keeps_a_key_no_derivation_produces(
        self, db_path
    ):
        _seed_listing(
            db_path, listing_id="v1", pool_id="pool-b", site_id="site-a", schema_version=1
        )

        assert open_listing_resource_keys(
            db_path, home_site="site-a"
        ) == {listing_pool_key("site-a", "pool-b", 2)}


class TestListingShapes:
    def test_a_pool_hint_publishes_its_shapes_and_no_default_shapes(self, db_path):
        pool = _shaped_pool(
            "gpu", [_member("m1", capacity=_BIG)],
            shapes=[_SMALL_SHAPE, {"gpu": {"count": 2, "model": "H100"}, "memory": {"gib": 128}}],
        )

        slices = _shape_slices(db_path, [pool])

        assert len(slices) == 2
        by_count = {row["gpu_count"]: row for row in slices}
        assert (by_count[1]["vcpu_count"], by_count[1]["ram_gb"], by_count[1]["disk_gb"]) == (8, 64, 100)
        # A dimension the shape omits is neither published nor claimed.
        assert "vcpu_count" not in by_count[2] and "disk_gb" not in by_count[2]
        assert by_count[2]["ram_gb"] == 128
        assert {row["shape_source"] for row in slices} == {"pool_hint"}

    def test_a_specific_resource_pool_publishes_per_member_per_feasible_shape(self, db_path):
        pool = _shaped_pool(
            "gpu",
            [_member("big", capacity=_BIG), _member("small", capacity={**_BIG, "ram_gb": 128})],
            shapes=[{"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 256}}],
            cardinality="specific_resource",
        )

        assert [row["resource_id"] for row in _shape_slices(db_path, [pool])] == ["big"]

    def test_default_shapes_reproduce_gpu_only_listings(self, db_path):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)])

        slices = _shape_slices(db_path, [pool])

        assert sorted(row["gpu_count"] for row in slices) == list(range(1, 9))
        for row in slices:
            assert row["listing_shape"] == {"gpu": {"count": row["gpu_count"], "model": "H100"}}
            assert not {"vcpu_count", "ram_gb", "disk_gb"} & set(row)
            assert (row["pool_id"], row["gpu_model"], row["region"]) == ("gpu", "H100", "us-east")

    def test_a_mixed_model_pool_publishes_per_model(self, db_path):
        pool = _shaped_pool(
            "gpu",
            [
                _member("h", capacity={"gpu_count": 2}),
                _member("a", capacity={"gpu_count": 1}, attributes={"gpu_model": "A100"}),
            ],
        )

        published = sorted((row["gpu_model"], row["gpu_count"]) for row in _shape_slices(db_path, [pool]))

        assert published == [("A100", 1), ("H100", 1), ("H100", 2)]

    def test_backed_memory_being_taken_makes_a_stated_shape_unpublishable(self, db_path):
        free = _member("m1", capacity=_BIG, available={**_BIG, "ram_gb": 512})
        taken = _member("m1", capacity=_BIG, available={**_BIG, "ram_gb": 32})

        assert _shape_slices(db_path, [_shaped_pool("gpu", [free], shapes=[_SMALL_SHAPE])])
        assert _shape_slices(db_path, [_shaped_pool("gpu", [taken], shapes=[_SMALL_SHAPE])]) == []

    def test_loaded_buckets_decide_availability_for_every_dimension(self, db_path):
        # The member's own availability says memory is taken, but a loaded bucket
        # family is authoritative for a fungible pool.
        pool = _shaped_pool(
            "gpu", [_member("m1", capacity=_BIG, available={**_BIG, "ram_gb": 0})],
            shapes=[_SMALL_SHAPE],
        )
        bucket = {
            "pool_id": "gpu",
            "resource_type": "compute.gpu",
            "resource_subtype": None,
            "available": {**_BIG, "ram_gb": 128},
            "grouping_attributes": {"gpu_model": "H100", "region": "us-east"},
            "resource_count": 1,
        }

        assert len(_shape_slices(db_path, [pool], buckets=[bucket])) == 1
        low = {**bucket, "available": {**_BIG, "ram_gb": 32}}
        assert _shape_slices(db_path, [pool], buckets=[low]) == []
        # A loaded family naming no entry for the pool means nothing is free.
        assert _shape_slices(db_path, [pool], buckets=[]) == []

    def test_unknown_availability_is_judged_on_declared_capacity(self, db_path):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])

        assert len(_shape_slices(db_path, [pool])) == 1

    def test_an_infeasible_stated_shape_is_reported_with_no_fallback(self, db_path):
        too_big = {"gpu": {"count": 16, "model": "H100"}}
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[too_big])

        assert _shape_slices(db_path, [pool]) == []
        (finding,) = _site_report()["infeasible_shapes"]["gpu"]
        assert finding["shape"] == too_big
        assert finding["not_feasible_against"] == "declared"
        assert finding["shape_digest"] == resolve_shape(too_big).digest

    def test_an_unreadable_hint_holds_the_pool_with_no_fallback(self, db_path):
        pool = _shaped_pool(
            "gpu", [_member("m1", capacity=_BIG)], shapes=[{"tpu": {"count": 1}}]
        )
        holds: set = set()

        assert _shape_slices(db_path, [pool], holds=holds) == []
        assert ("pool", "site-a", "gpu") in holds
        assert _site_report()["unreadable_shapes"]["gpu"]

    def test_editing_a_shape_changes_its_key(self, db_path):
        def key(gib):
            pool = _shaped_pool(
                "gpu", [_member("m1", capacity=_BIG)],
                shapes=[{"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": gib}}],
            )
            (row,) = _shape_slices(db_path, [pool])
            return row["resource_key"]

        assert key(64) != key(96)

    def test_stating_a_default_shape_keeps_its_key(self, db_path):
        members = [_member("m1", capacity={"gpu_count": 1})]
        (default,) = _shape_slices(db_path, [_shaped_pool("gpu", members)])
        (stated,) = _shape_slices(
            db_path,
            [_shaped_pool("gpu", members, shapes=[{"gpu": {"model": "H100", "count": 1}}])],
        )

        assert default["resource_key"] == stated["resource_key"]
        assert default["shape_source"] == "default" and stated["shape_source"] == "pool_hint"

    def test_a_region_only_in_the_pool_hint_publishes_nothing_and_is_reported(self, db_path):
        pool = _shaped_pool(
            "gpu",
            [_member("m1", capacity={"gpu_count": 2}, attributes={"region": None})],
            region="us-west",
        )

        assert _shape_slices(db_path, [pool]) == []
        assert _site_report()["undeclared_attributes"] == {
            "gpu": {"attribute": "region", "value": "us-west"}
        }

    def test_a_default_shape_unavailable_only_on_load_is_not_reported(self, db_path):
        pool = _shaped_pool(
            "gpu", [_member("m1", capacity={"gpu_count": 2}, available={"gpu_count": 0})]
        )

        assert _shape_slices(db_path, [pool]) == []
        report = _site_report()
        assert report["undeclared_attributes"] == {} and report["infeasible_shapes"] == {}

    def test_a_member_without_resource_type_holds_a_fungible_pool(self, db_path):
        pool = _shaped_pool(
            "gpu",
            [_member("m1", capacity={"gpu_count": 2}),
             _member("m2", capacity={"gpu_count": 2}, resource_type=None)],
        )
        holds: set = set()

        assert _shape_slices(db_path, [pool], holds=holds) == []
        assert ("pool", "site-a", "gpu") in holds
        assert _site_report()["members_without_resource_type"] == {"m2": "gpu"}

    def test_a_member_without_resource_type_holds_only_itself_in_a_specific_pool(self, db_path):
        pool = _shaped_pool(
            "gpu",
            [_member("m1", capacity={"gpu_count": 1}),
             _member("m2", capacity={"gpu_count": 1}, resource_type=None)],
            cardinality="specific_resource",
        )
        holds: set = set()

        assert [row["resource_id"] for row in _shape_slices(db_path, [pool], holds=holds)] == ["m1"]
        assert holds == {("resource", "site-a", "m2")}


class TestFamilyRateDerivationThroughTheDatabase:
    """Family rates on the projection path and none on the local-table path,
    read through a real SQLite database."""

    def test_candidates_carry_their_models_resolved_family_rates(self, db_path):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])
        pool["pool_metadata"]["policy_tags"]["pricing"] = {
            "gpu": {"H100": {"rates": _rate("80")}},
            "memory": {"rates": _rate("0.05")},
        }

        (row,) = _shape_slices(db_path, [pool])

        assert row["family_rates"] == {"gpu": _rate("80"), "memory": _rate("0.05")}
        assert "min_price" not in row and "token" not in row

    def test_the_local_table_path_resolves_no_family_rates(self, db_path):
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=2)

        slices = _available_vm_slices(db_path, home_site="site-a")

        assert slices
        assert all(not row.get("family_rates") for row in slices)
        assert all("min_price" not in row and "token" not in row for row in slices)


def _admissibility_default(raw):
    parsed = parse_declaration(raw, tier=CONFIGURED_DEFAULT_TIER, schema=VM_CAPABILITY_SCHEMA)
    assert parsed.declaration is not None, parsed.problems
    return parsed.declaration


def _admitted_slices(db_path, pools, *, default=None, holds=None):
    return available_compute_slices(
        db_path,
        home_site="site-a",
        site_pool_projection={"site-a": pools},
        hint_resolution=PoolHintResolutionSettings(admissibility_default=default),
        holds=holds,
    )


def _published(slices):
    return sorted((row["gpu_model"], row["gpu_count"]) for row in slices)


_A100_MEMBER = _member("a", capacity=_BIG, attributes={"gpu_model": "A100"})
_H100_MEMBER = _member("h", capacity=_BIG)
_A100_PLAIN = {"gpu": {"model": "A100", "count": 1}}


class TestShapeAdmissibility:
    """Per-listing admissibility at publication: a listing whose policy cannot
    be computed, or whose offer its policy excludes, is not derived while the
    pool's other listings publish."""

    def _pool(self, *shapes):
        return _shaped_pool("gpu", [_A100_MEMBER, _H100_MEMBER], shapes=list(shapes))

    def test_a_constrained_stated_shape_publishes_its_offer_and_no_constraint(self, db_path):
        pool = self._pool(
            {"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}},
             "memory": {"gib": {"max": 512}}},
        )

        (row,) = _admitted_slices(db_path, [pool])

        assert (row["gpu_count"], row["gpu_model"]) == (1, "H100")
        assert "ram_gb" not in row
        assert row["listing_shape"] == {"gpu": {"count": 1, "model": "H100"}}
        report = _site_report()
        assert report["inadmissible_listing_shapes"] == {}
        assert report["unusable_shape_constraints"] == {}

    def test_a_listing_narrowing_the_default_publishes(self, db_path):
        pool = self._pool({"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}})
        default = _admissibility_default({"gpu": {"count": {"min": 1, "max": 16}}})

        assert _published(_admitted_slices(db_path, [pool], default=default)) == [("H100", 1)]

    def test_a_configured_default_excludes_a_stated_offer(self, db_path):
        pool = self._pool(_A100_PLAIN, {"gpu": {"model": "H100", "count": 8}})
        default = _admissibility_default({"gpu": {"count": {"max": 4}}})

        assert _published(_admitted_slices(db_path, [pool], default=default)) == [("A100", 1)]
        (finding,) = _site_report()["inadmissible_listing_shapes"]["gpu"]
        assert finding["tier"] == "pool_hint"
        assert finding["shape"] == {"gpu": {"count": 8, "model": "H100"}}
        (problem,) = finding["problems"]
        assert (problem["code"], problem["tier"], problem["paths"]) == (
            "above_maximum", CONFIGURED_DEFAULT_TIER, ["gpu.count"],
        )

    def test_the_default_generator_meets_a_configured_default_and_nothing_is_reported(
        self, db_path
    ):
        pool = _shaped_pool("gpu", [_H100_MEMBER])
        default = _admissibility_default({"gpu": {"count": {"max": 4}}})

        slices = _admitted_slices(db_path, [pool], default=default)

        assert sorted(row["gpu_count"] for row in slices) == [1, 2, 3, 4]
        report = _site_report()
        assert report["inadmissible_listing_shapes"] == {}
        assert report["unusable_shape_constraints"] == {}

    def test_an_empty_merged_range_closes_that_listing_and_names_both_tiers(self, db_path):
        pool = self._pool(_A100_PLAIN, {"gpu": {"model": "H100", "count": {"offer": 1, "max": 2}}})
        default = _admissibility_default({"gpu": {"count": {"min": 4}}})

        assert _published(_admitted_slices(db_path, [pool], default=default)) == []
        findings = _site_report()["unusable_shape_constraints"]["gpu"]
        # The default's minimum also excludes the A100 offer of one, which is
        # reported as inadmissible, not unusable.
        (finding,) = findings
        assert {(bound["tier"], bound["bound"], bound["value"]) for bound in finding["bounds"]} == {
            ("pool_hint", "max", 2), (CONFIGURED_DEFAULT_TIER, "min", 4),
        }
        assert _site_report()["inadmissible_listing_shapes"]["gpu"][0]["shape"] == _A100_PLAIN

    def test_an_unknown_constraint_key_closes_that_listing_alone(self, db_path):
        pool = self._pool(_A100_PLAIN, {"gpu": {"model": "H100", "count": {"offer": 1, "step": 2}}})

        assert _published(_admitted_slices(db_path, [pool])) == [("A100", 1)]
        (finding,) = _site_report()["unusable_shape_constraints"]["gpu"]
        assert (finding["tier"], finding["paths"]) == ("pool_hint", ["gpu.count"])
        assert "'step'" in finding["problem"]

    def test_a_constraint_on_an_undefined_field_closes_that_listing_alone(self, db_path):
        pool = self._pool(
            _A100_PLAIN, {"gpu": {"model": "H100", "count": 1}, "memory": {"foo": {"max": 4}}},
        )

        assert _published(_admitted_slices(db_path, [pool])) == [("A100", 1)]
        assert _site_report()["unusable_shape_constraints"]["gpu"]

    def test_one_base_shape_stated_with_different_constraints_closes_naming_both(self, db_path):
        pool = self._pool(
            {"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}},
            _A100_PLAIN,
            {"gpu": {"model": "H100", "count": {"offer": 1, "max": 8}}},
        )

        assert _published(_admitted_slices(db_path, [pool])) == [("A100", 1)]
        (finding,) = _site_report()["unusable_shape_constraints"]["gpu"]
        assert finding["entries"] == [0, 2]

    def test_identical_entries_collapse_and_are_not_reported(self, db_path):
        constrained = {"gpu": {"model": "H100", "count": {"offer": 1, "max": 4}}}
        pool = self._pool(constrained, constrained)

        assert _published(_admitted_slices(db_path, [pool])) == [("H100", 1)]
        assert _site_report()["unusable_shape_constraints"] == {}

    @pytest.mark.parametrize(
        ("shape", "path"),
        [
            ({"gpu": {"model": {"max": 4}, "count": 1}}, "gpu.model"),
            ({"gpu": {"model": "H100", "count": {"min": 2, "max": 8}}}, "gpu.count"),
        ],
    )
    def test_a_constraint_removing_a_required_field_holds_the_pool(self, db_path, shape, path):
        holds: set = set()

        assert _admitted_slices(db_path, [self._pool(_A100_PLAIN, shape)], holds=holds) == []
        assert ("pool", "site-a", "gpu") in holds
        (problem,) = _site_report()["unreadable_shapes"]["gpu"]
        assert path in problem

    def test_an_override_shape_does_not_inherit_the_hints_constraints(self, db_path):
        pool = _shaped_pool(
            "gpu", [_H100_MEMBER],
            shapes=[{"gpu": {"model": "H100", "count": {"offer": 1, "max": 2}}}],
        )
        rows, report, _ = _override_rows(
            pool, override={"listing_shapes": [{"gpu": {"model": "H100", "count": 4}}]},
        )

        (row,) = rows
        assert [shape.gpu_count for shape in row["feasible_shapes"]] == [4]
        assert report.inadmissible_listing_shapes == {}

    def test_identity_is_kept_across_a_constraint_only_change(self, db_path):
        def key(count):
            pool = _shaped_pool("gpu", [_H100_MEMBER], shapes=[{"gpu": {"model": "H100", "count": count}}])
            (row,) = _admitted_slices(db_path, [pool])
            return row["resource_key"]

        assert key(2) == key({"offer": 2, "max": 4}) == key({"offer": 2, "min": 1, "max": 8})

    def test_an_open_listing_stays_open_while_its_offer_stays_admissible(self, db_path):
        _seed_listing(db_path, listing_id="shaped", pool_id="gpu", gpu_count=2, site_id="site-a")
        pool = _shaped_pool(
            "gpu", [_H100_MEMBER], shapes=[{"gpu": {"model": "H100", "count": {"offer": 2, "max": 8}}}],
        )

        assert stale_open_listing_ids(
            db_path, home_site="site-a", configured_sites=("site-a",), backed_only=False,
            site_pool_projection={"site-a": [pool]},
        ) == []

    def test_the_next_reconciliation_closes_a_listing_whose_offer_became_inadmissible(
        self, db_path
    ):
        _seed_listing(db_path, listing_id="shaped", pool_id="gpu", gpu_count=2, site_id="site-a")
        pool = _shaped_pool("gpu", [_H100_MEMBER], shapes=[{"gpu": {"model": "H100", "count": 2}}])
        reconcile = dict(
            home_site="site-a", configured_sites=("site-a",), backed_only=False,
            site_pool_projection={"site-a": [pool]},
        )

        assert stale_open_listing_ids(db_path, **reconcile) == []
        tightened = _admissibility_default({"gpu": {"count": {"max": 1}}})
        assert stale_open_listing_ids(db_path, admissibility_default=tightened, **reconcile) == [
            "shaped"
        ]

    @pytest.mark.parametrize(
        ("tag", "unreadable"),
        [
            ("asking_rates", {"vm": [{"shape": _A100_PLAIN, "amount": "2", "asset": "usd", "period": "month"}]}),
            ("pricing", {"cpu": {"rates": "not-a-list"}}),
        ],
    )
    def test_an_excluded_listing_closes_though_an_unreadable_rate_holds_its_pool(
        self, db_path, tag, unreadable
    ):
        _seed_listing(db_path, listing_id="kept", pool_id="gpu", gpu_count=1, gpu_model="A100", site_id="site-a")
        _seed_listing(db_path, listing_id="excluded", pool_id="gpu", gpu_count=2, site_id="site-a")
        pool = self._pool(_A100_PLAIN, {"gpu": {"model": "H100", "count": 2}})
        pool["pool_metadata"]["policy_tags"][tag] = unreadable

        assert stale_open_listing_ids(
            db_path, home_site="site-a", configured_sites=("site-a",), backed_only=False,
            site_pool_projection={"site-a": [pool]},
            admissibility_default=_admissibility_default({"gpu": {"count": {"max": 1}}}),
        ) == ["excluded"]

    def test_a_listing_the_default_excludes_is_not_reopened(self, db_path):
        _seed_listing(
            db_path, listing_id="shaped", status="closed", pool_id="gpu", gpu_count=2, site_id="site-a",
        )
        pool = _shaped_pool("gpu", [_H100_MEMBER], shapes=[{"gpu": {"model": "H100", "count": 2}}])
        reopen = dict(home_site="site-a", site_pool_projection={"site-a": [pool]})

        assert closed_available_listing_ids(db_path, **reopen) == ["shaped"]
        excluding = _admissibility_default({"gpu": {"count": {"max": 1}}})
        assert closed_available_listing_ids(db_path, admissibility_default=excluding, **reopen) == []

    def test_local_table_derivation_meets_a_configured_default(self, db_path):
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=8)
        default = _admissibility_default({"gpu": {"count": {"max": 4}}})

        slices = _available_vm_slices(
            db_path,
            home_site="site-a",
            hint_resolution=PoolHintResolutionSettings(admissibility_default=default),
        )

        assert sorted(row["gpu_count"] for row in slices) == [1, 2, 3, 4]

    def test_local_table_derivation_without_a_default_is_unchanged(self, db_path):
        _seed_pool(db_path, pool_id="gpu-pool", gpu_count=3)

        slices = _available_vm_slices(db_path, home_site="site-a")

        assert sorted(row["gpu_count"] for row in slices) == [1, 2, 3]


def test_override_feasibility_is_judged_on_each_shapes_base_shape(db_path):
    pool = _shaped_pool("gpu", [_H100_MEMBER])
    shapes = [
        {"gpu": {"model": "H100", "count": {"offer": 2, "max": 4}}, "memory": {"gib": {"max": 64}}},
        {"gpu": {"model": "H100", "count": {"offer": 16}}},
    ]

    feasible = declared_shape_feasibility(
        db_path,
        [pool],
        site_id="site-a",
        pool_id="gpu",
        home_site="site-a",
        override={"listing_shapes": shapes},
        shape_feasible=_FEASIBILITY,
    )

    assert feasible == {
        resolve_shape({"gpu": {"model": "H100", "count": 2}}).digest: True,
        resolve_shape({"gpu": {"model": "H100", "count": 16}}).digest: False,
    }
