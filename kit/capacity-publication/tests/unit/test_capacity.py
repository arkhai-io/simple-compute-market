from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core_storefront.aggregation import fill_first
from market_capacity_publication import (
    CapacityBinding,
    CapacityBindingError,
    UnbackedBinding,
    publication_binding,
    CapacityConfigurationError,
    CapacityRuntime,
    CapacitySite,
)


class FakeSite:
    def __init__(self, rows):
        self.rows = rows
        self.reserve = AsyncMock(
            return_value={"capacity_reservation_id": "r-1", "resource_id": "gpu-1"}
        )
        self.commit = AsyncMock()
        self.release = AsyncMock(return_value={"capacity_reservation_id": "r-1"})

    async def snapshot(self):
        return list(self.rows)


@pytest.fixture
def runtime():
    remotes = {
        "site-a": FakeSite([{"resource_id": "gpu-1", "available_units": 3}]),
        "site-b": FakeSite([{"resource_id": "gpu-1", "available_units": 8}]),
    }
    reconciler = AsyncMock()
    composed = CapacityRuntime(
        sites=(
            CapacitySite("site-a", "https://a.example/", object()),
            CapacitySite("site-b", "https://b.example", object()),
        ),
        signer=SimpleNamespace(identity="seller"),
        placement=fill_first,
        reconcile=reconciler,
        site_client_factory=lambda site, _signer: remotes[site.site_id],
    )
    return composed, remotes, reconciler


@pytest.mark.asyncio
async def test_projection_and_availability_keep_exact_site_authority(runtime):
    composed, _, _ = runtime

    projections = await composed.projections()
    availability = await composed.availability()

    assert [item.site_id for item in projections] == ["site-a", "site-b"]
    assert availability == {("site-a", "gpu-1"): 3, ("site-b", "gpu-1"): 8}
    assert (None, "gpu-1") not in availability


@pytest.mark.asyncio
async def test_bound_effects_never_fan_out_or_use_reservation_cache(runtime):
    composed, remotes, _ = runtime
    binding = CapacityBinding("site-b", "vm", "pool-1")

    reserved = await composed.reserve(binding, claim={"offering_mode": "vm"})
    await composed.commit(
        binding,
        resource_id="gpu-1",
        capacity_reservation_id="r-after-restart",
    )
    released = await composed.release(
        binding,
        capacity_reservation_id="r-after-restart",
    )

    assert reserved["site"] == "site-b"
    assert released["site"] == "site-b"
    remotes["site-a"].reserve.assert_not_awaited()
    remotes["site-a"].commit.assert_not_awaited()
    remotes["site-a"].release.assert_not_awaited()
    remotes["site-b"].commit.assert_awaited_once()
    remotes["site-b"].release.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_recorded_site_fails_closed(runtime):
    composed, remotes, _ = runtime

    with pytest.raises(CapacityBindingError, match="unconfigured site"):
        await composed.reserve(
            CapacityBinding("removed-site", "vm", "pool-1"),
            claim={"offering_mode": "vm"},
        )

    assert all(remote.reserve.await_count == 0 for remote in remotes.values())


def test_incomplete_or_ambiguous_composition_is_rejected():
    with pytest.raises(CapacityConfigurationError, match="at least one"):
        CapacityRuntime(
            sites=(),
            signer=object(),
            placement=fill_first,
            reconcile=AsyncMock(),
        )
    with pytest.raises(CapacityConfigurationError, match="duplicate"):
        CapacityRuntime(
            sites=(
                CapacitySite("same", "https://a", object()),
                CapacitySite("same", "https://b", object()),
            ),
            signer=object(),
            placement=fill_first,
            reconcile=AsyncMock(),
        )


@pytest.mark.asyncio
async def test_capacity_effects_refuse_an_unbacked_binding_before_any_site_call(
    runtime,
):
    composed, remotes, _ = runtime
    unbacked = UnbackedBinding("site-b", "vm", "pool-1")

    with pytest.raises(CapacityBindingError, match="capacity-backed"):
        await composed.reserve(unbacked, claim={"offering_mode": "vm"})
    with pytest.raises(CapacityBindingError, match="capacity-backed"):
        await composed.commit(
            unbacked, resource_id="gpu-1", capacity_reservation_id="r-1"
        )
    with pytest.raises(CapacityBindingError, match="capacity-backed"):
        await composed.release(unbacked, capacity_reservation_id="r-1")
    with pytest.raises(CapacityBindingError, match="capacity-backed"):
        await composed.truncate_lease(
            unbacked,
            capacity_reservation_id="r-1",
            lease_end_utc="2026-09-23T00:00:00Z",
        )

    for remote in remotes.values():
        remote.reserve.assert_not_awaited()
        remote.commit.assert_not_awaited()
        remote.release.assert_not_awaited()


def test_binding_classes_are_distinct_over_equal_fields():
    backed = CapacityBinding("site-a", "vm", "pool-a")
    unbacked = UnbackedBinding("site-a", "vm", "pool-a")

    assert backed != unbacked
    assert not isinstance(unbacked, CapacityBinding)
    assert (backed.capacity_backing, unbacked.capacity_backing) == (
        "backed",
        "unbacked",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("backed", CapacityBinding), ("unbacked", UnbackedBinding)],
)
def test_durable_backing_loads_the_matching_binding(value, expected):
    binding = publication_binding(
        capacity_backing=value, site_id="site-a", offering_mode="vm", source_id="p"
    )

    assert type(binding) is expected


@pytest.mark.parametrize("value", ["Backed", "", None, "infinite"])
def test_durable_backing_outside_the_two_values_is_refused(value):
    with pytest.raises(CapacityBindingError, match="capacity_backing"):
        publication_binding(
            capacity_backing=value,
            site_id="site-a",
            offering_mode="vm",
            source_id="p",
        )
