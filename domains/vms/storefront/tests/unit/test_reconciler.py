"""Unit tests for arkhai_vms_listings.reconciler: pure derivation logic.

These exercise transformations over in-memory pools, projections, and
overrides. Cases that read or write a SQLite database are integration tests
(``tests/integration/test_reconciler_derivation.py``).
"""

from __future__ import annotations

import pytest
from market_site.projections import resource_pool_projection
from arkhai_vms_listings.pricing_resolution import GpuPricingFields
from arkhai_vms_listings.reconciler import (
    PoolHintResolutionSettings,
    _fungible_availability_from_buckets,
    _member_available_units,
    _projected_resource_usage,
    listing_pool_key,
    listing_resource_key,
    vm_override_view,
)
from tests._reconciler_cases import (
    _BIG,
    _SMALL_SHAPE,
    _SiteDerivationReport,
    _TOKEN,
    _TWO_GPU_SHAPE,
    _digests,
    _member,
    _override_rows,
    _project_vm_pool_rows,
    _projected_pool_rows,
    _rate,
    _shaped_pool,
    _term,
)


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


class TestProjectedResourceUsage:
    def test_returns_none_without_a_physical_resource_id(self):
        usage = _projected_resource_usage(
            {}, site_id="site-a", member_availability=None,
        )
        assert usage is None

    def test_none_availability_means_fully_available(self):
        usage = _projected_resource_usage(
            {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 8}},
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
                "physical_resource_id": "res-1", "resource_type": "compute.gpu",
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
                "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                "capacity": {"gpu_count": 8},
                "available": {"gpu_count": 5},
            },
            site_id="site-a",
            member_availability=None,
        )
        assert usage.available == 5

    def test_a_derived_declarations_projection_is_read_as_live_availability(self):
        """A host formerly projected from its host row (no ``available``)
        now projects its declaration, which always reports availability.
        Built through the site's own projection so the row is the one the
        storefront receives: the reported figure is used, not a stale
        member lookup, and a present value is never mistaken for unknown."""
        declared = {
            "resource_id": "kvm1",
            "pool_id": "gpu-pool",
            "resource_type": "compute.gpu",
            "capacity": {"gpu_count": 4},
            "available": {"gpu_count": 3},
            "attributes": {"gpu_model": "H200", "host_id": "kvm1"},
            "enabled": True,
        }
        unreported = {**declared, "resource_id": "kvm2"}
        del unreported["available"]
        (pool,) = resource_pool_projection([declared, unreported])
        by_id = {row["physical_resource_id"]: row for row in pool["resources"]}

        live = _projected_resource_usage(
            by_id["kvm1"],
            site_id="site-a",
            member_availability={("site-a", "kvm1"): 4},
        )
        fallback = _projected_resource_usage(
            by_id["kvm2"],
            site_id="site-a",
            member_availability={("site-a", "kvm2"): 1},
        )

        assert (live.total, live.available) == (4, 3)
        assert "available" not in by_id["kvm2"]
        assert fallback.available == 1

    def test_falls_back_to_member_availability_when_no_available_field(self):
        usage = _projected_resource_usage(
            {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 8}},
            site_id="site-a",
            member_availability={("site-a", "res-1"): 2},
        )
        assert usage.available == 2

    def test_usage_carries_no_gpu_model(self):
        """A listing's model comes from its shape, so a member's usage is
        counts alone; a model on the usage would be a second, unread source."""
        usage = _projected_resource_usage(
            {
                "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                "capacity": {"gpu_count": 1},
                "attributes": {"gpu_model": "A100"},
            },
            site_id="site-a", member_availability=None,
        )
        assert not hasattr(usage, "gpu_model")


class TestFungibleAvailabilityFromBuckets:
    def test_none_family_falls_back(self):
        assert _fungible_availability_from_buckets("gpu-pool", None) is None

    def test_loaded_empty_family_is_trusted_zero(self):
        assert _fungible_availability_from_buckets("gpu-pool", []) == (0, 0)

    def test_loaded_family_with_no_matching_pool_is_trusted_zero(self):
        buckets = [
            {"pool_id": "other-pool", "available": {"gpu_count": 9}, "resource_count": 2},
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) == (0, 0)

    def test_matching_readable_bucket_is_used(self):
        buckets = [
            {
                "pool_id": "gpu-pool",
                "available": {"gpu_count": 6},
                "resource_count": 2,
                "grouping_attributes": {"gpu_model": "H100"},
            },
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) == (6, 12)

    def test_max_across_multiple_matching_buckets_not_sum(self):
        buckets = [
            {"pool_id": "gpu-pool", "available": {"gpu_count": 2}, "resource_count": 1},
            {"pool_id": "gpu-pool", "available": {"gpu_count": 6}, "resource_count": 1},
        ]
        max_available, total_available = _fungible_availability_from_buckets(
            "gpu-pool", buckets,
        )
        assert max_available == 6
        assert total_available == 2 + 6

    def test_matching_but_unreadable_bucket_falls_back(self):
        """A bucket entry exists for this pool but predates per-resource
        `available` (empty dict, no `gpu_count` key) -- not the same as
        a confirmed absence, must fall back rather than read as zero."""
        buckets = [
            {"pool_id": "gpu-pool", "available": {}, "resource_count": 1},
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) is None

    def test_one_readable_and_one_unreadable_matching_bucket_uses_the_readable_one(self):
        buckets = [
            {"pool_id": "gpu-pool", "available": {}, "resource_count": 1},
            {"pool_id": "gpu-pool", "available": {"gpu_count": 4}, "resource_count": 1},
        ]
        assert _fungible_availability_from_buckets("gpu-pool", buckets) == (4, 4)


class TestProjectedPoolRows:
    def test_empty_without_a_pool_id(self):
        rows = _project_vm_pool_rows({}, site_id="site-a", member_availability=None, capacity_buckets=None,)
        assert rows == []

    def test_pool_without_vm_deliverable_mode_is_excluded(self):
        rows = _projected_pool_rows(
            {
                "pool_id": "pool-1",
                "resources": [],
                "pool_metadata": {
                    "policy_tags": {"deliverable_modes": ["bare_metal"]}
                },
            },
            site_id="site-a",
            member_availability=None,
            capacity_buckets=None,
        )
        assert rows == []

    def test_a_pool_publishes_from_a_complete_hint_alone(self):
        """A pool with no storefront override still publishes with real
        commercial terms, sourced entirely from its own projected hint."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
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
                                "settlements": ["hint-clause"],
                                "max_duration_seconds": 3600,
                            },
                        },
                    },
                },
            },
        },
        site_id="site-b",
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["region"] == "Nevada, US"
        assert _term(rows[0], "settlements") == ["hint-clause"]
        assert _term(rows[0], "max_duration_seconds") == 3600

    def test_a_pool_without_an_override_publishes_priceless_by_default(self):
        rows = _project_vm_pool_rows({"pool_id": "unpriced", "resources": [
            {
                "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                "capacity": {"gpu_count": 1}, "attributes": {"gpu_model": "H100"},
                "enabled": True,
            },
        ]},
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert _term(rows[0], "max_duration_seconds") is None
        assert rows[0]["sla"] == 0.0

    def test_a_pool_without_an_override_publishes_from_config_default(self):
        rows = _project_vm_pool_rows({
            "pool_id": "unpriced",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "A100"},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            gpu_pricing_defaults_by_model={
                "A100": GpuPricingFields(max_duration_seconds=1800),
            },
        ),)
        assert len(rows) == 1
        assert _term(rows[0], "max_duration_seconds") == 1800

    def test_builds_one_fungible_row_for_a_pool_with_an_override(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
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
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a",
        override={"max_duration_seconds": 3600},
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        row = rows[0]
        assert row["pool_id"] == "gpu-pool"
        assert row["site_id"] == "site-a"
        assert row["total_gpu_count"] == 4
        assert _term(row, "max_duration_seconds") == 3600
        assert row["listing_cardinality_mode"] == "fungible"
        assert row["listing_cardinality_mode_explanation"] is None
        assert row["single_resource_id"] is None

    def test_single_member_pool_defaults_to_specific_resource_without_a_tag(self):
        """Backward compatibility: `available_compute_slices` always
        treated a single-member pool as specific-resource before
        the cardinality tag existed (`member_count == 1` heuristic). An
        untagged pool with exactly one member must keep resolving that
        way, or an existing derived-listing mapping keyed on that
        resource's identity would silently break the moment a
        projection without `pool_metadata` reaches this function."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["listing_cardinality_mode"] == "specific_resource"
        assert rows[0]["single_resource_id"] == "res-1"

    def test_multi_member_pool_defaults_to_fungible_without_a_tag(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "enabled": True,
                },
                {
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["listing_cardinality_mode"] == "fungible"
        assert rows[0]["single_resource_id"] is None

    def test_disabled_resources_are_excluded(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "enabled": False,
                },
            ],
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["total_gpu_count"] == 0
        assert rows[0]["member_count"] == 0

    def test_the_listing_model_is_the_members(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "A100"},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert {shape.gpu_model for shape in rows[0]["listing_shapes"]} == {"A100"}
        assert set(rows[0]["pricing_by_model"]) == {"A100"}

    def test_a_member_without_a_model_yields_no_shape(self):
        """A shape names a model only from a member's declaration."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert rows[0]["listing_shapes"] == ()
        assert rows[0]["pricing_by_model"] == {}

    # -- region/sla hint resolution ---------------------------------------

    def test_region_is_the_pools_hint(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
            "pool_metadata": {"policy_tags": {"region": "Nevada, US"}},
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert rows[0]["region"] == "Nevada, US"

    def test_a_pool_without_a_region_hint_is_held(self):
        holds: set = set()
        report = _SiteDerivationReport()
        rows = _projected_pool_rows({
            "pool_id": "gpu-pool",
            "pool_metadata": {"policy_tags": {"deliverable_modes": ["vm"]}},
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4},
                 "attributes": {"gpu_model": "H100", "region": "us-east"}, "enabled": True},
            ],
        },
        site_id="site-a", holds=holds, report=report,
        member_availability=None, capacity_buckets=None,)
        assert rows == []
        assert holds == {("pool", "site-a", "gpu-pool")}
        assert report.as_dict()["regionless_pools"] == ["gpu-pool"]

    def test_sla_storefront_override_wins_over_pool_hint_by_default(self):
        """No hint_resolution passed -- the default settings apply, and
        the storefront's per-pool override takes precedence over any
        pool-declared hint regardless of the (default-closed) trust gate."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
            "pool_metadata": {"policy_tags": {"sla": 50.0}},
        },
        site_id="site-a",
        override={"sla": 99.9},
        member_availability=None, capacity_buckets=None,)
        assert rows[0]["sla"] == 99.9

    def test_sla_pool_hint_used_when_no_local_override_and_gate_open(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
            "pool_metadata": {"policy_tags": {"sla": 95.0}},
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            accept_pool_declared_sla=True, default_sla=0.0,
        ),)
        assert rows[0]["sla"] == 95.0

    def test_sla_pool_hint_ignored_when_gate_closed_even_with_no_override(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
            "pool_metadata": {"policy_tags": {"sla": 95.0}},
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            accept_pool_declared_sla=False, default_sla=12.5,
        ),)
        assert rows[0]["sla"] == 12.5

    def test_sla_falls_back_to_config_default_with_no_override_or_hint(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            accept_pool_declared_sla=True, default_sla=42.0,
        ),)
        assert rows[0]["sla"] == 42.0

    # -- pricing hint resolution ------------------------------------------

    def test_pricing_storefront_override_wins_over_pool_hint(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"}, "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {"pricing": {"gpu": {"H100": {"max_duration_seconds": 1800}}}},
            },
        },
        site_id="site-a",
        override={"max_duration_seconds": 7200},
        member_availability=None, capacity_buckets=None,)
        assert _term(rows[0], "max_duration_seconds") == 7200

    def test_pricing_pool_hint_used_when_no_storefront_override(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"}, "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {"pricing": {"gpu": {"H100": {"max_duration_seconds": 1800}}}},
            },
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert _term(rows[0], "max_duration_seconds") == 1800

    def test_pricing_falls_back_to_per_model_config_default(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"}, "enabled": True,
                },
            ],
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            gpu_pricing_defaults_by_model={
                "H100": GpuPricingFields(max_duration_seconds=900),
            },
        ),)
        assert _term(rows[0], "max_duration_seconds") == 900

    def test_pricing_falls_back_to_flat_config_default_as_last_resort(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4},
                    "attributes": {"gpu_model": "H100"}, "enabled": True,
                },
            ],
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,
        hint_resolution=PoolHintResolutionSettings(
            gpu_pricing_flat_default=GpuPricingFields(max_duration_seconds=60),
        ),)
        assert _term(rows[0], "max_duration_seconds") == 60

    def test_specific_resource_multi_member_prices_each_by_its_own_model(self):
        """Two members with different GPU models must resolve pricing
        independently -- proving pricing resolution is per-row, not
        computed once for the whole pool."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"}, "enabled": True,
                },
                {
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu", "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "A100"}, "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {
                    "listing_cardinality_mode": "specific_resource",
                    "pricing": {
                        "gpu": {
                            "H100": {"max_duration_seconds": 3600},
                            "A100": {"max_duration_seconds": 1800},
                        },
                    },
                },
            },
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        # Every row carries each model's terms; a listing takes its shape's.
        pricing = rows[0]["pricing_by_model"]
        assert (
            pricing["H100"].max_duration_seconds,
            pricing["A100"].max_duration_seconds,
        ) == (3600, 1800)

    # -- listing_cardinality_mode resolution --------------------------------------

    def test_unrecognized_cardinality_mode_falls_back_with_explanation(self):
        """One member -> structural default is specific_resource (see
        test_single_member_pool_defaults_to_specific_resource_without_a_tag)
        -- an unrecognized explicit value falls back to *that* default,
        not a hardcoded constant."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "bogus"}},
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["listing_cardinality_mode"] == "specific_resource"
        assert rows[0]["listing_cardinality_mode_explanation"] is not None
        assert "bogus" in rows[0]["listing_cardinality_mode_explanation"]

    def test_unrecognized_cardinality_mode_falls_back_to_fungible_for_multi_member(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {"physical_resource_id": "res-1", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
                {"physical_resource_id": "res-2", "resource_type": "compute.gpu", "capacity": {"gpu_count": 4}, "enabled": True},
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "bogus"}},
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["listing_cardinality_mode"] == "fungible"
        assert rows[0]["listing_cardinality_mode_explanation"] is not None
        assert "bogus" in rows[0]["listing_cardinality_mode_explanation"]

    # -- specific_resource, including multi-member ----------------------

    def test_specific_resource_single_member_yields_one_resource_keyed_row(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {"listing_cardinality_mode": "specific_resource"},
            },
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["single_resource_id"] == "res-1"
        assert rows[0]["listing_cardinality_mode"] == "specific_resource"

    def test_specific_resource_multi_member_yields_one_row_per_member(self):
        """A multi-member pool declared specific_resource must publish
        one independently identified row per member, not collapse to a
        single aggregate the way fungible mode does."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "available": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
                {
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "available": {"gpu_count": 6},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
                {
                    "physical_resource_id": "res-3", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "available": {"gpu_count": 0},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
            ],
            "pool_metadata": {
                "policy_tags": {"listing_cardinality_mode": "specific_resource"},
            },
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
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
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "enabled": True,
                },
                {
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "enabled": False,
                },
            ],
            "pool_metadata": {
                "policy_tags": {"listing_cardinality_mode": "specific_resource"},
            },
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert len(rows) == 1
        assert rows[0]["single_resource_id"] == "res-1"

    # -- fungible mode sourced from site_capacity_buckets ----------------

    def test_fungible_prefers_bucket_availability_over_resource_walk(self):
        """The max_member_available ceiling must reflect a single bucket's
        (i.e. a single member's) availability, not a sum across buckets,
        and must come from the bucket data when it's usable."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
                {
                    "physical_resource_id": "res-2", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "attributes": {"gpu_model": "H100"},
                    "enabled": True,
                },
            ],
        },
        site_id="site-a",
        member_availability=None,
        capacity_buckets=[
            {
                "pool_id": "gpu-pool",
                "available": {"gpu_count": 2},
                "resource_count": 1,
                "grouping_attributes": {"gpu_model": "H100"},
            },
            {
                "pool_id": "gpu-pool",
                "available": {"gpu_count": 6},
                "resource_count": 1,
                "grouping_attributes": {"gpu_model": "H100"},
            },
        ],)
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
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a",
        member_availability=None,
        capacity_buckets=[
            {
                "pool_id": "other-pool",
                "available": {"gpu_count": 99},
                "resource_count": 5,
            },
        ],)
        assert rows[0]["max_member_available_gpu_count"] == 0
        assert rows[0]["available_gpu_count"] == 0

    def test_fungible_trusts_zero_when_family_loaded_as_a_whole_empty_list(self):
        """The site-wide "authoritative zero buckets anywhere" case --
        e.g. the capacity-bucket family loaded successfully but the site
        currently has no enabled resources at all. Must be trusted the
        same way a per-pool absence is, not treated as unknown."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 8},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a",
        member_availability=None,
        capacity_buckets=[],)
        assert rows[0]["max_member_available_gpu_count"] == 0
        assert rows[0]["available_gpu_count"] == 0

    def test_fungible_falls_back_to_resource_walk_when_no_bucket_data(self):
        """No site_capacity_buckets supplied at all (None) -- must not
        publish zero capacity, must use the pre-existing computation."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "available": {"gpu_count": 3},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a",
        member_availability=None, capacity_buckets=None,)
        assert rows[0]["max_member_available_gpu_count"] == 3

    def test_fungible_falls_back_when_bucket_predates_available_field(self):
        """A bucket whose `available` dict lacks `gpu_count` entirely
        (an older producer that never emitted per-resource availability)
        must not be read as an authoritative zero -- falls back to the
        resource-list computation instead."""
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "available": {"gpu_count": 4},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a",
        member_availability=None,
        capacity_buckets=[
            {"pool_id": "gpu-pool", "available": {}, "resource_count": 1},
        ],)
        assert rows[0]["max_member_available_gpu_count"] == 4

    def test_fungible_trusts_a_genuine_zero_from_buckets(self):
        rows = _project_vm_pool_rows({
            "pool_id": "gpu-pool",
            "resources": [
                {
                    "physical_resource_id": "res-1", "resource_type": "compute.gpu",
                    "capacity": {"gpu_count": 4},
                    "available": {"gpu_count": 4},
                    "enabled": True,
                },
            ],
            "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "fungible"}},
        },
        site_id="site-a",
        member_availability=None,
        capacity_buckets=[
            {
                "pool_id": "gpu-pool",
                "available": {"gpu_count": 0},
                "resource_count": 1,
            },
        ],)
        # A real zero from a usable bucket is trusted, even though the
        # resource-list walk (never consulted for max/available once a
        # usable bucket exists) would have said 4.
        assert rows[0]["max_member_available_gpu_count"] == 0
        assert rows[0]["available_gpu_count"] == 0


def test_structural_keys_are_byte_identical_to_stored_keys():
    # Stored listings are found by these exact strings; the shared encoding must
    # reproduce them byte for byte, including for delimiter-bearing identifiers.
    assert listing_pool_key("site-a", "b:c", 2) == "pool:6:site-a:3:b:c:gpus:2"
    assert listing_resource_key("s", "r:1", 1) == "1:s:3:r:1:gpus:1"


class TestFamilyRateDerivation:
    """Family rates resolve per GPU model on the projection path and ride on
    each candidate; the local-table path never resolves them."""

    def test_an_override_states_rates_above_the_hint(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])
        pool["pool_metadata"]["policy_tags"]["pricing"] = {
            "gpu": {"H100": {"rates": _rate("80")}},
        }

        (row,), _report, _ = _override_rows(
            pool, override={"pricing": {"gpu": {"H100": {"rates": _rate("90")}}}}
        )

        assert row["family_rates_by_model"]["H100"]["gpu"] == tuple(_rate("90"))

    def test_configured_family_rates_are_the_lowest_tier(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])

        (row,), _report, _ = _override_rows(
            pool,
            hint_resolution=PoolHintResolutionSettings(
                family_rate_defaults={"cpu": {"rates": _rate("0.5")}},
            ),
        )

        assert row["family_rates_by_model"]["H100"] == {"cpu": tuple(_rate("0.5"))}

    def test_retired_pricing_keys_are_reported_without_holding(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])
        pool["pool_metadata"]["policy_tags"]["pricing"] = {
            "gpu": {"H100": {"min_price": "5", "token": "0xhint"}},
        }

        (row,), report, holds = _override_rows(
            pool, override={"retired_terms": ("min_price",)}
        )

        assert holds == set()
        assert row["family_rates_by_model"]["H100"] == {}
        assert report.retired_pricing_keys == {
            "gpu": [
                "override terms.min_price",
                "hint pricing.gpu.H100.min_price",
                "hint pricing.gpu.H100.token",
            ]
        }
        assert report.as_dict()["retired_pricing_keys"]["gpu"]

    def test_an_unreadable_hint_rate_holds_the_pool_rather_than_falling_through(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])
        pool["pool_metadata"]["policy_tags"]["pricing"] = {"cpu": {"rates": "not-a-list"}}

        rows, report, holds = _override_rows(
            pool,
            hint_resolution=PoolHintResolutionSettings(
                family_rate_defaults={"cpu": {"rates": _rate("0.5")}},
            ),
        )

        # The configured default is a price nobody stated for this pool.
        assert rows == []
        assert ("pool", "site-a", "gpu") in holds
        (problem,) = report.unreadable_family_rates["gpu"]
        assert problem.startswith("hint pricing.cpu")
        assert report.as_dict()["unreadable_family_rates"]["gpu"] == [problem]

    @pytest.mark.parametrize(
        ("pricing", "fragment"),
        [
            ({"fpga": {"rates": _rate("1")}}, "no VM family is priced by it"),
            ({"gpu": {"rates": _rate("1")}}, "must be stated per model"),
            (
                {"cpu": {"rates": [{"asset": _TOKEN, "rate": "1", "per": "request"}]}},
                "time unit",
            ),
        ],
    )
    def test_rates_no_vm_family_is_priced_by_hold_the_pool(self, pricing, fragment):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])
        pool["pool_metadata"]["policy_tags"]["pricing"] = pricing

        rows, report, holds = _override_rows(pool)

        assert rows == []
        assert ("pool", "site-a", "gpu") in holds
        assert fragment in report.unreadable_family_rates["gpu"][0]

    def test_families_without_a_rate_are_reported_per_asset(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])
        pool["pool_metadata"]["policy_tags"]["pricing"] = {
            "gpu": {"H100": {
                "rates": _rate("80"),
                "settlements": [{"mechanism": "alkahest.v1", "asset": _TOKEN}],
            }},
            "memory": {"rates": _rate("0.05")},
        }

        (row,), report, holds = _override_rows(pool)

        assert holds == set()
        (entry,) = report.families_without_rates["gpu"]
        assert (entry["asset"], entry["families"]) == (_TOKEN, ["cpu", "storage"])

    def test_a_stored_override_with_retired_terms_is_read_not_held(self):
        view = vm_override_view(
            listing_shapes=None,
            settlements=None,
            terms={"min_price": "4", "token": "0xold", "sla": 99.0},
        )
        assert view["retired_terms"] == ("min_price", "token")
        assert view["sla"] == 99.0
        assert "min_price" not in view and "token" not in view


class TestStorefrontOverrideTier:
    """The site-scoped override is the first shape and term tier."""

    def test_an_override_replaces_the_pool_hint_whole(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE, _TWO_GPU_SHAPE])

        (row,), _, _ = _override_rows(pool, override={"listing_shapes": [_TWO_GPU_SHAPE]})

        assert row["shape_source"] == "storefront_override"
        assert [shape.shape for shape in row["listing_shapes"]] == [_TWO_GPU_SHAPE]

    def test_an_override_stating_the_hints_shape_keeps_its_key(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])

        (hinted,), _, _ = _override_rows(pool)
        (overridden,), _, _ = _override_rows(pool, override={"listing_shapes": [_SMALL_SHAPE]})

        # Keys depend only on the shape digest, not on the tier that stated it.
        assert _digests(overridden["feasible_shapes"]) == _digests(hinted["feasible_shapes"])

    def test_an_override_without_shapes_leaves_the_hint_in_place(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])

        (row,), _, _ = _override_rows(pool, override={"sla": 99.0})

        assert row["shape_source"] == "pool_hint"

    def test_an_unreadable_stored_override_holds_the_pool_and_is_reported(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)], shapes=[_SMALL_SHAPE])

        rows, report, holds = _override_rows(
            pool, override={"listing_shapes": [{"gpu": {"count": 1, "model": "H100"}, "fpga": {}}]}
        )

        assert rows == []
        assert ("pool", "site-a", "gpu") in holds
        (problem,) = report.unreadable_shapes["gpu"]
        assert problem.startswith("storefront_override: ")

    def test_commercial_fields_merge_over_the_hint_field_by_field(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity={"gpu_count": 1})])
        pool["pool_metadata"]["policy_tags"]["pricing"] = {
            "gpu": {"H100": {"max_duration_seconds": 3600, "settlements": ["hint-clause"]}}
        }

        (row,), _, _ = _override_rows(
            pool, override={"settlements": ["override-clause"], "sla": 99.5},
            hint_resolution=PoolHintResolutionSettings(),
        )

        terms = row["pricing_by_model"]["H100"]
        assert (terms.settlements, terms.max_duration_seconds) == (["override-clause"], 3600)
        assert row["sla"] == 99.5

    def test_an_override_at_a_non_home_site_applies(self):
        pool = _shaped_pool("gpu", [_member("m1", capacity=_BIG)])

        (row,), report, _ = _override_rows(
            pool,
            site_id="site-b",
            override={"listing_shapes": [_SMALL_SHAPE], "max_duration_seconds": 900},
        )

        assert [shape.shape for shape in row["listing_shapes"]] == [_SMALL_SHAPE]
        assert row["pricing_by_model"]["H100"].max_duration_seconds == 900
