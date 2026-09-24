"""Storefront pool overrides, through the typed clients against the storefront app.

The app is ``tests.publication_app``: real routers, container, identity
middleware, and database, with each capacity site replaced by the in-process
fake where this codebase wraps it. The pool-override kit's client drives the
override routes over the core client's generic transport. The fake site serves
the live resource-pool projection a write is checked against; the harness cache
is what publication derives from, so a test can make the two disagree.

Rejection-path cases assert status and stored state; the typed client raises
``StorefrontClientError`` carrying the status.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

import pytest
from market_pool_overrides import PoolOverrideClient, pool_override_statuses
from storefront_client import StorefrontClientError

from market_storefront.services import site_projection_cache
from tests._settings_overrides import settings_overrides
from tests.publication_app import SITE, SITE_B, pool, publication_app, settlement_clause

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


def _record(pool_id="gpu", *, site_id=SITE, offering_mode="vm", **fields) -> dict:
    return {"site_id": site_id, "pool_id": pool_id, "offering_mode": offering_mode, **fields}


def _overrides(world) -> PoolOverrideClient:
    return PoolOverrideClient(world.client)


async def _cycle(world, loop: str = "publication") -> dict:
    return await world.client.admin_run_lifecycle_cycle(loop)


def _row(listing) -> dict:
    row = {**listing.extra, **asdict(listing)}
    row.pop("extra", None)
    if isinstance(row.get("listing_resource"), str):
        row["listing_resource"] = json.loads(row["listing_resource"])
    return row


async def _open_rows(world) -> dict[str, dict]:
    page = await world.client.list_listings(status="open", limit=200)
    return {listing.listing_id: _row(listing) for listing in page.listings}


async def _open_listings(world) -> dict[str, dict]:
    return {listing_id: row["listing_resource"] for listing_id, row in (await _open_rows(world)).items()}


async def _refused(call) -> StorefrontClientError:
    with pytest.raises(StorefrontClientError) as caught:
        await call
    return caught.value


async def _stored(world) -> list:
    return (await _overrides(world).list_pool_overrides()).overrides


async def _states(world) -> dict[tuple[str, str, str], str]:
    statuses = pool_override_statuses(await world.client.get_system_status()) or []
    return {(o["site_id"], o["pool_id"], o["offering_mode"]): o["state"] for o in statuses}


def _site_calls(site) -> list:
    return [call for call in site.requests if call[1] == _PROJECTION_PATH]


# -- accepted writes -----------------------------------------------------------


async def test_an_accepted_write_reports_feasibility_and_the_live_generation(world):
    world.pools.append(_shaped())
    too_big = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 4096}}

    written = await _overrides(world).put_pool_override(
        _record(listing_shapes=[OVERRIDE_SHAPE, too_big], terms={"sla": 99.5})
    )

    assert [entry.feasible for entry in written.feasibility] == [True, False]
    assert written.projection.revision == world.site.pool_projection_revision
    assert written.projection.digest
    assert written.override.terms == {"sla": 99.5}
    # The write refreshed the written site's cache in place.
    assert world.projection.snapshots == 1


async def test_an_override_replacing_hint_shapes_republishes_and_survives_reconciliation(tmp_path):
    async with publication_app(tmp_path) as world:  # capacity-backed supply
        world.pools.append(_shaped(backing="backed"))
        await _cycle(world)
        ((hinted_id, _),) = (await _open_listings(world)).items()

        await _overrides(world).put_pool_override(_record(listing_shapes=[OVERRIDE_SHAPE]))
        result = await _cycle(world)

        assert result["counts"] == {"close": 1, "publish": 1}
        ((override_id, resource),) = (await _open_listings(world)).items()
        assert override_id != hinted_id and resource["ram_gb"] == 16

        # Every structural-key reader resolves the override tier, so capacity
        # reconciliation derives the same key and leaves the listing open.
        world.site.emit("released")
        await _cycle(world, "capacity-events")
        assert set(await _open_listings(world)) == {override_id}


async def test_commercial_terms_reach_the_published_listing(world):
    world.pools.append(_shaped())
    await _cycle(world)

    await _overrides(world).put_pool_override(
        _record(terms={"sla": 97.5}, settlements=[settlement_clause(rate="7")])
    )
    await _cycle(world)

    ((_, row),) = (await _open_rows(world)).items()
    assert row["listing_resource"]["sla"] == 97.5
    assert row["accepted_escrows"][0]["rates"][0]["value"] == "7"


async def test_an_infeasible_shape_is_accepted_and_publishes_nothing(world):
    world.pools.append(_shaped())
    await _cycle(world)
    too_big = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 4096}}

    written = await _overrides(world).put_pool_override(_record(listing_shapes=[too_big]))

    assert [entry.feasible for entry in written.feasibility] == [False]
    assert (await _cycle(world))["counts"] == {"close": 1}
    assert await _open_listings(world) == {}


async def test_a_pool_with_unresolvable_declarations_is_accepted_and_held(world):
    world.pools.append(_shaped())
    await _cycle(world)
    held = _shaped()
    del held["pool_metadata"]["policy_tags"]["capacity_backing"]
    world.pools[0] = held

    written = await _overrides(world).put_pool_override(_record(terms={"sla": 90.0}))

    assert written.override.terms == {"sla": 90.0}
    result = await _cycle(world)
    assert {a["pool_id"] for a in result["actions"] if a["action"] == "hold"} == {"gpu"}
    assert len(await _open_listings(world)) == 1


async def test_a_refresh_failure_does_not_fail_the_write(world):
    world.pools.append(_shaped())
    await _cycle(world)
    world.projection.failing = True

    written = await _overrides(world).put_pool_override(_record(listing_shapes=[OVERRIDE_SHAPE]))

    assert written.override.listing_shapes == [OVERRIDE_SHAPE]
    assert world.projection.snapshots == 1  # the refresh was attempted
    # The cache keeps its last generation, and publication still applies the write.
    await _cycle(world)
    assert [r["ram_gb"] for r in (await _open_listings(world)).values()] == [16]


async def test_an_exact_retry_returns_the_recorded_outcome(world):
    world.pools.append(_shaped())
    first = await _overrides(world).put_pool_override(
        _record(terms={"sla": 90.0}), request_id="retry-1"
    )
    # The site is gone, but a retry is answered from the replay record.
    world.site.reachable = False

    second = await _overrides(world).put_pool_override(
        _record(terms={"sla": 90.0}), request_id="retry-1"
    )

    assert second == first


# -- a non-home site -----------------------------------------------------------


async def test_an_override_at_a_non_home_site_is_checked_stored_and_published_there(tmp_path):
    async with publication_app(
        tmp_path, mechanism_fulfillment=_UNBACKED_PUBLISHABLE, second_site=True
    ) as world:
        # The same pool name at both sites; only site-b's is overridden.
        world.pools.append(_shaped())
        world.pools_b.append(_shaped())
        await _cycle(world)

        await _overrides(world).put_pool_override(
            _record(site_id=SITE_B, listing_shapes=[OVERRIDE_SHAPE])
        )

        # The write reached site-b's authority, and refreshed only site-b's cache.
        assert _site_calls(world.site) == [] and len(_site_calls(world.site_b)) == 1
        assert (world.projection.snapshots, world.projection_b.snapshots) == (0, 1)
        (stored,) = await _stored(world)
        assert (stored.site_id, stored.pool_id) == (SITE_B, "gpu")

        await _cycle(world)
        memory = sorted(r["ram_gb"] for r in (await _open_listings(world)).values())
        assert memory == [16, 32]  # site-b's override, site-a's hint


# -- refused writes ------------------------------------------------------------


async def test_a_pool_the_live_site_lacks_is_refused_though_the_cache_lists_it(world):
    world.pools.append(_shaped())
    world.site.pool_projection = []  # the live generation no longer holds it

    refusal = await _refused(_overrides(world).put_pool_override(_record(terms={"sla": 1.0})))

    assert refusal.status_code == 404
    assert await _stored(world) == []


@pytest.mark.parametrize(
    ("switch", "reason"),
    [("reachable", "unreachable"), ("verifiable", "did not verify")],
)
async def test_a_site_that_cannot_answer_is_refused_as_retryable(world, switch, reason):
    world.pools.append(_shaped())
    setattr(world.site, switch, False)

    refusal = await _refused(_overrides(world).put_pool_override(_record(terms={"sla": 1.0})))

    assert refusal.status_code == 503
    assert reason in str(refusal) and "does not project" not in str(refusal)
    assert await _stored(world) == []


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(
            _record(listing_shapes=[{"gpu": {"count": 1, "model": "H100"}, "fpga": {"count": 1}}]),
            id="a shape outside the vocabulary",
        ),
        pytest.param(_record(terms={"sla": -1}), id="terms outside the vocabulary"),
        pytest.param(
            _record(settlements=[{"mechanism": "nope", "asset": "x", "rate": "1", "per": "hour"}]),
            id="clauses that do not compile",
        ),
        pytest.param(_record(offering_mode="kube_pod", terms={"sla": 1.0}),
                     id="a mode no market serves"),
        pytest.param(_record(site_id="site-zz", terms={"sla": 1.0}), id="an unconfigured site"),
    ],
)
async def test_a_write_refusable_without_the_site_never_calls_it(world, record):
    world.pools.append(_shaped())

    refusal = await _refused(_overrides(world).put_pool_override(record))

    assert refusal.status_code == 422
    assert _site_calls(world.site) == []
    assert await _stored(world) == []


# -- reads and deletes ---------------------------------------------------------


async def test_reads_and_an_idempotent_delete(world):
    world.pools.append(_shaped())
    overrides = _overrides(world)
    await overrides.put_pool_override(_record(terms={"min_price": "3"}))

    assert (await overrides.get_pool_override(SITE, "gpu", "vm")).terms == {"min_price": "3"}
    listed = await overrides.list_pool_overrides(site_id=SITE, pool_id="gpu")
    assert [(o.pool_id, o.offering_mode) for o in listed.overrides] == [("gpu", "vm")]

    assert (await overrides.delete_pool_override(SITE, "gpu", "vm")).deleted is True
    assert (await overrides.delete_pool_override(SITE, "gpu", "vm")).deleted is False
    refusal = await _refused(overrides.get_pool_override(SITE, "gpu", "vm"))
    assert refusal.status_code == 404


# -- status and unknown sites --------------------------------------------------


async def test_an_override_is_orphaned_while_its_pool_is_absent_and_applies_on_return(world):
    world.pools.append(_shaped())
    await _overrides(world).put_pool_override(_record(listing_shapes=[OVERRIDE_SHAPE]))
    await _cycle(world)
    assert await _states(world) == {(SITE, "gpu", "vm"): "applied"}

    removed = world.pools.pop()
    await _cycle(world)
    assert await _states(world) == {(SITE, "gpu", "vm"): "orphaned"}
    assert await _open_listings(world) == {}

    world.pools.append(removed)
    await _cycle(world)
    assert await _states(world) == {(SITE, "gpu", "vm"): "applied"}
    assert [r["ram_gb"] for r in (await _open_listings(world)).values()] == [16]


async def test_a_site_with_no_projection_holds_its_listings_and_its_override_is_unknown(
    tmp_path,
):
    async with publication_app(
        tmp_path, mechanism_fulfillment=_UNBACKED_PUBLISHABLE, second_site=True
    ) as world:
        world.pools.append(_shaped())
        world.pools_b.append(_shaped())
        await _overrides(world).put_pool_override(
            _record(site_id=SITE_B, listing_shapes=[OVERRIDE_SHAPE])
        )
        await _cycle(world)
        before = await _open_listings(world)
        assert len(before) == 2

        removed = site_projection_cache._caches.pop(SITE_B)
        result = await _cycle(world)

        # Unknown is not empty: site-b's listing is neither closed nor refreshed.
        assert await _open_listings(world) == before
        assert {
            (a.get("site_id"), a.get("reason")) for a in result["actions"] if a["action"] == "hold"
        } == {(SITE_B, "site_projection_unknown")}
        assert "close" not in result["counts"]
        assert (await _states(world))[(SITE_B, "gpu", "vm")] == "unknown"

        # When the site returns, its listings reconcile against it as usual.
        site_projection_cache._caches[SITE_B] = removed
        world.pools_b.clear()
        assert (await _cycle(world))["counts"] == {"close": 1}


async def test_with_no_site_known_nothing_is_derived_from_local_tables_or_closed(world):
    world.pools.append(_shaped())
    await _cycle(world)
    before = await _open_listings(world)
    # Service-internal state setup: a legacy local row a local-table fallback
    # would publish; no API writes local physical inventory alone.
    conn = sqlite3.connect(world.db.db_path)
    with conn:
        conn.execute(
            "INSERT INTO compute_capacity_pools (pool_id, gpu_model, total_gpu_count) "
            "VALUES ('local-only', 'A100', 4)"
        )
    conn.close()

    site_projection_cache._caches.pop(SITE)
    result = await _cycle(world)

    assert await _open_listings(world) == before
    assert "publish" not in result["counts"] and "close" not in result["counts"]


async def test_an_admin_reservation_closes_only_what_the_projection_no_longer_fits(tmp_path):
    async with publication_app(tmp_path) as world:  # capacity-backed supply
        world.pools.append(pool("gpu", backing="backed", gpu_count=2))
        world.site.add_resource("gpu-res", 2, attributes={"gpu_model": "H100", "region": "us-east"})
        await _cycle(world)
        by_count = {r["gpu_count"]: i for i, r in (await _open_listings(world)).items()}

        # The site now reports one GPU free, as its projection would after the hold.
        world.pools[0]["resources"][0]["available"]["gpu_count"] = 1
        reserved = await world.client.admin_reserve_capacity(
            required_attributes={}, listing_id=by_count[1]
        )

        # Only the two-GPU listing no longer fits; the one-GPU listing stays open.
        assert set(reserved.closed_listing_ids) == {by_count[2]}
        assert set(await _open_listings(world)) == {by_count[1]}


async def test_under_local_table_derivation_an_override_is_stored_but_inactive(world):
    world.pools.append(_shaped())
    with settings_overrides(**{"capacity.use_site_projection_for_listings": False}):
        await _overrides(world).put_pool_override(_record(listing_shapes=[OVERRIDE_SHAPE]))

        assert await _states(world) == {(SITE, "gpu", "vm"): "inactive"}
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
    await _overrides(world).put_pool_override(_record(terms={"sla": 99.0}))
    await _cycle(world)
    derivation = (await world.client.get_system_status()).publication_derivation[SITE]
    assert derivation["legacy_overrides_in_effect"] == {}

    await _overrides(world).delete_pool_override(SITE, "gpu", "vm")
    await _cycle(world)

    derivation = (await world.client.get_system_status()).publication_derivation[SITE]
    assert derivation["legacy_overrides_in_effect"] == {"gpu": ["sla"]}
    ((_, resource),) = (await _open_listings(world)).items()
    assert resource["sla"] == 90.0
