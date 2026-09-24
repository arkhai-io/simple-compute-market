"""PoolOverrideService: the write check order, its effects, and override status.

Collaborators are injected mocks, so these tests prove the order of checks and
which collaborator each step reaches. The typed-client path through a real
application and database is proven in
``tests/integration/test_pool_overrides_api.py``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from arkhai_vms import vm_shape_digest
from market_site_client import SiteCapacityAuthenticationError, SiteCapacityClientError

from market_storefront.models.pool_override_models import PoolOverrideRecord
from market_storefront.services.pool_override_service import (
    OVERRIDE_APPLIED,
    OVERRIDE_INACTIVE,
    OVERRIDE_ORPHANED,
    OVERRIDE_SITE_UNCONFIGURED,
    OVERRIDE_UNKNOWN,
    PoolOverrideRefused,
    PoolOverrideService,
    override_state,
)

SHAPE = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 64}}
LIVE = {"revision": 7, "digest": "live-7", "resource_pools": [{"resource_pool_id": "gpu"}]}


class _World:
    """The service with every collaborator a mock, recording call order."""

    def __init__(self, *, site_ids=("site-a", "site-b"), live=LIVE, projection=None):
        self.calls: list[str] = []
        self.db = MagicMock()
        self.db.replace_pool_override = AsyncMock(
            side_effect=lambda values: self.calls.append("store")
            or {**values, "created_at": "t0", "updated_at": "t0"}
        )
        self.db.delete_pool_override = AsyncMock(return_value=True)
        self.db.list_pool_overrides = AsyncMock(return_value=[])
        self.site = MagicMock()
        if isinstance(live, Exception):
            self.site.resource_pool_projection = AsyncMock(side_effect=live)
        else:
            self.site.resource_pool_projection = AsyncMock(return_value=live)
        self.runtime = MagicMock()
        self.runtime.site_ids = site_ids
        self.runtime.site_client = MagicMock(return_value=self.site)
        self.compile_clauses = MagicMock()
        self.judge = MagicMock(return_value={})
        self.refresh = AsyncMock(side_effect=lambda site: self.calls.append(f"refresh:{site}"))
        self.wake = MagicMock(side_effect=lambda: self.calls.append("wake"))
        self.service = PoolOverrideService(
            sqlite_client=self.db,
            capacity_runtime=self.runtime,
            projection_source=lambda: projection,
            compile_clauses=self.compile_clauses,
            judge_shapes=self.judge,
            refresh_site=self.refresh,
            wake_publication=self.wake,
        )


def _record(**fields) -> PoolOverrideRecord:
    return PoolOverrideRecord.model_validate({"site_id": "site-a", "pool_id": "gpu", **fields})


async def _refused(world: _World, record: PoolOverrideRecord) -> PoolOverrideRefused:
    with pytest.raises(PoolOverrideRefused) as caught:
        await world.service.replace(record)
    return caught.value


# -- write checks, in order ----------------------------------------------------


async def test_an_unconfigured_site_is_refused_before_any_site_call():
    world = _World()

    refusal = await _refused(world, _record(site_id="site-zz"))

    assert refusal.status_code == 422
    world.runtime.site_client.assert_not_called()
    world.db.replace_pool_override.assert_not_awaited()


async def test_clauses_that_do_not_compile_are_refused_before_any_site_call():
    world = _World()
    world.compile_clauses.side_effect = ValueError("unknown mechanism")

    refusal = await _refused(world, _record(settlements=[{"mechanism": "nope"}]))

    assert refusal.status_code == 422 and "unknown mechanism" in refusal.detail
    world.runtime.site_client.assert_not_called()


@pytest.mark.parametrize(
    ("failure", "names"),
    [
        (SiteCapacityClientError("connection refused"), "unreachable"),
        (SiteCapacityAuthenticationError("bad signature", status_code=200), "did not verify"),
        (SiteCapacityClientError("boom", status_code=500), "HTTP 500"),
        ({"revision": "7", "digest": "d", "resource_pools": []}, "unusable"),
    ],
)
async def test_a_site_that_cannot_answer_is_refused_as_retryable(failure, names):
    world = _World(live=failure)

    refusal = await _refused(world, _record())

    assert refusal.status_code == 503
    assert "site-a" in refusal.detail and names in refusal.detail
    world.db.replace_pool_override.assert_not_awaited()


async def test_a_pool_the_live_projection_lacks_is_refused_and_nothing_is_stored():
    world = _World(live={**LIVE, "resource_pools": [{"resource_pool_id": "other"}]})

    refusal = await _refused(world, _record())

    assert refusal.status_code == 404 and "'gpu'" in refusal.detail
    world.db.replace_pool_override.assert_not_awaited()
    world.wake.assert_not_called()


async def test_an_accepted_write_stores_then_refreshes_then_wakes():
    world = _World()
    world.judge.return_value = {}

    response = await world.service.replace(_record(listing_shapes=[SHAPE]))

    assert world.calls == ["store", "refresh:site-a", "wake"]
    assert response["projection"] == {"revision": 7, "digest": "live-7"}
    (entry,) = response["feasibility"]
    assert entry["shape"] == SHAPE and entry["feasible"] is False


async def test_feasibility_is_judged_on_the_live_generation_with_the_new_record():
    world = _World()
    world.judge.return_value = {vm_shape_digest(SHAPE): True}

    response = await world.service.replace(_record(listing_shapes=[SHAPE]))

    pools, site, pool, home, override = world.judge.call_args.args
    assert pools == LIVE["resource_pools"]
    assert (site, pool, home) == ("site-a", "gpu", "site-a")
    assert override["listing_shapes"] == [SHAPE]
    assert response["feasibility"][0]["feasible"] is True


async def test_a_refresh_failure_does_not_fail_the_write():
    world = _World()
    world.refresh.side_effect = RuntimeError("site went away")

    response = await world.service.replace(_record())

    world.db.replace_pool_override.assert_awaited_once()
    world.wake.assert_called_once()
    assert response["override"]["pool_id"] == "gpu"


async def test_a_delete_wakes_publication_and_contacts_no_site():
    world = _World()

    assert await world.service.delete(site_id="site-a", pool_id="gpu") is True

    world.runtime.site_client.assert_not_called()
    world.refresh.assert_not_awaited()
    world.wake.assert_called_once()


# -- status --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("site_id", "projection", "state"),
    [
        ("site-a", None, OVERRIDE_INACTIVE),
        ("site-zz", {"site-a": []}, OVERRIDE_SITE_UNCONFIGURED),
        ("site-b", {"site-a": [{"resource_pool_id": "gpu"}]}, OVERRIDE_UNKNOWN),
        ("site-a", {"site-a": [{"resource_pool_id": "other"}]}, OVERRIDE_ORPHANED),
        # An authoritative empty generation is an answer: the pool is absent.
        ("site-a", {"site-a": []}, OVERRIDE_ORPHANED),
        ("site-a", {"site-a": [{"resource_pool_id": "gpu"}]}, OVERRIDE_APPLIED),
    ],
)
def test_an_override_is_in_exactly_one_state(site_id, projection, state):
    assert (
        override_state(
            site_id=site_id,
            pool_id="gpu",
            site_ids=("site-a", "site-b"),
            projection=projection,
        )
        == state
    )


def test_local_table_derivation_makes_even_an_unconfigured_site_inactive():
    assert (
        override_state(site_id="site-zz", pool_id="gpu", site_ids=("site-a",), projection=None)
        == OVERRIDE_INACTIVE
    )


async def test_statuses_report_every_stored_override():
    world = _World(projection={"site-a": [{"resource_pool_id": "gpu"}]})
    world.db.list_pool_overrides.return_value = [
        {"site_id": "site-a", "pool_id": "gpu"},
        {"site_id": "site-b", "pool_id": "gpu"},
    ]

    assert await world.service.statuses() == [
        {"site_id": "site-a", "pool_id": "gpu", "state": OVERRIDE_APPLIED},
        {"site_id": "site-b", "pool_id": "gpu", "state": OVERRIDE_UNKNOWN},
    ]
