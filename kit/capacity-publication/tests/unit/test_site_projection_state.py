"""Per-site projection state over a fake aggregate's named sites.

Each fake site serves both projection families from values the test sets and
fails on demand. The aggregate is the real ``AggregateCapacityClient`` over
those fakes, injected through the state's constructor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from core_storefront.aggregation import AggregateCapacityClient
from core_storefront.models.system_models import ProjectionFamilyStatus
from core_storefront.site_projections import (
    ProjectionCacheView,
    ProjectionIdentity,
    ProjectionState,
)
from market_capacity_publication import (
    CAPACITY_BUCKET,
    RESOURCE_POOL,
    CapacityBindingError,
    CapacityConfigurationError,
    SiteProjectionState,
    freshly_confirmed,
)

_ROWS_KEY = {RESOURCE_POOL: "resource_pools", CAPACITY_BUCKET: "capacity_buckets"}


class _FakeSite:
    """One site's two projection families, as a site client serves them."""

    def __init__(self, pools=None, buckets=None) -> None:
        self.rows = {
            RESOURCE_POOL: list(pools if pools is not None else [{"pool_id": "p1"}]),
            CAPACITY_BUCKET: list(buckets if buckets is not None else [{"bucket": "b1"}]),
        }
        self.revision = {RESOURCE_POOL: 1, CAPACITY_BUCKET: 1}
        self.failing: set[str] = set()
        self.calls: list[str] = []
        self.topology_handler = None

    def change(self, family: str, rows) -> None:
        self.rows[family] = list(rows)
        self.revision[family] += 1

    def _identity(self, family: str) -> dict:
        return {"revision": self.revision[family], "digest": f"{family}:{self.revision[family]}"}

    async def _version(self, family: str) -> dict:
        self.calls.append(f"{family}.version")
        if family in self.failing:
            raise RuntimeError(f"{family} unreachable")
        return self._identity(family)

    async def _snapshot(self, family: str) -> dict:
        self.calls.append(f"{family}.snapshot")
        if family in self.failing:
            raise RuntimeError(f"{family} unreachable")
        return {**self._identity(family), _ROWS_KEY[family]: list(self.rows[family])}

    async def resource_pool_projection_version(self):
        return await self._version(RESOURCE_POOL)

    async def resource_pool_projection(self):
        return await self._snapshot(RESOURCE_POOL)

    async def capacity_bucket_projection_version(self):
        return await self._version(CAPACITY_BUCKET)

    async def capacity_bucket_projection(self):
        return await self._snapshot(CAPACITY_BUCKET)

    def set_topology_error_handler(self, handler) -> None:
        self.topology_handler = handler


class _Wakes:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self) -> None:
        self.count += 1


def _state(**sites: _FakeSite) -> tuple[SiteProjectionState, _Wakes]:
    wakes = _Wakes()
    state = SiteProjectionState(
        AggregateCapacityClient(sites), on_resource_pool_change=wakes
    )
    return state, wakes


async def test_both_families_load_for_every_site():
    west, east = _FakeSite(), _FakeSite(pools=[{"pool_id": "e1"}])
    state, _ = _state(west=west, east=east)

    await state.poll_once()

    for site in ("west", "east"):
        for family in (RESOURCE_POOL, CAPACITY_BUCKET):
            assert state.view(site, family).state is ProjectionState.loaded
    assert state.values(RESOURCE_POOL) == {
        "west": [{"pool_id": "p1"}],
        "east": [{"pool_id": "e1"}],
    }
    assert state.values(CAPACITY_BUCKET) == {
        "west": [{"bucket": "b1"}],
        "east": [{"bucket": "b1"}],
    }


async def test_values_omit_a_site_holding_nothing_and_keep_a_loaded_empty_site():
    empty, unreachable = _FakeSite(pools=[]), _FakeSite()
    unreachable.failing = {RESOURCE_POOL}
    state, _ = _state(empty=empty, unreachable=unreachable)

    await state.poll_once()

    assert state.values(RESOURCE_POOL) == {"empty": []}
    assert state.view("unreachable", RESOURCE_POOL).value is None


async def test_a_failed_poll_keeps_the_last_generation_stale_and_in_values():
    site = _FakeSite()
    state, _ = _state(west=site)
    await state.poll_once()
    loaded = state.view("west", RESOURCE_POOL)

    site.failing = {RESOURCE_POOL}
    await state.poll_once()

    view = state.view("west", RESOURCE_POOL)
    assert view.state is ProjectionState.stale
    assert view.last_error == "resource_pool unreachable"
    assert view.fetched_at == loaded.fetched_at
    assert view.identity == loaded.identity
    assert state.values(RESOURCE_POOL) == {"west": [{"pool_id": "p1"}]}
    assert state.view("west", CAPACITY_BUCKET).state is ProjectionState.loaded


async def test_poll_once_wakes_publication_only_on_a_resource_pool_change():
    site = _FakeSite()
    state, wakes = _state(west=site)

    await state.poll_once()
    assert wakes.count == 1  # the first load is a change

    await state.poll_once()
    site.change(CAPACITY_BUCKET, [{"bucket": "b2"}])
    await state.poll_once()
    site.failing = {RESOURCE_POOL}
    await state.poll_once()
    assert wakes.count == 1

    site.failing = set()
    site.change(RESOURCE_POOL, [{"pool_id": "p2"}])
    await state.poll_once()
    assert wakes.count == 2
    assert state.values(RESOURCE_POOL) == {"west": [{"pool_id": "p2"}]}


async def test_refresh_site_fetches_in_place_and_never_wakes():
    west, east = _FakeSite(), _FakeSite()
    state, wakes = _state(west=west, east=east)
    await state.poll_once()
    wakes.count = 0
    west.calls.clear()
    east.calls.clear()

    west.change(RESOURCE_POOL, [{"pool_id": "p2"}])
    west.change(CAPACITY_BUCKET, [{"bucket": "b2"}])
    await state.refresh_site("west")

    assert wakes.count == 0
    assert sorted(west.calls) == ["capacity_bucket.snapshot", "resource_pool.snapshot"]
    assert east.calls == []
    assert state.values(RESOURCE_POOL)["west"] == [{"pool_id": "p2"}]
    assert state.values(CAPACITY_BUCKET)["west"] == [{"bucket": "b2"}]


async def test_refresh_site_can_select_families():
    site = _FakeSite()
    state, _ = _state(west=site)
    await state.poll_once()
    site.calls.clear()

    await state.refresh_site("west", families=[RESOURCE_POOL, RESOURCE_POOL])

    assert site.calls == ["resource_pool.snapshot"]


async def test_a_failed_refresh_site_does_not_raise_or_confirm():
    site = _FakeSite()
    state, wakes = _state(west=site)
    await state.poll_once()
    loaded_at = state.view("west", RESOURCE_POOL).fetched_at
    wakes.count = 0

    site.failing = {RESOURCE_POOL, CAPACITY_BUCKET}
    await state.refresh_site("west")

    for family in (RESOURCE_POOL, CAPACITY_BUCKET):
        assert state.view("west", family).state is ProjectionState.stale
    assert state.view("west", RESOURCE_POOL).fetched_at == loaded_at
    assert wakes.count == 0


async def test_a_topology_error_checks_both_families_once_and_wakes_on_a_pool_change():
    site = _FakeSite()
    state, wakes = _state(west=site)
    await state.poll_once()
    wakes.count = 0
    site.calls.clear()

    await site.topology_handler()
    assert sorted(site.calls) == ["capacity_bucket.version", "resource_pool.version"]
    assert wakes.count == 0

    site.calls.clear()
    site.change(RESOURCE_POOL, [{"pool_id": "p2"}])
    await site.topology_handler()
    assert sorted(site.calls) == [
        "capacity_bucket.version",
        "resource_pool.snapshot",
        "resource_pool.version",
    ]
    assert wakes.count == 1


async def test_a_failed_drift_check_keeps_the_generation_stale():
    site = _FakeSite()
    state, wakes = _state(west=site)
    await state.poll_once()
    wakes.count = 0

    site.failing = {CAPACITY_BUCKET}
    await site.topology_handler()

    assert state.view("west", CAPACITY_BUCKET).state is ProjectionState.stale
    assert state.view("west", RESOURCE_POOL).state is ProjectionState.loaded
    assert wakes.count == 0


async def test_unknown_sites_and_families_are_refused():
    state, _ = _state(west=_FakeSite())

    with pytest.raises(CapacityBindingError):
        state.view("east", RESOURCE_POOL)
    with pytest.raises(CapacityBindingError):
        await state.refresh_site("east")
    with pytest.raises(ValueError):
        state.view("west", "hosts")
    with pytest.raises(ValueError):
        state.values("hosts")
    with pytest.raises(ValueError):
        await state.refresh_site("west", families=["hosts"])


def test_a_non_aggregate_client_is_refused():
    with pytest.raises(CapacityConfigurationError):
        SiteProjectionState(object(), on_resource_pool_change=lambda: None)


async def test_status_reports_each_family_without_its_rows():
    loaded, unreachable = _FakeSite(), _FakeSite()
    unreachable.failing = {RESOURCE_POOL, CAPACITY_BUCKET}
    state, _ = _state(loaded=loaded, unreachable=unreachable)
    await state.poll_once()

    status = state.status()

    pool_status = status["loaded"][RESOURCE_POOL]
    assert isinstance(pool_status, ProjectionFamilyStatus)
    assert (pool_status.state, pool_status.revision, pool_status.digest) == (
        "loaded", 1, "resource_pool:1",
    )
    assert pool_status.fetched_at is not None
    assert status["unreachable"][RESOURCE_POOL].state == "unavailable"
    assert status["unreachable"][CAPACITY_BUCKET].last_error == "capacity_bucket unreachable"


_NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def _view(state: ProjectionState, *, age: float | None) -> ProjectionCacheView:
    return ProjectionCacheView(
        identity=ProjectionIdentity(1, "d"),
        value=[],
        state=state,
        last_error=None,
        fetched_at=None if age is None else _NOW - timedelta(seconds=age),
    )


@pytest.mark.parametrize(("age", "expected"), [(0, True), (10, True), (15, True), (15.001, False)])
def test_freshly_confirmed_within_the_window(age, expected):
    view = _view(ProjectionState.loaded, age=age)
    assert freshly_confirmed(view, now=_NOW, window_seconds=15) is expected


@pytest.mark.parametrize(
    "state",
    [
        ProjectionState.not_loaded,
        ProjectionState.stale,
        ProjectionState.unavailable,
        ProjectionState.invalid,
    ],
)
def test_only_a_loaded_generation_is_freshly_confirmed(state):
    assert freshly_confirmed(_view(state, age=1), now=_NOW, window_seconds=15) is False


def test_a_loaded_generation_never_confirmed_is_not_fresh():
    view = _view(ProjectionState.loaded, age=None)
    assert freshly_confirmed(view, now=_NOW, window_seconds=15) is False
