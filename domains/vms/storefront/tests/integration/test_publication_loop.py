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

from tests._settings_overrides import settings_overrides
from tests.fixtures.publication_cycle import validate_cycle_report
from tests.publication_app import (
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


async def test_a_changed_model_closes_the_listing_and_publishes_nothing_new(world):
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))
    await _cycle(world)
    published = set(await _listings(world))

    world.pools[0] = pool("broker-a", backing="unbacked", gpu_count=2, gpu_model="A100")
    result = await _cycle(world)

    assert await _listings(world) == {}
    assert result["counts"] == {"close": 2}
    for listing_id in published:
        assert (await _listing(world, listing_id))["closed_by"] == "reconciliation"
    # Still diverged: the listings stay closed.
    assert (await _cycle(world))["counts"] == {"refuse": 2}


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
    from market_storefront import lifecycle, server

    lifecycle.reset_for_tests()
    server._LOOPS_PAUSED = False
    yield
    lifecycle.reset_for_tests()
    server._LOOPS_PAUSED = False


async def test_the_lifecycle_pause_holds_the_loop_while_its_controls_step_it(
    world, lifecycle_registry
):
    from market_storefront.startup import _start_publication_loop

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
    from tests.publication_app import BUYER_SIGNER

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
