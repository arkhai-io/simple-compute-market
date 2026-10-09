"""The write service against the real store, with its outside collaborators injected.

The site client, the market's contribution, the clause compiler, and publication's
refresh and wake are where this library meets things it does not own; each is a
small recording stand-in. The store is real, so every claim about what is and is
not stored is observed in the database.
"""

from __future__ import annotations

import sqlite3

import pytest
from market_site_client import SiteCapacityAuthenticationError, SiteCapacityClientError

from market_pool_overrides import (
    OVERRIDE_APPLIED,
    OVERRIDE_UNKNOWN,
    PoolOverrideAddress,
    PoolOverrideRecord,
    PoolOverrideRefused,
    PoolOverrideService,
    ShapeFeasibility,
    SQLitePoolOverrideStore,
    pool_override_migrations,
)

SHAPE = {"gpu": {"count": 1, "model": "H100"}}
LIVE = {"revision": 7, "digest": "live-7", "resource_pools": [{"pool_id": "gpu"}]}


class _Site:
    def __init__(self, answer):
        self.answer = answer
        self.calls = 0

    async def resource_pool_projection(self):
        self.calls += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class _Contribution:
    offering_mode = "vm"

    def __init__(self, *, problems=(), feasible=True):
        self.problems = list(problems)
        self.feasible = feasible
        self.judged = []

    def vocabulary_problems(self, record):
        return self.problems

    def judge_shapes(self, site_pools, *, record):
        self.judged.append((list(site_pools), record))
        return [ShapeFeasibility(shape_digest=f"d{i}", shape=shape, feasible=self.feasible)
                for i, shape in enumerate(record.listing_shapes or ())]


class _World:
    def __init__(self, db_path, *, answer=LIVE, contribution=None, compile_error=None,
                 refresh_error=None, projection=None):
        conn = sqlite3.connect(db_path)
        for migration in pool_override_migrations():
            migration.apply(conn)
        conn.commit()
        conn.close()
        self.events: list[str] = []
        self.site = _Site(answer)
        self.contribution = contribution or _Contribution()
        self.store = SQLitePoolOverrideStore(str(db_path))

        def compile_clauses(clauses):
            if compile_error is not None:
                raise compile_error

        async def refresh(site_id):
            self.events.append(f"refresh:{site_id}")
            if refresh_error is not None:
                raise refresh_error

        self.service = PoolOverrideService(
            store=self.store,
            site_ids=lambda: ("site-a", "site-b"),
            site_client=lambda site_id: self.site,
            contributions={"vm": self.contribution},
            compile_clauses=compile_clauses,
            projection_source=lambda: projection,
            refresh_site=refresh,
            wake_publication=lambda: self.events.append("wake"),
        )

    async def stored(self):
        return await self.store.list()


def _record(**fields) -> PoolOverrideRecord:
    fields = {"site_id": "site-a", "pool_id": "gpu", "offering_mode": "vm",
              "listing_shapes": [SHAPE], **fields}
    return PoolOverrideRecord.model_validate(fields)


async def _refused(world, record) -> PoolOverrideRefused:
    with pytest.raises(PoolOverrideRefused) as caught:
        await world.service.replace(record)
    return caught.value


@pytest.mark.parametrize(
    ("record", "world_kwargs"),
    [
        pytest.param({"site_id": "site-zz"}, {}, id="unconfigured site"),
        pytest.param({"offering_mode": "kube_pod"}, {}, id="no market serves the mode"),
        pytest.param({}, {"contribution": _Contribution(problems=["fpga: unknown"])},
                     id="vocabulary"),
        pytest.param({"settlements": [{"mechanism": "nope"}]},
                     {"compile_error": ValueError("unknown mechanism")}, id="clauses"),
    ],
)
async def test_a_request_refusable_without_the_site_never_calls_it(tmp_path, record, world_kwargs):
    world = _World(tmp_path / "db", **world_kwargs)

    refusal = await _refused(world, _record(**record))

    assert refusal.status_code == 422
    assert world.site.calls == 0
    assert await world.stored() == [] and world.events == []


@pytest.mark.parametrize(
    ("answer", "reason"),
    [
        (SiteCapacityClientError("connection refused"), "unreachable"),
        (SiteCapacityAuthenticationError("bad signature", status_code=200), "did not verify"),
        (SiteCapacityClientError("boom", status_code=500), "HTTP 500"),
        ({"revision": "7", "digest": "d", "resource_pools": []}, "unusable"),
        # A verified answer whose rows are not pool objects cannot be judged.
        ({"revision": 7, "digest": "d", "resource_pools": [1]}, "unusable"),
    ],
)
async def test_a_site_that_cannot_answer_usably_is_refused_as_retryable(tmp_path, answer, reason):
    world = _World(tmp_path / "db", answer=answer)

    refusal = await _refused(world, _record())

    assert refusal.status_code == 503
    assert "site-a" in refusal.detail and reason in refusal.detail
    assert await world.stored() == []


async def test_a_pool_the_live_projection_lacks_is_refused_and_nothing_is_stored(tmp_path):
    world = _World(tmp_path / "db", answer={**LIVE, "resource_pools": [{"pool_id": "x"}]})

    refusal = await _refused(world, _record())

    assert refusal.status_code == 404
    assert await world.stored() == [] and world.events == []


async def test_an_accepted_write_is_stored_then_refreshes_its_site_then_wakes(tmp_path):
    world = _World(tmp_path / "db")

    response = await world.service.replace(_record(site_id="site-b"))

    assert world.events == ["refresh:site-b", "wake"]
    (stored,) = await world.stored()
    assert (stored["site_id"], stored["listing_shapes"]) == ("site-b", [SHAPE])
    assert response["projection"] == {"revision": 7, "digest": "live-7"}
    # The market judged the live generation of the written site.
    pools, record = world.contribution.judged[0]
    assert pools == LIVE["resource_pools"] and record.site_id == "site-b"
    assert response["feasibility"][0]["feasible"] is True


async def test_a_refresh_failure_does_not_fail_the_write(tmp_path):
    world = _World(tmp_path / "db", refresh_error=RuntimeError("site went away"))

    await world.service.replace(_record())

    assert len(await world.stored()) == 1
    assert world.events == ["refresh:site-a", "wake"]


async def test_a_delete_wakes_publication_without_a_site_call(tmp_path):
    world = _World(tmp_path / "db")
    await world.service.replace(_record())
    world.events.clear()
    address = PoolOverrideAddress(site_id="site-a", pool_id="gpu", offering_mode="vm")

    assert await world.service.delete(address) is True

    assert world.site.calls == 1  # only the earlier write's
    assert world.events == ["wake"]


async def test_statuses_name_each_override_and_its_state(tmp_path):
    world = _World(tmp_path / "db", projection={"site-a": [{"pool_id": "gpu"}]})
    await world.service.replace(_record())
    await world.service.replace(_record(site_id="site-b"))

    assert await world.service.statuses() == [
        {"site_id": "site-a", "pool_id": "gpu", "offering_mode": "vm", "state": OVERRIDE_APPLIED},
        {"site_id": "site-b", "pool_id": "gpu", "offering_mode": "vm", "state": OVERRIDE_UNKNOWN},
    ]
