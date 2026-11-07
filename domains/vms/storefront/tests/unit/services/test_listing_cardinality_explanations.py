"""Operator notices for pools whose projected cardinality mode needs one.

Read from a projection state the test builds over fake sites, as the
composition root builds one over its aggregate.
"""

from __future__ import annotations

from market_storefront.services.listing_cardinality_explanations import (
    listing_cardinality_mode_explanations,
)
from tests.fake_site import (
    FakeProjectionSite,
    loaded_site_projection_state,
    site_projection_state,
)


def _site(pools):
    return FakeProjectionSite(resource_pools=pools, capacity_buckets=[])


class TestListingCardinalityModeExplanations:
    async def test_empty_when_nothing_loaded(self):
        state = site_projection_state({"site-a": _site([{"pool_id": "gpu-pool"}])})
        assert listing_cardinality_mode_explanations(state) == {}

    async def test_no_explanation_for_a_recognized_or_absent_cardinality_mode(self):
        state = await loaded_site_projection_state({"site-a": _site([
            {"pool_id": "gpu-pool-a", "resources": []},
            {
                "pool_id": "gpu-pool-b", "resources": [],
                "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "specific_resource"}},
            },
        ])})
        assert listing_cardinality_mode_explanations(state) == {}

    async def test_explanation_for_an_unrecognized_cardinality_mode(self):
        state = await loaded_site_projection_state({"site-a": _site([
            {
                "pool_id": "gpu-pool",
                "resources": [],
                "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "bogus"}},
            },
        ])})
        explanations = listing_cardinality_mode_explanations(state)
        assert set(explanations) == {"site-a"}
        assert "gpu-pool" in explanations["site-a"]
        assert "bogus" in explanations["site-a"]["gpu-pool"]

    async def test_deprecated_key_is_reported_without_a_fallback(self):
        """An unupgraded site emits only the deprecated key. The pool must
        resolve to the cardinality that key names and the operator must be
        told to rename it -- the notice is not a fallback explanation, and
        the pool must not be reclassified to the structural default."""
        state = await loaded_site_projection_state({"site-a": _site([
            {
                "pool_id": "legacy-pool",
                "resources": [],
                "pool_metadata": {
                    "policy_tags": {"listing_mode": "specific_resource"},
                },
            },
        ])})
        notice = listing_cardinality_mode_explanations(state)["site-a"]["legacy-pool"]
        assert "listing_mode" in notice
        assert "listing_cardinality_mode" in notice
        assert "unrecognized" not in notice

    async def test_both_notices_reported_for_a_bad_value_under_the_old_key(self):
        state = await loaded_site_projection_state({"site-a": _site([
            {
                "pool_id": "legacy-bad-pool",
                "resources": [],
                "pool_metadata": {"policy_tags": {"listing_mode": "bogus"}},
            },
        ])})
        notice = listing_cardinality_mode_explanations(state)["site-a"]["legacy-bad-pool"]
        assert "bogus" in notice
        assert "listing_cardinality_mode" in notice

    async def test_one_sites_explanations_do_not_affect_another(self):
        state = await loaded_site_projection_state({
            "site-clean": _site([{"pool_id": "clean-pool", "resources": []}]),
            "site-bad": _site([
                {
                    "pool_id": "bad-pool", "resources": [],
                    "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "bogus"}},
                },
            ]),
        })
        assert set(listing_cardinality_mode_explanations(state)) == {"site-bad"}

    async def test_a_stale_sites_last_generation_is_still_explained(self):
        """The notices describe what the storefront holds, a stale generation
        included, as publication reads it."""
        bad = _site([
            {
                "pool_id": "bad-pool", "resources": [],
                "pool_metadata": {"policy_tags": {"listing_cardinality_mode": "bogus"}},
            },
        ])
        state = await loaded_site_projection_state({"site-a": bad})
        bad.failing = True
        await state.poll_once()

        assert set(listing_cardinality_mode_explanations(state)) == {"site-a"}
