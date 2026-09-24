"""Storefront pool overrides, through the typed client against the storefront app.

The app is ``tests.publication_app``: real routers, container, identity
middleware, and database, with the capacity site replaced by the in-process fake
where this codebase wraps it. The fake site serves the live resource-pool
projection an override write is checked against; the harness's cache is what
publication derives from, so a test can make the two disagree.

Rejection-path cases assert status and stored state; the typed client raises
``StorefrontClientError`` carrying the status.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

import pytest
from storefront_client import StorefrontClientError

from market_storefront.services import site_projection_cache
from tests._settings_overrides import settings_overrides
from tests.publication_app import SITE, pool, publication_app

pytestmark = pytest.mark.asyncio

_UNBACKED_PUBLISHABLE = {"alkahest.v1": False, "fiat.stripe.v1": True}
_BIG = {"gpu_count": 2, "vcpu_count": 16, "ram_gb": 64, "disk_gb": 200}
HINT_SHAPE = {"gpu": {"count": 1, "model": "H100"}, "cpu": {"count": 8},
              "memory": {"gib": 32}, "storage": {"gib": 100}}
OVERRIDE_SHAPE = {**HINT_SHAPE, "memory": {"gib": 16}}
_PROJECTION_PATH = "/api/v1/capacity/site-resource-pools"


@pytest.fixture
async def world(tmp_path):
    async with publication_app(tmp_path, mechanism_fulfillment=_UNBACKED_PUBLISHABLE) as app:
        yield app


def _shaped(pool_id="gpu", *, backing="unbacked", shapes=(HINT_SHAPE,)):
    return pool(pool_id, backing=backing, capacity=_BIG, listing_shapes={"vm": list(shapes)})


def _record(pool_id="gpu", **fields) -> dict:
    return {"site_id": SITE, "pool_id": pool_id, **fields}


async def _cycle(world, loop: str = "publication") -> dict:
    return await world.client.admin_run_lifecycle_cycle(loop)


async def _open_listings(world) -> dict[str, dict]:
    page = await world.client.list_listings(status="open", limit=200)
    out = {}
    for listing in page.listings:
        resource = listing.listing_resource
        out[listing.listing_id] = json.loads(resource) if isinstance(resource, str) else resource
    return out


async def _refused(call) -> StorefrontClientError:
    with pytest.raises(StorefrontClientError) as caught:
        await call
    return caught.value


async def _stored(world) -> list:
    return (await world.client.admin_list_pool_overrides()).overrides


async def _states(world) -> dict[tuple[str, str], str]:
    status = await world.client.get_system_status()
    return {(o["site_id"], o["pool_id"]): o["state"] for o in status.pool_overrides}


def _site_calls(world) -> list:
    return [call for call in world.site.requests if call[1] == _PROJECTION_PATH]


# -- accepted writes -----------------------------------------------------------


async def test_an_accepted_write_reports_feasibility_and_the_live_generation(world):
    world.pools.append(_shaped())
    too_big = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 4096}}

    written = await world.client.admin_put_pool_override(
        _record(listing_shapes=[OVERRIDE_SHAPE, too_big], sla=99.5)
    )

    assert [entry.feasible for entry in written.feasibility] == [True, False]
    assert written.projection_revision == world.site.pool_projection_revision
    assert written.projection_digest
    assert written.override.sla == 99.5
    # The write refreshed the site's cache in place.
    assert world.projection.snapshots == 1


async def test_an_override_replacing_hint_shapes_republishes_and_survives_reconciliation(tmp_path):
    async with publication_app(tmp_path) as world:  # capacity-backed supply
        world.pools.append(_shaped(backing="backed"))
        await _cycle(world)
        ((hinted_id, _),) = (await _open_listings(world)).items()

        await world.client.admin_put_pool_override(_record(listing_shapes=[OVERRIDE_SHAPE]))
        result = await _cycle(world)

        assert result["counts"] == {"close": 1, "publish": 1}
        ((override_id, resource),) = (await _open_listings(world)).items()
        assert override_id != hinted_id and resource["ram_gb"] == 16

        # Capacity reconciliation derives the same key, so it leaves the listing.
        world.site.emit("released")
        await _cycle(world, "capacity-events")
        assert set(await _open_listings(world)) == {override_id}


async def test_an_infeasible_shape_is_accepted_and_publishes_nothing(world):
    world.pools.append(_shaped())
    await _cycle(world)
    too_big = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 4096}}

    written = await world.client.admin_put_pool_override(_record(listing_shapes=[too_big]))

    assert [entry.feasible for entry in written.feasibility] == [False]
    assert (await _cycle(world))["counts"] == {"close": 1}
    assert await _open_listings(world) == {}


async def test_an_exact_retry_returns_the_recorded_outcome(world):
    world.pools.append(_shaped())
    first = await world.client.admin_put_pool_override(_record(sla=90.0), request_id="retry-1")
    # The site is gone, but a retry is answered from the replay record.
    world.site.reachable = False

    second = await world.client.admin_put_pool_override(_record(sla=90.0), request_id="retry-1")

    assert asdict(second) == asdict(first)


# -- refused writes ------------------------------------------------------------


async def test_a_pool_the_live_site_lacks_is_refused_though_the_cache_lists_it(world):
    world.pools.append(_shaped())
    world.site.pool_projection = []  # the live generation no longer holds it

    refusal = await _refused(world.client.admin_put_pool_override(_record(sla=1.0)))

    assert refusal.status_code == 404
    assert await _stored(world) == []


@pytest.mark.parametrize(
    ("switch", "reason"),
    [("reachable", "unreachable"), ("verifiable", "did not verify")],
)
async def test_a_site_that_cannot_answer_is_refused_as_retryable(world, switch, reason):
    world.pools.append(_shaped())
    setattr(world.site, switch, False)

    refusal = await _refused(world.client.admin_put_pool_override(_record(sla=1.0)))

    assert refusal.status_code == 503
    assert reason in str(refusal) and "does not project" not in str(refusal)
    assert await _stored(world) == []


async def test_a_shape_outside_the_vocabulary_is_refused_without_a_site_call(world):
    world.pools.append(_shaped())
    shape = {"gpu": {"count": 1, "model": "H100"}, "fpga": {"count": 1}}

    refusal = await _refused(world.client.admin_put_pool_override(_record(listing_shapes=[shape])))

    assert refusal.status_code == 422
    assert _site_calls(world) == []
    assert await _stored(world) == []


async def test_an_unconfigured_site_is_refused_without_a_site_call(world):
    refusal = await _refused(
        world.client.admin_put_pool_override({"site_id": "site-zz", "pool_id": "gpu"})
    )

    assert refusal.status_code == 422
    assert _site_calls(world) == []


# -- reads and deletes ---------------------------------------------------------


async def test_reads_and_an_idempotent_delete(world):
    world.pools.append(_shaped())
    await world.client.admin_put_pool_override(_record(min_price="3"))

    assert (await world.client.admin_get_pool_override(SITE, "gpu")).min_price == "3"
    assert [o.pool_id for o in (await world.client.admin_list_pool_overrides(site_id=SITE)).overrides] == ["gpu"]

    assert (await world.client.admin_delete_pool_override(SITE, "gpu")).deleted is True
    assert (await world.client.admin_delete_pool_override(SITE, "gpu")).deleted is False
    refusal = await _refused(world.client.admin_get_pool_override(SITE, "gpu"))
    assert refusal.status_code == 404


# -- status --------------------------------------------------------------------


async def test_an_override_is_orphaned_while_its_pool_is_absent_and_applies_on_return(world):
    world.pools.append(_shaped())
    await world.client.admin_put_pool_override(_record(listing_shapes=[OVERRIDE_SHAPE]))
    await _cycle(world)
    assert await _states(world) == {(SITE, "gpu"): "applied"}

    removed = world.pools.pop()
    await _cycle(world)
    assert await _states(world) == {(SITE, "gpu"): "orphaned"}
    assert await _open_listings(world) == {}

    world.pools.append(removed)
    await _cycle(world)
    assert await _states(world) == {(SITE, "gpu"): "applied"}
    assert [r["ram_gb"] for r in (await _open_listings(world)).values()] == [16]


async def test_an_override_at_a_site_with_no_projection_is_unknown(world):
    world.pools.append(_shaped())
    await world.client.admin_put_pool_override(_record(sla=1.0))

    site_projection_cache._caches.pop(SITE)

    assert await _states(world) == {(SITE, "gpu"): "unknown"}


async def test_under_local_table_derivation_an_override_is_stored_but_inactive(world):
    world.pools.append(_shaped())
    with settings_overrides(**{"capacity.use_site_projection_for_listings": False}):
        await world.client.admin_put_pool_override(_record(listing_shapes=[OVERRIDE_SHAPE]))

        assert await _states(world) == {(SITE, "gpu"): "inactive"}
        await _cycle(world)
        assert await _open_listings(world) == {}


async def test_deleting_an_override_over_a_legacy_value_restores_and_reports_it(world):
    world.pools.append(_shaped())
    # Service-internal state setup: the legacy override row's only writer is
    # the resource import, which also writes physical inventory this test does
    # not want; no API writes the row alone.
    conn = sqlite3.connect(world.db.db_path)
    with conn:
        conn.execute(
            "INSERT INTO compute_capacity_pools (pool_id, gpu_model, sla) VALUES (?, ?, ?)",
            ("gpu", "H100", 90.0),
        )
    conn.close()
    await world.client.admin_put_pool_override(_record(sla=99.0))
    await _cycle(world)
    derivation = (await world.client.get_system_status()).publication_derivation[SITE]
    assert derivation["legacy_overrides_in_effect"] == {}

    await world.client.admin_delete_pool_override(SITE, "gpu")
    await _cycle(world)

    derivation = (await world.client.get_system_status()).publication_derivation[SITE]
    assert derivation["legacy_overrides_in_effect"] == {"gpu": ["sla"]}
    ((_, resource),) = (await _open_listings(world)).items()
    assert resource["sla"] == 90.0
