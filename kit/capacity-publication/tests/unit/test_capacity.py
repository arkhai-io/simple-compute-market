from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from core_storefront.aggregation import fill_first
from market_capacity_publication import (
    CapacityBinding,
    CapacityBindingError,
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

    reserved = await composed.reserve(binding, claim={"executor_kind": "vm"})
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
            claim={"executor_kind": "vm"},
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
