"""The route service's handling over a service double: status per outcome."""

from __future__ import annotations

import pytest

from market_pool_overrides import (
    PoolOverrideRecord,
    PoolOverrideRouteError,
    PoolOverrideRouteService,
)
from market_pool_overrides.service import PoolOverrideRefused

pytestmark = pytest.mark.asyncio

_STORED = {
    "site_id": "s", "pool_id": "p", "offering_mode": "vm",
    "listing_shapes": None, "settlements": None, "asking_rates": [], "terms": None,
    "created_at": "t", "updated_at": "t",
}


class _Service:
    def __init__(self, *, refuse: PoolOverrideRefused | None = None, stored=None):
        self.refuse = refuse
        self.stored = stored
        self.deleted = []

    async def replace(self, record):
        if self.refuse:
            raise self.refuse
        return {"override": {**_STORED, **record.model_dump()}, "feasibility": [],
                "projection": {"revision": 1, "digest": "d"}}

    async def get(self, address):
        return self.stored

    async def list(self, *, site_id=None, pool_id=None):
        return [self.stored] if self.stored else []

    async def delete(self, address):
        self.deleted.append(address)
        return True


async def _refused(call) -> PoolOverrideRouteError:
    with pytest.raises(PoolOverrideRouteError) as caught:
        await call
    return caught.value


async def test_without_a_service_every_operation_is_unavailable():
    routes = PoolOverrideRouteService(None)
    assert (await _refused(routes.read())).status_code == 503
    assert (await _refused(routes.replace({}))).status_code == 503
    assert (await _refused(routes.delete(site_id="s", pool_id="p", offering_mode="vm"))
            ).status_code == 503


async def test_a_body_that_is_not_a_record_is_refused_with_422():
    routes = PoolOverrideRouteService(_Service())
    refused = await _refused(routes.replace({"site_id": "s", "pool_id": "p",
                                             "offering_mode": "vm", "region": "x"}))
    assert refused.status_code == 422


async def test_a_service_refusal_keeps_its_status():
    routes = PoolOverrideRouteService(_Service(refuse=PoolOverrideRefused(404, "no pool")))
    record = PoolOverrideRecord(site_id="s", pool_id="p", offering_mode="vm", asking_rates=[])
    refused = await _refused(routes.replace(record))
    assert (refused.status_code, refused.detail) == (404, "no pool")


async def test_an_accepted_raw_body_and_record_answer_alike():
    routes = PoolOverrideRouteService(_Service())
    body = {"site_id": "s", "pool_id": "p", "offering_mode": "vm", "asking_rates": []}
    from_raw = await routes.replace(body)
    from_record = await routes.replace(PoolOverrideRecord.model_validate(body))
    assert from_raw == from_record
    assert from_raw.override.asking_rates == []


async def test_reading_an_absent_override_is_404_and_a_partial_address_lists():
    routes = PoolOverrideRouteService(_Service())
    assert (await _refused(routes.read(site_id="s", pool_id="p", offering_mode="vm"))
            ).status_code == 404
    assert (await routes.read(site_id="s")).overrides == []


async def test_a_delete_requires_the_whole_address():
    service = _Service()
    routes = PoolOverrideRouteService(service)
    refused = await _refused(routes.delete(site_id="s", pool_id=None, offering_mode="vm"))
    assert refused.status_code == 400
    assert service.deleted == []
    deleted = await routes.delete(site_id="s", pool_id="p", offering_mode="vm")
    assert deleted.deleted is True


async def test_an_address_with_nul_is_refused_with_400():
    routes = PoolOverrideRouteService(_Service())
    refused = await _refused(routes.read(site_id="s\x00", pool_id="p", offering_mode="vm"))
    assert refused.status_code == 400
