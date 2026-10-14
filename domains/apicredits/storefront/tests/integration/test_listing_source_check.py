"""An API-credit listing is rechecked against its own source.

External boundary: a real SQLite repository holding the listing and its
binding; the credits site is a fake answering its pool projection and quota
snapshot.
"""

from __future__ import annotations

import pytest

from apicredits_storefront.listing_source_check import build_listing_source_check
from tests.integration.credit_negotiation import FakeCapacity


class _Site(FakeCapacity):
    def __init__(self, *, available=100, backing="backed", advertised=("api_credits",)):
        super().__init__(available)
        self.backing = backing
        self.advertised = list(advertised)
        self.reachable = True

    async def resource_pool_projection(self):
        if not self.reachable:
            raise ConnectionError("site unreachable")
        projection = await super().resource_pool_projection()
        tags = projection["resource_pools"][0]["pool_metadata"]["policy_tags"]
        tags["capacity_backing"] = self.backing
        tags["advertisable_modes"] = self.advertised
        tags["deliverable_modes"] = self.advertised if self.backing == "backed" else []
        return projection


async def _check(db, site):
    return await build_listing_source_check(lambda _repository: site)(db, "L-tok")


async def test_an_unchanged_source_matches(db):
    assert (await _check(db, _Site())).outcome == "matches"


async def test_a_pool_that_stops_advertising_api_credits_is_a_declared_mismatch(db):
    verdict = await _check(db, _Site(advertised=("vm",)))

    assert verdict.outcome == "declared_mismatch"


async def test_exhausted_quota_is_unavailable(db):
    verdict = await _check(db, _Site(available=0))

    assert verdict.outcome == "unavailable"


async def test_an_unreachable_site_is_unverifiable(db):
    site = _Site()
    site.reachable = False

    assert (await _check(db, site)).outcome == "unverifiable"


async def test_a_pool_declaring_the_opposite_backing_is_a_declared_mismatch(db):
    verdict = await _check(db, _Site(backing="unbacked"))

    assert verdict.outcome == "declared_mismatch"
    assert verdict.differing_fields == ("capacity_backing",)


@pytest.mark.parametrize("site_id", ["elsewhere"])
async def test_an_unconfigured_site_is_unverifiable(db, site_id):
    site = _Site()
    site.site_names = [site_id]

    assert (await _check(db, site)).outcome == "unverifiable"
