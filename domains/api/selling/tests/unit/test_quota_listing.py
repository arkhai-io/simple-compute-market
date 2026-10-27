"""The quota listing's binding and reconciliation, under a neutral domain's bundle."""

from __future__ import annotations

import json

import pytest
from market_resource_pools import ResolvedPool
from market_resource_pools_contracts.backing import BACKED, UNBACKED

from arkhai_api_selling.issuance import MissingQuotaResource
from arkhai_api_selling.quota_listing import (
    QuotaListingSource,
    build_listing_source_check,
    QuotaPool,
    QuotaPoolUnavailable,
    prepare_listing_binding,
    quota_pool,
    registration,
    reopenable_listing_ids,
    stale_open_listing_ids,
)
from tests.bundles import DOMAIN, EXAMPLE


POOL = QuotaPool("default", ResolvedPool(BACKED, frozenset({"example"}), True))


def _pools(*, advertised=("example",), pool_id="default"):
    return [
        {
            "pool_id": pool_id,
            "resources": [{"physical_resource_id": "quota-a"}],
            "pool_metadata": {
                "enabled": True,
                "policy_tags": {
                    "deliverable_modes": list(advertised),
                    "advertisable_modes": list(advertised),
                    "capacity_backing": "backed",
                },
            },
        }
    ]


def test_the_quota_pool_advertises_the_bundles_offering_mode():
    pool = quota_pool(EXAMPLE, _pools(), resource_id="quota-a")
    assert pool.pool_id == "default"
    assert pool.declaration.backing is BACKED
    with pytest.raises(QuotaPoolUnavailable, match="does not advertise 'example'"):
        quota_pool(EXAMPLE, _pools(advertised=("other",)), resource_id="quota-a")
    with pytest.raises(QuotaPoolUnavailable, match="no longer in its pool 'default'"):
        quota_pool(EXAMPLE, _pools(pool_id="other"), resource_id="quota-a", pool_id="default")


def test_the_registration_is_the_bundles_offering_mode_and_contribution():
    registered = registration(EXAMPLE, DOMAIN)
    assert registered.offering_mode == "example"
    assert registered.contribution_id == "example"


def test_a_binding_records_the_projected_quota_resource_under_the_bundles_source_kind():
    binding = prepare_listing_binding(
        EXAMPLE,
        listing_id="L-1",
        site_id="quota",
        listing_resource={"product": "alpha", "quota": "quota-a"},
        pool=POOL,
        domain=DOMAIN,
    )
    assert binding.physical_resource_id == "quota-a"
    assert binding.pool_id == "default"
    assert binding.binding.offering_mode == "example"
    assert json.loads(binding.source_envelope_json)["kind"] == "example.quota-listing.v1"
    assert binding.capacity_backing == BACKED.label


def test_a_listing_naming_no_quota_resource_is_refused_before_publication():
    with pytest.raises(MissingQuotaResource, match="listing 'L-2' names no quota resource"):
        prepare_listing_binding(
            EXAMPLE,
            listing_id="L-2",
            site_id="quota",
            listing_resource={"product": "alpha"},
            pool=POOL,
            domain=DOMAIN,
        )


# Reconciliation


def _source(listing_id, resource_id, status, closed_by=None):
    return QuotaListingSource(listing_id, status, closed_by, "quota", resource_id)


def _judge(backing):
    return lambda _source, available: backing.judge(lambda: None, available)


def test_exhaustion_closes_and_replenishment_reopens():
    sources = [
        _source("L-a", "quota-a", "open"),
        _source("L-b", "quota-b", "open"),
        _source("L-c", "quota-a", "closed", "reconciliation"),
    ]
    judge = _judge(BACKED)
    availability = {("quota", "quota-a"): 0, ("quota", "quota-b"): 12}
    assert stale_open_listing_ids(sources, availability=availability, judge=judge) == ["L-a"]
    assert reopenable_listing_ids(sources, availability=availability, judge=judge) == []

    availability = {("quota", "quota-a"): 3, ("quota", "quota-b"): 12}
    assert stale_open_listing_ids(sources, availability=availability, judge=judge) == []
    assert reopenable_listing_ids(sources, availability=availability, judge=judge) == ["L-c"]


def test_only_what_reconciliation_closed_reopens():
    sources = [
        _source("L-seller", "quota-a", "closed", "seller"),
        _source("L-quota", "quota-a", "closed", "reconciliation"),
    ]
    assert reopenable_listing_ids(
        sources, availability={("quota", "quota-a"): 5}, judge=_judge(BACKED)
    ) == ["L-quota"]


def test_unknown_availability_closes_and_reopens_nothing_and_a_missing_resource_closes():
    sources = [_source("L-a", "quota-a", "open")]
    judge = _judge(BACKED)
    assert stale_open_listing_ids(sources, availability=None, judge=judge) == []
    assert reopenable_listing_ids(sources, availability=None, judge=judge) == []
    assert stale_open_listing_ids(sources, availability={}, judge=judge) == ["L-a"]


def test_availability_closes_no_listing_its_backing_does_not_bound():
    sources = [_source("L-a", "quota-a", "open")]
    assert stale_open_listing_ids(sources, availability={}, judge=_judge(UNBACKED)) == []


# The source check


class _Repository:
    """A storefront's stored listing and its durable binding."""

    def __init__(self, listing_resource):
        self.listing_resource = listing_resource
        self.durable = prepare_listing_binding(
            EXAMPLE,
            listing_id="L-1",
            site_id="quota",
            listing_resource={"product": "alpha", "quota": "quota-a"},
            pool=POOL,
            domain=DOMAIN,
        )

    async def load_listing_binding(self, *, listing_id):
        return self.durable

    async def load_listing(self, *, listing_id):
        return {"listing_id": listing_id, "listing_resource": json.dumps(self.listing_resource)}


class _Site:
    def __init__(self, available=5):
        self.available = available

    async def resource_pool_projection(self):
        return {"resource_pools": _pools()}

    async def snapshot(self):
        return [{"resource_id": "quota-a", "available_units": self.available}]


class _Capacity:
    def __init__(self, site):
        self._site = site

    def site(self, site_id):
        if site_id != "quota":
            raise KeyError(site_id)
        return self._site


async def _check(listing_resource, site=None):
    check = build_listing_source_check(EXAMPLE, lambda _repository: _Capacity(site or _Site()))
    return await check(_Repository(listing_resource), "L-1")


async def test_a_listing_matching_its_binding_and_pool_matches():
    assert (await _check({"product": "alpha", "quota": "quota-a"})).outcome == "matches"


async def test_a_listing_naming_no_quota_resource_is_refused_before_acceptance():
    verdict = await _check({"product": "alpha"})
    assert verdict.outcome == "declared_mismatch"
    assert "names no quota resource" in verdict.reason


async def test_a_listing_naming_another_quota_resource_than_its_binding_is_refused():
    verdict = await _check({"product": "alpha", "quota": "quota-b"})
    assert verdict.outcome == "declared_mismatch"
    assert "other than its binding" in verdict.reason


async def test_exhausted_quota_is_unavailable():
    verdict = await _check({"product": "alpha", "quota": "quota-a"}, _Site(available=0))
    assert verdict.outcome == "unavailable"
