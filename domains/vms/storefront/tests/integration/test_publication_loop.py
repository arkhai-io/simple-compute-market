"""The publication loop, driven through the storefront app.

Every cycle runs through the typed client's lifecycle controls — ``run-cycle``
applies exactly the timer's cycle, ``dry-run`` previews it — against the app built
by ``tests.publication_app``: the real routers and container, settlement configured
for real, and the capacity site, projection, and settlement mechanisms replaced
where this codebase wraps them. State is read back through the client wherever an
API exposes it; a listing's durable binding has no API and is read from the
storefront's own persistence.

The VM composition fulfils both of its mechanisms through capacity, so an unbacked
listing has no option it may publish under it. Tests of unbacked supply declare
``alkahest.v1`` as not fulfilled through capacity, which is what lets them publish.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

import pytest

from market_storefront import lifecycle, server
from market_storefront.startup import _start_publication_loop

from tests._settings_overrides import settings_overrides
from tests.fixtures.publication_cycle import validate_cycle_report
from tests.publication_app import (
    BUYER_SIGNER,
    SITE,
    pool,
    publication_app,
    settlement_clause,
)

pytestmark = pytest.mark.asyncio

# Alkahest declared as not fulfilled through capacity, so unbacked supply publishes.
_UNBACKED_PUBLISHABLE = {"alkahest.v1": False, "fiat.stripe.v1": True}


@pytest.fixture
async def world(tmp_path):
    async with publication_app(
        tmp_path, mechanism_fulfillment=_UNBACKED_PUBLISHABLE
    ) as app:
        yield app


@pytest.fixture
async def capacity_world(tmp_path):
    async with publication_app(tmp_path) as app:
        yield app


async def _cycle(world, *, dry_run: bool = False) -> dict:
    if dry_run:
        report = await world.client.admin_dry_run_lifecycle_cycle("publication")
    else:
        report = await world.client.admin_run_lifecycle_cycle("publication")
    validate_cycle_report(report)
    return report


def _row(listing) -> dict:
    """A client listing as one mapping: modelled fields plus everything else it
    carries, such as ``accepted_escrows`` and ``closed_by``."""
    if isinstance(listing, dict):
        row = dict(listing)
    else:
        row = {**listing.extra, **asdict(listing)}
        row.pop("extra", None)
    resource = row.get("listing_resource")
    if isinstance(resource, str):
        row["listing_resource"] = json.loads(resource)
    return row


async def _listings(world, *, status: str = "open") -> dict[str, dict]:
    page = await world.client.list_listings(status=status, limit=200)
    return {row["listing_id"]: row for row in map(_row, page.listings)}


async def _listing(world, listing_id: str) -> dict:
    return _row(await world.client.get_listing(listing_id))


async def _backing(world, listing_id: str) -> str:
    return (await world.db.load_listing_binding(listing_id=listing_id)).capacity_backing


async def test_a_declared_unbacked_pool_publishes_without_any_command(world):
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))

    result = await _cycle(world)

    listings = await _listings(world)
    assert result["counts"] == {"publish": 2}
    assert len(listings) == 2
    for listing_id, row in listings.items():
        assert await _backing(world, listing_id) == "unbacked"
        assert row["listing_resource"]["capacity_backing"] == "unbacked"
        assert [escrow["chain_name"] for escrow in row["accepted_escrows"]] == ["anvil"]


async def test_an_unbacked_source_with_only_capacity_mechanisms_publishes_nothing(
    capacity_world,
):
    capacity_world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))

    result = await _cycle(capacity_world)

    assert await _listings(capacity_world) == {}
    assert result["counts"] == {"refuse": 2}


async def test_a_dry_run_reports_the_cycle_and_changes_nothing(world):
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))

    first = await _cycle(world, dry_run=True)
    second = await _cycle(world, dry_run=True)

    assert first == second
    assert first["dry_run"] is True
    assert first["counts"] == {"publish": 2}
    assert await _listings(world) == {}


async def test_a_cycle_after_publication_is_unchanged(world):
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))
    await _cycle(world)
    before = await _listings(world)

    result = await _cycle(world)

    assert result["counts"] == {}
    assert await _listings(world) == before


async def test_a_term_change_refreshes_the_open_listing_in_place(world):
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))
    await _cycle(world)
    before = await _listings(world)

    world.set_settlement_clauses([settlement_clause(rate="250")])
    result = await _cycle(world)

    after = await _listings(world)
    assert set(after) == set(before)
    assert result["counts"] == {"refresh": 2}
    assert {
        row["accepted_escrows"][0]["rates"][0]["value"] for row in after.values()
    } == {"250"}


async def test_a_changed_model_closes_the_listings_and_publishes_the_new_shapes(world):
    """The model is part of a listing's shape, so a pool whose members change
    model withdraws the old shapes and offers new ones, each under its own key."""
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))
    await _cycle(world)
    published = set(await _listings(world))

    world.pools[0] = pool("broker-a", backing="unbacked", gpu_count=2, gpu_model="A100")
    result = await _cycle(world)

    assert result["counts"] == {"close": 2, "publish": 2}
    for listing_id in published:
        assert (await _listing(world, listing_id))["closed_by"] == "reconciliation"
    current = await _listings(world)
    assert set(current).isdisjoint(published)
    assert {row["listing_resource"]["gpu_model"] for row in current.values()} == {"A100"}
    # The new shapes are stable, and the withdrawn ones stay closed.
    assert "publish" not in (await _cycle(world))["counts"]
    assert set(await _listings(world)) == set(current)


async def test_a_disabled_pool_closes_its_listings(world):
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))
    await _cycle(world)

    world.pools[0] = pool("broker-a", backing="unbacked", gpu_count=2, enabled=False)
    result = await _cycle(world)

    assert await _listings(world) == {}
    assert result["counts"] == {"close": 2}


async def test_a_seller_close_survives_every_later_cycle(world):
    world.pools.append(pool("broker-a", backing="unbacked"))
    await _cycle(world)
    (listing_id,) = await _listings(world)
    await world.seller.close_listing(listing_id)

    result = await _cycle(world)

    assert await _listings(world) == {}
    assert result["counts"] == {"skip": 1}
    assert (await _listing(world, listing_id))["closed_by"] == "seller"


async def test_an_unresolvable_pool_is_held_not_closed(world):
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))
    world.pools.append(pool("broker-b", backing="unbacked", gpu_count=2))
    await _cycle(world)

    held = pool("broker-b", backing="unbacked", gpu_count=2)
    del held["pool_metadata"]["policy_tags"]["capacity_backing"]
    world.pools[1] = held
    result = await _cycle(world)

    assert len(await _listings(world)) == 4
    assert {a["pool_id"] for a in result["actions"] if a["action"] == "hold"} == {
        "broker-b"
    }


async def test_a_backed_listing_without_disclosed_backing_is_refreshed(world):
    world.pools.append(pool("pool-b", backing="backed"))
    await _cycle(world)
    (listing_id,) = await _listings(world)
    # Storefront-internal state no API reaches: a listing stored before its
    # backing was disclosed.
    with sqlite3.connect(world.db.db_path) as conn:
        conn.execute(
            "UPDATE listings SET listing_resource = json_remove(listing_resource, "
            "'$.capacity_backing') WHERE listing_id = ?",
            (listing_id,),
        )

    result = await _cycle(world)

    assert result["counts"] == {"refresh": 1}
    listing = (await _listings(world))[listing_id]
    assert listing["listing_resource"]["capacity_backing"] == "backed"


async def test_a_migrated_database_publishes_and_closes_without_the_legacy_table(
    world,
):
    """A database migrated to the common binding refuses writes to its legacy
    mapping table; publication and reconciliation never write it."""
    with sqlite3.connect(world.db.db_path) as conn:
        conn.execute(
            "CREATE TABLE derived_compute_listings (listing_id TEXT PRIMARY KEY)"
        )
        for action in ("INSERT", "UPDATE", "DELETE"):
            conn.execute(
                f"""
                CREATE TRIGGER derived_compute_listings_retired_{action.lower()}
                BEFORE {action} ON derived_compute_listings
                BEGIN
                  SELECT RAISE(ABORT, 'derived_compute_listings is retired');
                END
                """
            )
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))
    assert (await _cycle(world))["counts"] == {"publish": 2}

    world.pools[0] = pool("broker-a", backing="unbacked", gpu_count=2, enabled=False)
    result = await _cycle(world)

    assert result["counts"] == {"close": 2}


async def test_an_older_producer_is_read_as_backed_and_delivery_authorizes(world):
    """No pool carries either declaration: the site predates them."""
    legacy = pool("legacy", backing="backed")
    tags = legacy["pool_metadata"]["policy_tags"]
    del tags["capacity_backing"], tags["advertisable_modes"]
    world.pools.append(legacy)

    result = await _cycle(world)

    assert result["counts"] == {"publish": 1}
    (listing_id,) = await _listings(world)
    assert await _backing(world, listing_id) == "backed"
    status = await world.client.get_system_status()
    derivation = status["publication_derivation"] if isinstance(status, dict) else (
        status.publication_derivation
    )
    assert derivation[SITE]["compatibility_rule"] is True


async def test_an_unrecognized_backing_value_holds_its_pool(world):
    world.pools.append(pool("broker-a", backing="unbacked"))
    await _cycle(world)

    world.pools[0] = pool("broker-a", backing="Unbacked")
    result = await _cycle(world)

    assert len(await _listings(world)) == 1
    assert [a["action"] for a in result["actions"]] == ["hold"]


async def test_a_shrunk_declaration_closes_only_the_slices_it_no_longer_covers(world):
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=4))
    await _cycle(world)
    assert len(await _listings(world)) == 4

    world.pools[0] = pool("broker-a", backing="unbacked", gpu_count=2)
    result = await _cycle(world)

    remaining = await _listings(world)
    assert result["counts"] == {"close": 2}
    assert sorted(row["listing_resource"]["gpu_count"] for row in remaining.values()) == [
        1,
        2,
    ]


async def test_supply_moving_to_a_backed_pool_closes_and_republishes(world):
    world.pools.append(pool("broker-a", backing="unbacked"))
    await _cycle(world)
    (old_id,) = await _listings(world)
    old_binding = await world.db.load_listing_binding(listing_id=old_id)

    world.pools[0] = pool("broker-a", backing="unbacked", enabled=False)
    world.pools.append(pool("pool-b", backing="backed"))
    await _cycle(world)

    (new_id,) = await _listings(world)
    new_binding = await world.db.load_listing_binding(listing_id=new_id)
    assert new_id != old_id
    assert new_binding.capacity_backing == "backed"
    assert new_binding.derivation_key != old_binding.derivation_key
    assert await world.db.load_listing_binding(listing_id=old_id) == old_binding


async def test_a_pool_recreated_with_the_opposite_backing_is_refused(world):
    """A site rebuilt from scratch can return a pool ID with the other backing."""
    world.pools.append(pool("broker-a", backing="unbacked"))
    await _cycle(world)
    (listing_id,) = await _listings(world)
    binding = await world.db.load_listing_binding(listing_id=listing_id)

    world.pools[0] = pool("broker-a", backing="backed")
    first = await _cycle(world)
    second = await _cycle(world)

    assert await _listings(world) == {}
    assert first["counts"] == {"close": 1}
    assert second["counts"] == {"refuse": 1}
    assert await world.db.load_listing_binding(listing_id=listing_id) == binding


async def test_after_a_cycle_no_listing_lacks_an_explicit_backing(world):
    """Counted over every listing, not sampled."""
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=3))
    world.pools.append(pool("pool-b", backing="backed", gpu_count=2))
    await _cycle(world)
    # Every listing as a storefront that predates the field left it.
    with sqlite3.connect(world.db.db_path) as conn:
        conn.execute(
            "UPDATE listings SET listing_resource = json_remove(listing_resource, "
            "'$.capacity_backing')"
        )

    await _cycle(world)

    listings = await _listings(world)
    assert len(listings) == 5
    for listing_id, row in listings.items():
        assert row["listing_resource"]["capacity_backing"] == await _backing(
            world, listing_id
        )


async def test_a_capacity_event_acts_only_on_backed_listings(world):
    """Availability reconciliation never sees an unbacked listing.

    A drop in availability closes only the backed listing, and a release reopens
    only the backed one: a reconciliation-closed unbacked listing is the
    publication loop's to reopen, with its terms refreshed from its source.
    """
    world.pools.append(pool("broker-a", backing="unbacked"))
    world.pools.append(pool("pool-b", backing="backed"))
    await _cycle(world)
    by_backing = {
        await _backing(world, listing_id): listing_id
        for listing_id in await _listings(world)
    }
    backed, unbacked = by_backing["backed"], by_backing["unbacked"]

    async def state(listing_id):
        row = await _listing(world, listing_id)
        return row["status"], row["closed_by"]

    def set_available(units):
        # Only availability moves; every declared capacity stays as it was.
        for projected in world.pools:
            projected["resources"][0]["available"]["gpu_count"] = units

    set_available(0)
    world.site.emit("reserved")
    await world.client.admin_run_lifecycle_cycle("capacity-events")
    assert await state(backed) == ("closed", "reconciliation")
    assert await state(unbacked) == ("open", None)

    # Storefront-internal state: an unbacked listing reconciliation closed.
    await world.db.update_listing(
        listing_id=unbacked, status="closed", closed_by="reconciliation"
    )
    set_available(1)
    world.site.emit("released")
    await world.client.admin_run_lifecycle_cycle("capacity-events")
    assert await state(backed) == ("open", None)
    assert await state(unbacked) == ("closed", "reconciliation")


def _vm_provision(duration_seconds: int = 3600) -> dict:
    return {
        "kind": "compute.v1",
        "version": 1,
        "payload": {"duration_seconds": duration_seconds, "ssh_public_key": ""},
    }


async def test_an_unbacked_listing_publishes_and_negotiates_to_acceptance(tmp_path):
    """Publication and negotiation in one app: the loop publishes an unbacked
    listing, and a buyer negotiates that listing to acceptance with no capacity
    reservation or hold at any point."""
    async with publication_app(
        tmp_path, mechanism_fulfillment=_UNBACKED_PUBLISHABLE, negotiation=True
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked"))
        assert (await _cycle(world))["counts"] == {"publish": 1}
        ((listing_id, listing),) = (await _listings(world)).items()
        (escrow,) = listing["accepted_escrows"]

        with settings_overrides(
            **{
                "negotiation.policies": [
                    "has_matching_inventory_guard",
                    "escrow_shape_guard",
                    "accept_exact_listing",
                ],
                "capacity.hold_ttl_seconds": 900,
            }
        ):
            result = await world.buyer.negotiate_new(
                listing_id=listing_id,
                # The listing's hourly rate for the one-hour provision.
                initial_amount=int(escrow["rates"][0]["value"]),
                provision_terms=_vm_provision(3600),
                chain_name="anvil",
                escrow_address=escrow["escrow_address"],
                proposal_fields={},
                literal_fields=escrow["literal_fields"],
                rates=escrow["rates"],
                demands=listing["demands"],
                escrow_expiration_unix=1_800_000_000,
            )

        assert result["action"] == "accept"
        assert result["accepted_escrow_terms"]
        assert await _backing(world, listing_id) == "unbacked"
        assert world.site.reservations == {}
        assert (
            await world.db.load_capacity_hold(negotiation_id=result["negotiation_id"])
            is None
        )


@pytest.fixture
def lifecycle_registry():
    """A clean loop registry and pause flag, as a fresh process has."""
    lifecycle.reset_for_tests()
    server._LOOPS_PAUSED = False
    yield
    lifecycle.reset_for_tests()
    server._LOOPS_PAUSED = False


async def test_the_lifecycle_pause_holds_the_loop_while_its_controls_step_it(
    world, lifecycle_registry
):
    # Held before it starts, so the running loop never begins a cycle of its own.
    await world.client.admin_pause_lifecycle_loops()
    _start_publication_loop(world.db)
    held = await world.client.admin_pause_lifecycle_loops()
    assert held["loops"]["publication"] == "paused"

    world.pools.append(pool("broker-a", backing="unbacked"))
    first = await _cycle(world, dry_run=True)
    second = await _cycle(world, dry_run=True)
    assert first == second
    assert first["counts"] == {"publish": 1}
    assert await _listings(world) == {}

    applied = await _cycle(world)
    assert {**applied, "dry_run": True} == first
    assert len(await _listings(world)) == 1

    still_held = await world.client.admin_pause_lifecycle_loops()
    assert still_held["loops"]["publication"] == "paused"
    assert (await _cycle(world, dry_run=True))["counts"] == {}


async def test_round_zero_evaluation_runs_the_inventory_guard(world):
    """The admin dry run of a buyer's opening round checks the listing against a
    fresh derivation of its own source, as a real round does."""
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))
    await _cycle(world)
    listing_id, listing = max(
        (await _listings(world)).items(),
        key=lambda item: item[1]["listing_resource"]["gpu_count"],
    )
    (escrow,) = listing["accepted_escrows"]
    proposal = {
        "chain_name": "anvil",
        "escrow_address": escrow["escrow_address"],
        "fields": {"amount": 100},
        "literal_fields": escrow["literal_fields"],
        "rates": escrow["rates"],
        "demands": listing["demands"],
        "expiration_unix": 2_000_000_000,
    }

    async def evaluate():
        with settings_overrides(
            **{
                "negotiation.policies": [
                    "has_matching_inventory_guard",
                    "accept_exact_listing",
                ]
            }
        ):
            return await world.client.evaluate_negotiate(
                listing_id,
                proposal=proposal,
                buyer_principal=BUYER_SIGNER.identity,
                requested_duration_seconds=3600,
            )

    supported = await evaluate()
    assert supported.decision == "accept"

    # The declaration shrinks below the listing's count; no cycle has run, so
    # the listing is still open and only the guard can notice.
    world.pools[0] = pool("broker-a", backing="unbacked", gpu_count=1)
    refused = await evaluate()

    assert refused.decision == "reject"
    assert refused.decision_reason == "no_matching_declaration"


@pytest.fixture
async def registry_world(tmp_path):
    async with publication_app(
        tmp_path, mechanism_fulfillment=_UNBACKED_PUBLISHABLE, registries=True
    ) as app:
        yield app


async def test_a_term_refresh_updates_the_listing_in_place_at_every_registry(
    registry_world,
):
    world = registry_world
    world.pools.append(pool("broker-a", backing="unbacked"))
    await _cycle(world)
    (listing_id,) = await _listings(world)
    world.registries.sent.clear()

    world.set_settlement_clauses([settlement_clause(rate="250")])
    assert (await _cycle(world))["counts"] == {"refresh": 1}

    republished = world.registries.to("publish", listing_id)
    assert sorted(url for url, _ in republished) == sorted(world.registries.urls)
    for _, body in republished:
        assert body["accepted_escrows"][0]["rates"][0]["value"] == "250"
    # In place: the same listing, and no status change sent anywhere.
    assert world.registries.to("update", listing_id) == []
    assert {listing for _, _, listing, _ in world.registries.sent} == {listing_id}


async def test_a_reopen_republishes_and_reopens_at_every_registry(registry_world):
    world = registry_world
    world.pools.append(pool("broker-a", backing="unbacked"))
    await _cycle(world)
    (listing_id,) = await _listings(world)

    world.pools[0] = pool("broker-a", backing="unbacked", enabled=False)
    assert (await _cycle(world))["counts"] == {"close": 1}
    closes = world.registries.to("update", listing_id)
    assert sorted(url for url, _ in closes) == sorted(world.registries.urls)
    assert {body["status"] for _, body in closes} == {"closed"}
    world.registries.sent.clear()

    world.pools[0] = pool("broker-a", backing="unbacked")
    assert (await _cycle(world))["counts"] == {"reopen": 1}

    assert sorted(url for url, _ in world.registries.to("publish", listing_id)) == sorted(
        world.registries.urls
    )
    reopens = world.registries.to("update", listing_id)
    assert sorted(url for url, _ in reopens) == sorted(world.registries.urls)
    assert {body["status"] for _, body in reopens} == {"open"}
    assert (await _listing(world, listing_id))["status"] == "open"


async def test_a_registry_that_missed_a_close_is_repaired_by_the_next_cycle(
    registry_world,
):
    world = registry_world
    world.pools.append(pool("broker-a", backing="unbacked"))
    await _cycle(world)
    (listing_id,) = await _listings(world)
    registry_a, registry_b = world.registries.urls
    world.registries.failing = {("closed", registry_b)}

    world.pools[0] = pool("broker-a", backing="unbacked", enabled=False)
    first = await _cycle(world)

    assert first["counts"] == {"close": 1, "converge": 1, "fail": 1}
    world.registries.failing.clear()
    preview = await _cycle(world, dry_run=True)
    assert [
        (a["listing_id"], a["registries"]) for a in preview["actions"]
    ] == [(listing_id, [registry_b])]
    world.registries.sent.clear()

    repaired = await _cycle(world)

    assert repaired["counts"] == {"converge": 1}
    assert [(op, url, body) for op, url, _, body in world.registries.sent] == [
        ("update", registry_b, {"status": "closed"})
    ]
    assert (await _cycle(world))["counts"] == {}


async def test_a_registry_left_closed_by_a_failed_reopen_is_repaired_by_the_next_cycle(
    registry_world,
):
    world = registry_world
    world.pools.append(pool("broker-a", backing="unbacked"))
    await _cycle(world)
    (listing_id,) = await _listings(world)
    world.pools[0] = pool("broker-a", backing="unbacked", enabled=False)
    await _cycle(world)
    registry_a, registry_b = world.registries.urls
    world.registries.failing = {("open", registry_b)}

    world.pools[0] = pool("broker-a", backing="unbacked")
    assert (await _cycle(world))["counts"] == {"reopen": 1, "converge": 1, "fail": 1}
    world.registries.failing.clear()
    world.registries.sent.clear()

    assert (await _cycle(world))["counts"] == {"converge": 1}
    assert [(op, url) for op, url, _, _ in world.registries.sent] == [
        ("publish", registry_b),
        ("update", registry_b),
    ]
    assert world.registries.to("update", listing_id)[-1][1] == {"status": "open"}


# ---------------------------------------------------------------------------
# Listing shapes
# ---------------------------------------------------------------------------

_BIG = {"gpu_count": 2, "vcpu_count": 16, "ram_gb": 64, "disk_gb": 200}
_SHAPE = {"gpu": {"count": 1, "model": "H100"}, "cpu": {"count": 8},
          "memory": {"gib": 32}, "storage": {"gib": 100}}


def _shaped(pool_id="broker-a", *, backing="unbacked", shapes=(_SHAPE,), **kwargs):
    return pool(pool_id, backing=backing, capacity=kwargs.pop("capacity", _BIG),
                listing_shapes={"vm": list(shapes)}, **kwargs)


async def _report(world) -> dict:
    status = await world.client.get_system_status()
    return status.publication_derivation[SITE]


async def test_a_pool_hint_publishes_its_shapes_and_no_default_shapes(world):
    world.pools.append(_shaped())

    assert (await _cycle(world))["counts"] == {"publish": 1}

    ((_, listing),) = (await _listings(world)).items()
    resource = listing["listing_resource"]
    assert {k: resource[k] for k in ("gpu_count", "vcpu_count", "ram_gb", "disk_gb")} == {
        "gpu_count": 1, "vcpu_count": 8, "ram_gb": 32, "disk_gb": 100,
    }


async def test_a_pool_without_a_hint_publishes_gpu_only_default_shapes(world):
    world.pools.append(pool("broker-a", backing="unbacked", capacity=_BIG))

    assert (await _cycle(world))["counts"] == {"publish": 2}

    for listing in (await _listings(world)).values():
        resource = listing["listing_resource"]
        # The member declares memory and disk, but a default shape commits to
        # the GPU family only, as listings did before shapes.
        assert resource.get("vcpu_count") is None
        assert resource.get("ram_gb") is None and resource.get("disk_gb") is None
        assert (resource["gpu_model"], resource["region"]) == ("H100", "us-east")


async def test_editing_a_shape_closes_its_listing_and_publishes_the_new_one(world):
    world.pools.append(_shaped())
    await _cycle(world)
    ((old_id, _),) = (await _listings(world)).items()
    old_binding = await world.db.load_listing_binding(listing_id=old_id)

    world.pools[0] = _shaped(shapes=({**_SHAPE, "memory": {"gib": 48}},))
    result = await _cycle(world)

    assert result["counts"] == {"close": 1, "publish": 1}
    ((new_id, new),) = (await _listings(world)).items()
    assert new_id != old_id and new["listing_resource"]["ram_gb"] == 48
    # The old listing's binding is never rewritten; a new identity was bound.
    assert await world.db.load_listing_binding(listing_id=old_id) == old_binding
    new_binding = await world.db.load_listing_binding(listing_id=new_id)
    assert new_binding.derivation_key != old_binding.derivation_key


async def test_a_declaration_shrinking_beneath_a_shape_closes_and_reports_it(world):
    world.pools.append(_shaped())
    await _cycle(world)

    world.pools[0] = _shaped(capacity={**_BIG, "ram_gb": 16})
    assert (await _cycle(world))["counts"] == {"close": 1}

    (finding,) = (await _report(world))["infeasible_shapes"]["broker-a"]
    assert finding["not_feasible_against"] == "declared"


async def test_backed_memory_being_taken_makes_a_stated_shape_unpublishable(capacity_world):
    capacity_world.pools.append(_shaped(backing="backed"))
    assert (await _cycle(capacity_world))["counts"] == {"publish": 1}

    capacity_world.pools[0] = _shaped(backing="backed", available={**_BIG, "ram_gb": 8})
    assert (await _cycle(capacity_world))["counts"] == {"close": 1}
    assert await _listings(capacity_world) == {}


async def test_a_capacity_change_does_not_resize_a_listing(capacity_world):
    capacity_world.pools.append(_shaped(backing="backed"))
    await _cycle(capacity_world)
    before = await _listings(capacity_world)

    # Part of the member is taken, but it is still feasible for the shape.
    capacity_world.pools[0] = _shaped(
        backing="backed", available={**_BIG, "gpu_count": 1, "ram_gb": 40}
    )
    result = await _cycle(capacity_world)

    assert "close" not in result["counts"] and "publish" not in result["counts"]
    after = await _listings(capacity_world)
    assert set(after) == set(before)
    for listing_id, listing in after.items():
        assert listing["listing_resource"] == before[listing_id]["listing_resource"]


async def test_a_dry_run_reports_shapes_without_changing_anything(world):
    world.pools.append(_shaped(shapes=(_SHAPE, {"gpu": {"count": 2, "model": "H100"}})))

    report = await _cycle(world, dry_run=True)

    assert report["counts"] == {"publish": 2}
    assert await _listings(world) == {}


async def test_a_stated_shape_negotiates_and_reserves_every_declared_dimension(tmp_path):
    async with publication_app(tmp_path, negotiation=True) as world:
        world.pools.append(_shaped(backing="backed"))
        # The claim's pool pins the site resource of the same name.
        world.site.add_resource(
            "broker-a", 2,
            attributes={"gpu_model": "H100", "region": "us-east"},
            capacity=_BIG,
        )
        assert (await _cycle(world))["counts"] == {"publish": 1}
        ((listing_id, listing),) = (await _listings(world)).items()
        (escrow,) = listing["accepted_escrows"]

        with settings_overrides(
            **{
                "negotiation.policies": [
                    "has_matching_inventory_guard",
                    "escrow_shape_guard",
                    "accept_exact_listing",
                ],
                "capacity.hold_ttl_seconds": 900,
            }
        ):
            result = await world.buyer.negotiate_new(
                listing_id=listing_id,
                initial_amount=int(escrow["rates"][0]["value"]),
                provision_terms=_vm_provision(3600),
                chain_name="anvil",
                escrow_address=escrow["escrow_address"],
                proposal_fields={},
                literal_fields=escrow["literal_fields"],
                rates=escrow["rates"],
                demands=listing["demands"],
                escrow_expiration_unix=1_800_000_000,
            )

        assert result["action"] == "accept"
        (reservation,) = world.site.reservations.values()
        assert reservation["dimensions"] == {
            "gpu_count": 1, "vcpu_count": 8, "ram_gb": 32, "disk_gb": 100,
        }


def _pre_shape_listing(db, listing_id, *, gpu_count, status="open", closed_by=None,
                       paused=False):
    """Direct setup, because no API binds a listing without a shape any more: a
    listing as it was bound before shapes, with a version 1 envelope."""
    from core_storefront.domain_registry import (
        StorefrontListingBinding,
        build_storefront_derivation_key,
    )
    from tests.fake_site import TEST_MARKETPLACE_SIGNER

    registration = db.domain_registry.resolve_mode("vm")
    source = {
        "kind": "compute.listing_source",
        "schema_version": 1,
        "payload": {"site_id": SITE, "pool_id": "broker-a", "resource_id": None,
                    "gpu_count": gpu_count},
    }
    binding = StorefrontListingBinding.from_source_envelope(
        listing_id=listing_id,
        site_id=SITE,
        binding=registration.binding,
        derivation_key=build_storefront_derivation_key(
            site_id=SITE,
            offering_mode=registration.binding.offering_mode,
            binding=registration.binding,
            source_identity=source,
        ),
        source_envelope=source,
        last_reconciled_at="2026-01-01T00:00:00Z",
        capacity_backing="unbacked",
        pool_id="broker-a",
    )
    return db.upsert_listing_with_binding(
        binding=binding,
        status=status,
        closed_by=closed_by,
        paused=paused,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        listing_resource={
            "pool_id": "broker-a", "gpu_model": "H100", "gpu_count": gpu_count,
            "region": "us-east", "sla": 0.0, "offering_mode": "vm",
            "capacity_backing": "unbacked",
        },
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://seller",
        seller_principal=TEST_MARKETPLACE_SIGNER.identity,
    )


async def test_an_upgraded_storefront_republishes_once_keeping_seller_state(world):
    from market_storefront.services.listing_identity_carryover import (
        carry_over_seller_state,
    )

    await _pre_shape_listing(world.db, "v1-open", gpu_count=1)
    await _pre_shape_listing(world.db, "v1-seller", gpu_count=2, status="closed",
                             closed_by="seller")
    await _pre_shape_listing(world.db, "v1-paused", gpu_count=3, paused=True)
    await _pre_shape_listing(world.db, "v1-recon", gpu_count=4, status="closed",
                             closed_by="reconciliation")
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=4))

    # The startup step, then the first cycle.
    carried = await carry_over_seller_state(world.db)
    assert set(carried.successors) == {"v1-seller", "v1-paused"}
    # The seller learns which listing to reopen or resume from system status.
    reported = (await world.client.get_system_status()).extra["listing_identity_carryover"]
    assert reported["successors"] == carried.successors
    result = await _cycle(world)

    # Each open pre-shape listing closes once; shapes without a successor publish.
    assert result["counts"]["close"] == 2
    assert result["counts"]["publish"] == 2
    for listing_id in ("v1-open", "v1-paused"):
        assert (await _listing(world, listing_id))["closed_by"] == "reconciliation"
    seller_successor = await _listing(world, carried.successors["v1-seller"])
    assert (seller_successor["status"], seller_successor["closed_by"]) == ("closed", "seller")
    paused_successor = await _listing(world, carried.successors["v1-paused"])
    assert (paused_successor["status"], paused_successor["paused"]) == ("open", True)

    # No shape is open twice, the seller's closed shape stays closed, and a later
    # cycle neither reopens a pre-shape listing nor publishes again.
    open_counts = [row["listing_resource"]["gpu_count"] for row in (await _listings(world)).values()]
    assert sorted(open_counts) == [1, 3, 4]
    later = await _cycle(world)
    assert "publish" not in later["counts"] and "close" not in later["counts"]
    for listing_id in ("v1-open", "v1-seller", "v1-paused", "v1-recon"):
        assert (await _listing(world, listing_id))["status"] == "closed"
