from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_resource_pools_contracts.backing import (
    BACKED,
    UNBACKED,
    CapacityNotAdmittedError,
)

from core_storefront.aggregation import AggregateCapacityClient, fill_first
from market_capacity_publication import (
    CapacityBindingError,
    CapacityEffects,
    PublicationBinding,
    backing_changed,
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
        self.commit = AsyncMock(
            return_value={"capacity_reservation_id": "r-1", "lease_end_utc": "2099-01-01 01:00"}
        )
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
    binding = PublicationBinding("site-b", "vm", "pool-1", BACKED)

    reserved = await composed.reserve(binding, claim={"offering_mode": "vm"})
    committed = await composed.commit(
        binding,
        resource_id="gpu-1",
        capacity_reservation_id="r-after-restart",
    )
    released = await composed.release(
        binding,
        capacity_reservation_id="r-after-restart",
    )

    assert reserved["site"] == "site-b"
    # The site's recorded reservation, tagged with the bound site.
    assert (committed["site"], committed["lease_end_utc"]) == ("site-b", "2099-01-01 01:00")
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
            PublicationBinding("removed-site", "vm", "pool-1", BACKED),
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
    unbacked = PublicationBinding("site-b", "vm", "pool-1", UNBACKED)

    with pytest.raises(CapacityNotAdmittedError, match="reserve"):
        await composed.reserve(unbacked, claim={"offering_mode": "vm"})
    with pytest.raises(CapacityNotAdmittedError, match="commit"):
        await composed.commit(
            unbacked, resource_id="gpu-1", capacity_reservation_id="r-1"
        )
    with pytest.raises(CapacityNotAdmittedError, match="release"):
        await composed.release(unbacked, capacity_reservation_id="r-1")
    with pytest.raises(CapacityNotAdmittedError, match="lease truncation"):
        await composed.truncate_lease(
            unbacked,
            capacity_reservation_id="r-1",
            lease_end_utc="2026-09-23T00:00:00Z",
        )

    for remote in remotes.values():
        remote.reserve.assert_not_awaited()
        remote.commit.assert_not_awaited()
        remote.release.assert_not_awaited()


@pytest.mark.asyncio
async def test_effects_over_any_aggregate_act_only_at_the_sites_it_names():
    site = AsyncMock()
    site.reserve.return_value = {"capacity_reservation_id": "r-1"}
    aggregate = AggregateCapacityClient({"site-a": site}, placement=fill_first)
    effects = CapacityEffects(aggregate)

    reserved = await effects.reserve(
        PublicationBinding("site-a", "bare_metal", "res-1", BACKED),
        claim={"offering_mode": "bare_metal"},
    )
    with pytest.raises(CapacityBindingError, match="unconfigured site"):
        await effects.commit(
            PublicationBinding("site-b", "bare_metal", "res-1", BACKED),
            resource_id="res-1",
            capacity_reservation_id="r-1",
        )

    assert reserved["site"] == "site-a"
    # The aggregate records where the reservation lives, as it does for any
    # reserve it routes.
    assert aggregate.reservation_sites["r-1"] == "site-a"


def test_bindings_differing_only_in_backing_are_unequal():
    backed = PublicationBinding("site-a", "vm", "pool-a", BACKED)
    unbacked = PublicationBinding("site-a", "vm", "pool-a", UNBACKED)

    assert backed != unbacked
    assert backed == PublicationBinding("site-a", "vm", "pool-a", BACKED)


@pytest.mark.parametrize("delegate", [BACKED, UNBACKED])
def test_durable_backing_loads_its_delegate(delegate):
    binding = publication_binding(
        capacity_backing=delegate.label,
        site_id="site-a",
        offering_mode="vm",
        source_id="p",
    )

    assert binding.backing is delegate


@pytest.mark.parametrize("value", ["Backed", "", None, "infinite"])
def test_durable_backing_with_no_delegate_is_refused(value):
    with pytest.raises(CapacityBindingError, match="capacity_backing"):
        publication_binding(
            capacity_backing=value,
            site_id="site-a",
            offering_mode="vm",
            source_id="p",
        )


def test_a_backing_change_is_detected_against_the_source():
    binding = PublicationBinding("site-a", "vm", "pool-a", BACKED)

    assert not backing_changed(binding, BACKED)
    assert backing_changed(binding, UNBACKED)
