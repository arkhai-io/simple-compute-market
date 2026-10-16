"""The storefront's one projection state, driven through the typed client.

The app is ``tests.publication_app`` with two configured sites, whose projection
state is built over fake sites serving the harness's pool lists. An operator
reaches the state through the admin projection refresh and the
``site-projections`` lifecycle step; publication reads what it holds. Every wake
the state raises is recorded by the harness before it reaches the publication
loop.
"""

from __future__ import annotations

import asyncio

import pytest

from market_storefront import lifecycle
from tests.publication_app import SITE, SITE_B, pool, publication_app

pytestmark = pytest.mark.asyncio

# Alkahest declared as not fulfilled through capacity, so unbacked supply publishes.
_UNBACKED_PUBLISHABLE = {"alkahest.v1": False, "arkhai.payments.v1": True}


@pytest.fixture
async def lifecycle_registry():
    """A clean loop registry and pause flag, as a fresh process has; any timer
    a test started is cancelled and awaited before its event loop closes."""
    lifecycle.reset_for_tests()
    yield
    handles = list(lifecycle.controller()._handles.values())
    lifecycle.reset_for_tests()
    await asyncio.gather(*handles, return_exceptions=True)


@pytest.fixture
async def world(tmp_path, lifecycle_registry):
    async with publication_app(
        tmp_path, mechanism_fulfillment=_UNBACKED_PUBLISHABLE, second_site=True
    ) as app:
        yield app


async def _open_listing_sites(world) -> dict[str, str]:
    """Each open listing's pool, by listing ID."""
    page = await world.client.list_listings(status="open", limit=200)
    return {listing.listing_id: listing.listing_resource["pool_id"] for listing in page.listings}


async def _hold_the_loops(world) -> dict[str, str]:
    """Hold the loops before the poller's timer starts, so it runs no cycle."""
    await world.client.admin_pause_lifecycle_loops()
    lifecycle.start_loops()
    return (await world.client.admin_pause_lifecycle_loops())["loops"]


@pytest.mark.parametrize("held", [False, True], ids=["running", "held"])
async def test_an_operator_refreshes_every_site_during_an_outage(world, held):
    world.pools.append(pool("pool-a", backing="unbacked"))
    world.pools_b.append(pool("pool-b", backing="unbacked"))
    await world.client.admin_refresh_site_projections()
    await world.client.admin_run_lifecycle_cycle("publication")
    assert sorted((await _open_listing_sites(world)).values()) == ["pool-a", "pool-b"]
    if held:
        assert (await _hold_the_loops(world))[lifecycle.SITE_PROJECTION_POLLER] == "paused"

    # Site-a stops answering while site-b declares a new pool.
    world.projection.failing = True
    world.pools_b.append(pool("pool-b2", backing="unbacked"))
    woken = len(world.wakes)
    refreshed = await world.client.admin_refresh_site_projections()

    site_a = refreshed["sites"][SITE]["resource_pool"]
    assert site_a["state"] == "stale" and site_a["last_error"]
    assert refreshed["sites"][SITE_B]["resource_pool"]["state"] == "loaded"
    # Site-b's change woke publication; site-a's failure changed nothing.
    assert len(world.wakes) == woken + 1

    # Site-a's listing keeps deriving from its last generation rather than
    # becoming unknown, and site-b's new pool publishes.
    report = await world.client.admin_run_lifecycle_cycle("publication")
    assert not [
        action
        for action in report["actions"]
        if action["action"] == "hold" and action.get("site_id") == SITE
    ]
    assert sorted((await _open_listing_sites(world)).values()) == [
        "pool-a",
        "pool-b",
        "pool-b2",
    ]
    if held:
        assert (await world.client.admin_pause_lifecycle_loops())["loops"][
            lifecycle.SITE_PROJECTION_POLLER
        ] == "paused"


async def test_the_projection_step_is_run_while_held(world):
    loops = await _hold_the_loops(world)
    assert loops[lifecycle.SITE_PROJECTION_POLLER] == "paused"
    fetched = world.projection.snapshots["resource_pool"]
    woken = len(world.wakes)

    world.pools.append(pool("pool-a", backing="unbacked"))
    stepped = await world.client.admin_run_lifecycle_cycle("site-projections")

    # Exactly the poller's cycle: each site's version checked, the changed one
    # fetched, and publication woken for the change.
    assert stepped["loop"] == lifecycle.SITE_PROJECTION_POLLER
    assert stepped["sites"][SITE]["resource_pool"]["state"] == "loaded"
    assert world.projection.snapshots["resource_pool"] == fetched + 1
    assert world.projection_b.snapshots["resource_pool"] == 1
    assert len(world.wakes) == woken + 1
    # A wake never advances a held loop: nothing published, and the loops stay held.
    assert await _open_listing_sites(world) == {}
    assert (await world.client.admin_pause_lifecycle_loops())["loops"][
        lifecycle.SITE_PROJECTION_POLLER
    ] == "paused"

    # A cycle with no change confirms and wakes nothing.
    await world.client.admin_run_lifecycle_cycle("site-projections")
    assert len(world.wakes) == woken + 1
