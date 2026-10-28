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

Every seller contact here is an address on the reserved ``.invalid`` domain, a
development value that must never be used on a public network.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

import pytest
from arkhai_vms_listings.listing_shapes import resolve_shape
from market_alkahest.alkahest import get_recipient_arbiter
from market_alkahest.dev_chain import anvil_address_book_path
from market_pool_overrides import PoolOverrideClient
from market_settlement_runtime import ReadinessBlocker

from market_storefront import lifecycle
from market_storefront.startup import _start_lifecycle_loops
from market_storefront.utils import config as storefront_config

from tests._settings_overrides import replaced_setting, settings_overrides
from tests.fixtures.publication_cycle import validate_cycle_report
from tests.introduction_deals import (
    CONTACT_MECHANISM,
    CONTACT_PUBLISHABLE,
    offer_introduction,
)
from tests.publication_app import (
    BUYER_SIGNER,
    SELLER_WALLET,
    SITE,
    SITE_B,
    contact_clause,
    contact_settlement,
    pool,
    publication_app,
    settlement_clause,
)

pytestmark = pytest.mark.asyncio

# Alkahest declared as not fulfilled through capacity, so unbacked supply publishes.
_UNBACKED_PUBLISHABLE = {"alkahest.v1": False, "arkhai.payments.v1": True}


@pytest.fixture
async def world(tmp_path):
    async with publication_app(
        tmp_path, mechanism_fulfillment=_UNBACKED_PUBLISHABLE
    ) as app:
        yield app


@pytest.fixture
async def negotiating_world(tmp_path):
    async with publication_app(
        tmp_path, mechanism_fulfillment=_UNBACKED_PUBLISHABLE, negotiation=True
    ) as app:
        yield app


@pytest.fixture
async def capacity_world(tmp_path):
    async with publication_app(tmp_path) as app:
        yield app


async def _poll(world) -> None:
    """One cycle of the projection poller: the storefront now holds what the
    harness's sites serve."""
    await world.client.admin_run_lifecycle_cycle("site-projections")


async def _cycle(world, *, dry_run: bool = False) -> dict:
    """One publication cycle, after the projection poller's, so the cycle reads
    what the harness's sites now serve."""
    await _poll(world)
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


async def test_an_alkahest_listing_advertises_the_recipient_arbiter_paying_the_seller(
    capacity_world,
):
    capacity_world.pools.append(pool("pool-a", backing="backed", gpu_count=1))

    await _cycle(capacity_world)

    (listing,) = (await _listings(capacity_world)).values()
    assert [escrow["chain_name"] for escrow in listing["accepted_escrows"]] == ["anvil"]
    assert listing["demands"] == [
        {
            "chain_name": "anvil",
            "arbiter": get_recipient_arbiter(
                "anvil", config_path=str(anvil_address_book_path())
            ).lower(),
            "demand_data": {"recipient": SELLER_WALLET.lower()},
        }
    ]


async def test_an_unready_alkahest_publishes_the_other_options_and_refuses_no_candidate(
    tmp_path,
):
    """An unready Alkahest's clauses publish no option and no release
    condition, the candidate publishes with its ready mechanism's option, and
    no candidate is refused for Alkahest. The settlement double reports the
    blocker the real preflight gives an oracle-gated section with no oracle
    (spec scenario "Alkahest is unready on a VM storefront"); the preflight
    itself is the kit's to test."""
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE: {"email": "sales@seller.invalid"}},
    ) as world:
        world.composition.alkahest_blocker = ReadinessBlocker(
            code="alkahest.oracle_policy_invalid",
            message="Settlement.alkahest.oracle_gated requires a trusted oracle",
            kind="configuration",
        )
        world.pools.append(pool("pool-a", backing="backed", gpu_count=1))
        with replaced_setting("pricing.settlements", [settlement_clause(), contact_clause()]):
            result = await _cycle(world)
            (listing,) = (await _listings(world)).values()

    assert result["counts"] == {"publish": 1}
    assert not listing.get("accepted_escrows")
    assert not listing.get("demands")
    assert [option["mechanism"] for option in listing["settlement_options"]] == [
        CONTACT_MECHANISM
    ]


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


def _without_region(projected: dict) -> dict:
    del projected["pool_metadata"]["policy_tags"]["region"]
    return projected


async def test_a_pool_stating_no_region_publishes_nothing_and_is_reported(world):
    world.pools.append(_without_region(pool("broker-a", backing="unbacked", gpu_count=2)))

    result = await _cycle(world)

    assert await _listings(world) == {}
    assert [
        (action["pool_id"], action["reason"])
        for action in result["actions"]
        if action["action"] == "hold"
    ] == [("broker-a", "pool_region_missing")]
    report = (await world.client.get_system_status()).publication_derivation[SITE]
    assert report["holds"] == [{"pool_id": "broker-a", "reason": "pool_region_missing"}]


async def test_a_preview_leaves_the_reported_derivation_as_the_last_cycle_left_it(world):
    """A previewed cycle derives as the cycle would, holds included, and
    publishes no derivation report: status keeps the last cycle's until a cycle
    runs, so its derivation and the loop's last outcome describe one cycle."""
    world.pools.append(_without_region(pool("broker-a", backing="unbacked", gpu_count=2)))
    await _cycle(world)
    world.pools[0] = pool("broker-a", backing="unbacked", gpu_count=2)

    preview = await _cycle(world, dry_run=True)
    previewed = (await world.client.get_system_status()).publication_derivation[SITE]
    await _cycle(world)
    ran = (await world.client.get_system_status()).publication_derivation[SITE]

    assert [action for action in preview["actions"] if action["action"] == "hold"] == []
    assert previewed["holds"] == [{"pool_id": "broker-a", "reason": "pool_region_missing"}]
    assert ran["holds"] == []


async def test_only_a_publication_cycle_records_a_sites_derivation(world):
    """A site is absent from status until a publication cycle derives it:
    capacity-event reconciliation and a preview derive the same projection and
    record nothing."""
    world.pools.append(_without_region(pool("broker-a", backing="unbacked", gpu_count=2)))

    before = (await world.client.get_system_status()).publication_derivation
    world.site.emit("reserved")
    await world.client.admin_run_lifecycle_cycle("capacity-events")
    reconciled = (await world.client.get_system_status()).publication_derivation
    await _cycle(world, dry_run=True)
    previewed = (await world.client.get_system_status()).publication_derivation
    await _cycle(world)
    ran = (await world.client.get_system_status()).publication_derivation

    assert before == reconciled == previewed == {}
    assert ran == {
        SITE: {
            "holds": [{"pool_id": "broker-a", "reason": "pool_region_missing"}],
            "refusals": [],
            "reports": [],
        }
    }


async def test_a_regionless_pool_with_no_available_slice_is_still_reported(world):
    """A backed pool with nothing available yields no candidate; publication
    still reports it as held for its missing region."""
    world.pools.append(
        _without_region(pool("pool-b", backing="backed", available={"gpu_count": 0}))
    )

    result = await _cycle(world)

    assert await _listings(world) == {}
    assert [
        (action["pool_id"], action["reason"])
        for action in result["actions"]
        if action["action"] == "hold"
    ] == [("pool-b", "pool_region_missing")]


async def test_a_pool_losing_its_region_holds_its_listings_open(world):
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))
    await _cycle(world)
    published = await _listings(world)

    world.pools[0] = _without_region(pool("broker-a", backing="unbacked", gpu_count=2))
    world.set_settlement_clauses([settlement_clause(rate="250")])
    result = await _cycle(world)

    # Neither closed nor refreshed: the changed rate, which would refresh a
    # listing whose pool states a region, does not reach them.
    assert await _listings(world) == published
    assert result["counts"] == {"hold": 1}


async def test_a_regionless_pools_sold_out_listing_still_closes(world):
    """Region does not bear on capacity, so availability reconciliation still
    closes a backed listing whose pool has stopped stating a region."""
    world.pools.append(pool("pool-b", backing="backed"))
    await _cycle(world)
    (listing_id,) = await _listings(world)

    world.pools[0] = _without_region(pool("pool-b", backing="backed"))
    world.pools[0]["resources"][0]["available"]["gpu_count"] = 0
    await _poll(world)
    world.site.emit("reserved")
    await world.client.admin_run_lifecycle_cycle("capacity-events")

    row = await _listing(world, listing_id)
    assert (row["status"], row["closed_by"]) == ("closed", "reconciliation")


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

    assert result["counts"] == {"report": 1, "publish": 1}
    (listing_id,) = await _listings(world)
    assert await _backing(world, listing_id) == "backed"
    derivation = (await world.client.get_system_status()).publication_derivation
    assert derivation[SITE]["reports"] == [{"reason": "legacy_producer_backing"}]


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
    # Named by its site and pool, the refusal reaches the site's derivation.
    (refusal,) = (await _derivation(world))["refusals"]
    assert (refusal["reason"], refusal["pool_id"], refusal["listing_id"]) == (
        "backing_disagrees",
        "broker-a",
        listing_id,
    )


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

    async def set_available(units):
        # Only availability moves; every declared capacity stays as it was.
        for projected in world.pools:
            projected["resources"][0]["available"]["gpu_count"] = units
        # A fungible pool's availability is read from the site's capacity
        # buckets, which the storefront holds as of its last poll.
        await world.client.admin_run_lifecycle_cycle("site-projections")

    await set_available(0)
    world.site.emit("reserved")
    await world.client.admin_run_lifecycle_cycle("capacity-events")
    assert await state(backed) == ("closed", "reconciliation")
    assert await state(unbacked) == ("open", None)

    # Storefront-internal state: an unbacked listing reconciliation closed.
    await world.db.update_listing(
        listing_id=unbacked, status="closed", closed_by="reconciliation"
    )
    await set_available(1)
    world.site.emit("released")
    await world.client.admin_run_lifecycle_cycle("capacity-events")
    assert await state(backed) == ("open", None)
    assert await state(unbacked) == ("closed", "reconciliation")


async def test_a_capacity_event_reconciles_on_the_buckets_current_with_it(world):
    """A capacity event refreshes its site's buckets before it reconciles.

    The site's availability moves and its event arrives with no projection poll
    between them, so the buckets the storefront held were the last poll's: the
    event's own reconciliation must fetch them, closing the backed fungible
    listing a reservation leaves without capacity and reopening it on release,
    and it wakes no publication.
    """
    world.pools.append(pool("pool-b", backing="backed"))
    await _cycle(world)
    (listing_id,) = await _listings(world)

    def set_available(units):
        for projected in world.pools:
            projected["resources"][0]["available"]["gpu_count"] = units

    async def state():
        row = await _listing(world, listing_id)
        return row["status"], row["closed_by"]

    wakes = len(world.wakes)
    set_available(0)
    world.site.emit("reserved")
    await world.client.admin_run_lifecycle_cycle("capacity-events")
    assert await state() == ("closed", "reconciliation")

    set_available(1)
    world.site.emit("released")
    await world.client.admin_run_lifecycle_cycle("capacity-events")
    assert await state() == ("open", None)
    assert len(world.wakes) == wakes


def _vm_provision(duration_seconds: int = 3600) -> dict:
    return {
        "kind": "compute.v1",
        "version": 1,
        "payload": {"duration_seconds": duration_seconds, "ssh_public_key": ""},
    }


def _alkahest_selection(listing) -> dict:
    """Fresh acceptance names its settlement option explicitly."""
    (option,) = [
        option for option in listing["settlement_options"]
        if option["mechanism"] == "alkahest.v1"
    ]
    return {
        "mechanism": "alkahest.v1",
        "option_id": option["option_id"],
        "expiration_unix": 1_800_000_000,
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
                settlement_selection=_alkahest_selection(listing),
            )

        assert result["action"] == "accept"
        assert result["settlement_plan"]["obligations"]
        assert "accepted_escrow_terms" not in result
        assert await _backing(world, listing_id) == "unbacked"
        assert world.site.reservations == {}
        assert (
            await world.db.load_capacity_hold(negotiation_id=result["negotiation_id"])
            is None
        )


@pytest.fixture
async def lifecycle_registry():
    """A clean loop registry and pause flag, as a fresh process has; any timer
    a test started is cancelled and awaited before its event loop closes."""
    await lifecycle.reset_for_tests()
    yield
    await lifecycle.reset_for_tests()


async def test_the_lifecycle_pause_holds_the_loop_while_its_controls_step_it(
    world, lifecycle_registry
):
    # Held before it starts, so the running loop never begins a cycle of its own.
    await world.client.admin_pause_lifecycle_loops()
    _start_lifecycle_loops()
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


async def test_round_zero_evaluation_runs_the_inventory_guard(negotiating_world):
    world = negotiating_world
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
        "settlement_selection": _alkahest_selection(listing),
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
                provision_terms={
                    "kind": "compute.v1",
                    "version": 1,
                    "payload": {"duration_seconds": 3600, "ssh_public_key": ""},
                },
            )

    supported = await evaluate()
    assert supported.decision == "accept"

    # The declaration shrinks below the listing's count and the poller holds
    # it; no publication cycle has run, so the listing is still open and only
    # the guard can notice.
    world.pools[0] = pool("broker-a", backing="unbacked", gpu_count=1)
    await _poll(world)
    refused = await evaluate()

    # A policy rejection refuses the opening, as negotiate/new would.
    assert refused.refused is True
    assert refused.decision == "refused"
    assert "no_matching_declaration" in refused.decision_reason


@pytest.fixture
async def registry_world(tmp_path):
    async with publication_app(
        tmp_path, mechanism_fulfillment=_UNBACKED_PUBLISHABLE
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


async def test_a_listing_every_registry_refused_is_published_once_they_answer(registry_world):
    """A storefront with a candidate to publish while every registry refuses
    records the listing, reports it unconverged at each registry, and closes
    nothing; once the registries answer, the next cycle publishes it to each, in
    the same process."""
    world = registry_world
    world.pools.append(pool("broker-a", backing="unbacked"))
    world.registries.failing = {("publish", url) for url in world.registries.urls}

    refused = await _cycle(world)
    degraded = await world.client.get_system_status()
    (listing_id,) = await _listings(world)
    unpublished = await world.db.load_publications(listing_id=listing_id)
    diverged = await world.db.list_publication_divergence(registry_urls=world.registries.urls)
    world.registries.failing.clear()
    world.registries.sent.clear()
    answered = await _cycle(world)
    published = await world.db.load_publications(listing_id=listing_id)
    converged = await world.db.list_publication_divergence(registry_urls=world.registries.urls)

    assert refused["counts"] == {"publish": 1, "converge": 1, "fail": 1}
    assert [
        (a["action"], a.get("registries"), a.get("reason"))
        for a in refused["actions"]
        if a.get("listing_id") == listing_id
    ] == [
        ("converge", list(world.registries.urls), None),
        ("fail", None, "registry_not_converged"),
    ]
    assert degraded.checks["registry"] == "unreachable"
    assert degraded.status == "degraded"
    assert (await _listing(world, listing_id))["status"] == "open"
    # The storefront records each registry's refusal, and reads both back as
    # not converged.
    assert sorted(row["registry_url"] for row in unpublished) == sorted(world.registries.urls)
    assert all(row["status"] != "published" and row["last_error"] for row in unpublished)
    assert sorted((row["listing_id"], row["registry_url"]) for row in diverged) == sorted(
        (listing_id, url) for url in world.registries.urls
    )

    # Recovered: each registry's record reads published, and nothing diverges.
    assert {row["registry_url"]: row["status"] for row in published} == {
        url: "published" for url in world.registries.urls
    }
    assert converged == []
    assert (await _listing(world, listing_id))["status"] == "open"
    assert answered["counts"] == {"converge": 1}
    assert sorted(url for url, _ in world.registries.to("publish", listing_id)) == sorted(
        world.registries.urls
    )
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


def _entry(report: dict, kind: str, reason: str, pool_id: str) -> dict | None:
    """The one ``kind`` entry a site's derivation gives ``pool_id`` for ``reason``."""
    (entry, *more) = [
        item
        for item in report[kind]
        if item["reason"] == reason and item.get("pool_id") == pool_id
    ] or [None]
    assert more == []
    return entry


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
    assert (await _cycle(world))["counts"] == {"close": 1, "report": 1}

    (finding,) = _entry(
        await _report(world), "reports", "listing_shape_infeasible", "broker-a"
    )["shapes"]
    assert finding["not_feasible_against"] == "declared"


async def test_backed_memory_being_taken_makes_a_stated_shape_unpublishable(capacity_world):
    capacity_world.pools.append(_shaped(backing="backed"))
    assert (await _cycle(capacity_world))["counts"] == {"publish": 1}

    capacity_world.pools[0] = _shaped(backing="backed", available={**_BIG, "ram_gb": 8})
    assert (await _cycle(capacity_world))["counts"] == {"close": 1, "report": 1}
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
                settlement_selection=_alkahest_selection(listing),
            )

        assert result["action"] == "accept"
        (reservation,) = world.site.reservations.values()
        assert reservation["dimensions"] == {
            "gpu_count": 1, "vcpu_count": 8, "ram_gb": 32, "disk_gb": 100,
        }


_CPU_SHAPE = {"cpu": {"count": 16}, "memory": {"gib": 64}}
_CPU_HOST = {"vcpu_count": 64, "ram_gb": 512}


async def test_a_shape_without_gpus_publishes_no_gpu_field_and_refreshes_without_one(world):
    """Spec scenario "A pool states a shape with no GPUs", its publication: the
    claim it reserves with is the deal path's to prove."""
    world.pools.append(
        _shaped("cpu", gpu_model=None, capacity=_CPU_HOST, shapes=(_CPU_SHAPE,))
    )

    assert (await _cycle(world))["counts"] == {"publish": 1}

    ((listing_id, listing),) = (await _listings(world)).items()
    published = world.registries.to("publish", listing_id)
    assert len(published) == len(world.registries.urls)
    body = published[0][1]["listing_resource"]
    assert body == listing["listing_resource"]
    assert (body["vcpu_count"], body["ram_gb"]) == (16, 64)
    assert "gpu_count" not in body and "gpu_model" not in body
    assert all(other["listing_resource"] == body for _, other in published)

    world.registries.sent.clear()
    world.set_settlement_clauses([settlement_clause(rate="250")])
    assert (await _cycle(world))["counts"] == {"refresh": 1}

    # A refresh sends every registry the same resource, still with no GPU key.
    refreshed = world.registries.to("publish", listing_id)
    assert len(refreshed) == len(world.registries.urls)
    assert all(other["listing_resource"] == body for _, other in refreshed)


async def test_default_shapes_close_once_the_pools_members_declare_no_gpus(world):
    """Spec scenario "A pool whose members declare no GPUs states no shapes":
    listings derived from its default shapes close, and the pool is reported."""
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=2))
    await _cycle(world)
    assert len(await _listings(world)) == 2

    world.pools[0] = pool("broker-a", backing="unbacked", gpu_model=None, capacity=_CPU_HOST)
    result = await _cycle(world)

    assert result["counts"].get("close") == 2 and "publish" not in result["counts"]
    assert await _listings(world) == {}
    assert _entry(await _report(world), "reports", "listing_shapes_required", "broker-a")


async def test_a_shape_without_gpus_on_a_gpu_host_negotiates_and_reserves_no_gpu(tmp_path):
    """Spec scenario "A GPU host's spare capacity sells as a VM without GPUs":
    the listing opens a negotiation, and its acceptance hold, admitted on the GPU
    host, holds the shape's vCPU and memory and none of its GPUs."""
    cpu_shape = {"cpu": {"count": 8}, "memory": {"gib": 32}}
    async with publication_app(tmp_path, negotiation=True) as world:
        world.pools.append(_shaped(backing="backed", shapes=(cpu_shape,)))
        world.site.add_resource(
            "broker-a", 2,
            attributes={"gpu_model": "H100", "region": "us-east"},
            capacity=_BIG,
        )
        assert (await _cycle(world))["counts"] == {"publish": 1}
        ((listing_id, listing),) = (await _listings(world)).items()
        assert "gpu_count" not in listing["listing_resource"]
        assert "gpu_model" not in listing["listing_resource"]
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
                settlement_selection=_alkahest_selection(listing),
            )

        assert result["action"] == "accept"
        (reservation,) = world.site.reservations.values()
        assert reservation["dimensions"] == {"vcpu_count": 8, "ram_gb": 32}
        assert reservation["units"] == 0
        assert world.site.available_dimensions("broker-a")["gpu_count"] == 2


async def test_a_pool_without_gpus_stating_no_shapes_publishes_nothing_and_is_reported(world):
    """Spec scenario "A pool whose members declare no GPUs states no shapes"."""
    world.pools.append(pool("cpu", backing="unbacked", gpu_model=None, capacity=_CPU_HOST))

    result = await _cycle(world)

    assert "publish" not in result["counts"]
    assert await _listings(world) == {}
    entry = _entry(await _report(world), "reports", "listing_shapes_required", "cpu")
    assert entry is not None
    assert "GPU shapes only" in entry["message"]
    assert "listing_shapes" in entry["message"]


async def test_a_pool_priced_only_per_gpu_model_refuses_its_shape_without_gpus(world):
    cpu_shape = {"cpu": {"count": 8}, "memory": {"gib": 32}}
    world.pools.append(
        _shaped(
            shapes=(_SHAPE, cpu_shape),
            pricing={"gpu": {"H100": {"settlements": [settlement_clause()]}}},
        )
    )

    with replaced_setting("pricing.settlements", []):
        await _cycle(world)
        listings = await _listings(world)
        derivation = await _derivation(world)

    ((_, listing),) = listings.items()
    assert listing["listing_resource"]["gpu_model"] == "H100"
    (refusal,) = derivation["refusals"]
    assert (refusal["reason"], refusal["pool_id"]) == ("no_settlement_option", "broker-a")
    assert refusal["shape_digest"] == resolve_shape(cpu_shape).digest


# ---------------------------------------------------------------------------
# Shape admissibility
# ---------------------------------------------------------------------------


def _gpu(count) -> dict:
    return {**_SHAPE, "gpu": {"count": count, "model": "H100"}}


async def test_the_configured_default_reaches_every_tier_of_a_cycle(tmp_path):
    """The parsed ``[admissibility.defaults.vm]`` bounds generated shapes, withholds
    a stated offer it excludes, and withholds a listing whose range it empties, each
    stated finding reported in system status. That such a listing, once open,
    closes is the reconciler's derivation-level evidence; the closing of a
    published listing is the next case's."""
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=_UNBACKED_PUBLISHABLE,
        admissibility_default={"gpu": {"count": {"max": 1}}},
    ) as world:
        world.pools.append(pool("generated", backing="unbacked", capacity=_BIG))
        world.pools.append(
            _shaped(
                "stated",
                shapes=(
                    _SHAPE,
                    _gpu(2),
                    {**_SHAPE, "cpu": {"count": 4}, "gpu": {"count": {"offer": 2, "min": 2}, "model": "H100"}},
                ),
            )
        )

        # Each stated finding is also a report of the cycle's.
        assert (await _cycle(world))["counts"] == {"publish": 2, "report": 2}

        published = {
            (row["listing_resource"]["pool_id"], row["listing_resource"]["gpu_count"])
            for row in (await _listings(world)).values()
        }
        assert published == {("generated", 1), ("stated", 1)}
        report = await _report(world)
        (excluded,) = _entry(
            report, "reports", "listing_shape_inadmissible", "stated"
        )["findings"]
        assert excluded["tier"] == "pool_hint"
        assert [problem["tier"] for problem in excluded["problems"]] == ["configured_default"]
        (unusable,) = _entry(
            report, "reports", "shape_constraints_unusable", "stated"
        )["findings"]
        assert {bound["tier"] for bound in unusable["bounds"]} == {
            "pool_hint", "configured_default",
        }
        assert _entry(report, "reports", "listing_shape_inadmissible", "generated") is None


async def test_a_hint_constraint_tightened_past_a_published_offer_closes_it(tmp_path):
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=_UNBACKED_PUBLISHABLE,
        admissibility_default={"gpu": {"count": {"max": 1}}},
    ) as world:
        # The hint widens the configured default for this listing alone.
        widened = {**_SHAPE, "gpu": {"count": {"offer": 2, "max": 2}, "model": "H100"}}
        world.pools.append(_shaped(shapes=(_SHAPE, widened)))
        await _cycle(world)
        before = await _listings(world)
        (two_gpu,) = [
            listing_id for listing_id, row in before.items()
            if row["listing_resource"]["gpu_count"] == 2
        ]

        # A change to the constraints alone keeps the listing's identity.
        world.pools[0] = _shaped(
            shapes=(_SHAPE, {**widened, "gpu": {"count": {"offer": 2, "max": 4}, "model": "H100"}})
        )
        assert "close" not in (await _cycle(world))["counts"]
        assert set(await _listings(world)) == set(before)

        # Without its own maximum, the configured default's governs the offer.
        world.pools[0] = _shaped(
            shapes=(_SHAPE, {**widened, "gpu": {"count": {"offer": 2}, "model": "H100"}})
        )
        assert (await _cycle(world))["counts"] == {"close": 1, "report": 1}

        closed = await _listing(world, two_gpu)
        assert (closed["status"], closed["closed_by"]) == ("closed", "reconciliation")
        assert set(await _listings(world)) == set(before) - {two_gpu}


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


# -- shape-priced listings -----------------------------------------------------


def _rateless_clause() -> dict:
    clause = settlement_clause()
    del clause["rate"], clause["per"]
    return clause


def _gpu_rates(rate: str, asset: str | None = None) -> dict:
    asset = asset or settlement_clause()["asset"]
    return {"gpu": {"H100": {"rates": [{"asset": asset, "rate": rate, "per": "hour"}]}}}


async def test_shape_priced_listings_publish_composed_rates_and_record_their_structure(
    registry_world,
):
    world = registry_world
    world.set_settlement_clauses([_rateless_clause()])
    world.pools.append(
        pool("broker-a", backing="unbacked", gpu_count=2, pricing=_gpu_rates("80"))
    )

    assert (await _cycle(world))["counts"] == {"publish": 2}

    listings = await _listings(world)
    rates = {
        row["listing_resource"]["gpu_count"]: row["accepted_escrows"][0]["rates"][0]["value"]
        for row in listings.values()
    }
    assert rates == {1: "80", 2: "160"}
    for listing_id, row in listings.items():
        assert (await _listing(world, listing_id))["rate_structure"] == {
            "gpu": _gpu_rates("80")["gpu"]["H100"]["rates"]
        }
        # A registry receives the composed rate and never the structure.
        for _, body in world.registries.to("publish", listing_id):
            assert "rate_structure" not in body
            assert body["accepted_escrows"] == row["accepted_escrows"]


async def test_a_family_rate_change_refreshes_shape_priced_listings_in_place(world):
    world.set_settlement_clauses([_rateless_clause()])
    world.pools.append(
        pool("broker-a", backing="unbacked", gpu_count=2, pricing=_gpu_rates("80"))
    )
    await _cycle(world)
    before = await _listings(world)

    world.pools[0] = pool(
        "broker-a", backing="unbacked", gpu_count=2, pricing=_gpu_rates("90")
    )
    result = await _cycle(world)

    after = await _listings(world)
    assert set(after) == set(before)
    assert result["counts"] == {"refresh": 2}
    assert {
        row["accepted_escrows"][0]["rates"][0]["value"] for row in after.values()
    } == {"90", "180"}


async def test_the_recorded_structure_holds_families_the_shape_omits(world):
    world.set_settlement_clauses([_rateless_clause()])
    asset = settlement_clause()["asset"]
    memory = [{"asset": asset, "rate": "1", "per": "hour"}]
    world.pools.append(
        pool(
            "broker-a",
            backing="unbacked",
            pricing={**_gpu_rates("80"), "memory": {"rates": memory}},
        )
    )
    await _cycle(world)
    (listing_id,) = await _listings(world)

    # A GPU-only default shape: memory does not price it, but is recorded so a
    # revised shape naming memory can be priced from the record.
    listing = await _listing(world, listing_id)
    assert listing["accepted_escrows"][0]["rates"][0]["value"] == "80"
    assert listing["rate_structure"] == {
        "gpu": _gpu_rates("80")["gpu"]["H100"]["rates"],
        "memory": memory,
    }


async def test_a_shape_priced_listing_that_would_be_free_is_refused_and_never_posted(
    world,
):
    world.set_settlement_clauses([_rateless_clause()])
    world.pools.append(
        pool(
            "broker-a",
            backing="unbacked",
            pricing=_gpu_rates("80", asset="0x" + "33" * 20),
        )
    )

    result = await _cycle(world)

    # The family the pool's rates leave uncharged is reported beside the refusal.
    assert result["counts"] == {"refuse": 1, "report": 1}
    assert await _listings(world) == {}


# -- candidates with no settlement option -----------------------------------

#: What an oracle-gated Alkahest section naming no oracle reports: unready for
#: its configuration, whatever its chain answers.
_RULED_OUT = ReadinessBlocker(
    code="alkahest.oracle_policy_invalid",
    message="Settlement.alkahest.oracle_gated requires a trusted oracle",
    kind="configuration",
)
#: What Alkahest reports before its chain probe has reached the chain.
_UNREACHED = ReadinessBlocker(
    code="alkahest.chain_unreachable",
    message="chain anvil has not been probed",
    kind="reachability",
)


def _closes(report: dict) -> dict[str, str]:
    return {
        item["listing_id"]: item["reason"]
        for item in report["actions"]
        if item["action"] == "close"
    }


def _of(report: dict, action: str) -> list[dict]:
    return [item for item in report["actions"] if item["action"] == action]


async def _derivation(world) -> dict:
    return (await world.client.get_system_status()).publication_derivation[SITE]


async def test_a_listing_whose_only_mechanism_is_configured_away_closes_and_reopens(
    capacity_world,
):
    """Spec scenario "An open listing loses its last option to configuration",
    on VM: the listing closes as `no_settlement_option`, the refusal is in the
    site's derivation, and the listing reopens under its identity once its
    option builds again."""
    capacity_world.pools.append(pool("pool-a", backing="backed", gpu_count=1))
    await _cycle(capacity_world)
    (listing_id,) = await _listings(capacity_world)

    capacity_world.composition.alkahest_blocker = _RULED_OUT
    unready = await _cycle(capacity_world)
    closed = await _listing(capacity_world, listing_id)
    derivation = await _derivation(capacity_world)
    capacity_world.composition.alkahest_blocker = None
    restored = await _cycle(capacity_world)

    assert _closes(unready) == {listing_id: "no_settlement_option"}
    assert (closed["status"], closed["closed_by"]) == ("closed", "reconciliation")
    (refusal,) = derivation["refusals"]
    assert (refusal["reason"], refusal["pool_id"], refusal["mechanisms"]) == (
        "no_settlement_option",
        "pool-a",
        ["alkahest.v1"],
    )
    assert derivation["holds"] == []
    assert [item["listing_id"] for item in _of(restored, "reopen")] == [listing_id]
    assert set(await _listings(capacity_world)) == {listing_id}


#: The harness's settlement root with Alkahest, its only mechanism, disabled.
_ALKAHEST_DISABLED = {"schema_version": 1, "priority": [], "alkahest": {"enabled": False}}


@pytest.mark.parametrize("clause_source", ["pool-hint", "configured"])
async def test_a_listing_whose_mechanism_is_disabled_closes_and_reopens(
    capacity_world, clause_source
):
    """A disabled section is the storefront's configuration ruling its
    mechanism out, so a listing whose only clause names it closes as
    `no_settlement_option`, as bare metal's does, and reopens under its
    identity once the section is enabled again: whether the clause is its
    pool's own pricing hint or the storefront's configured
    `[pricing].settlements`."""
    if clause_source == "pool-hint":
        hinted = {"gpu": {"H100": {"settlements": [settlement_clause()]}}}
        capacity_world.pools.append(
            pool("pool-a", backing="backed", gpu_count=1, pricing=hinted)
        )
        configured = []
    else:
        capacity_world.pools.append(pool("pool-a", backing="backed", gpu_count=1))
        configured = [settlement_clause()]
    with replaced_setting("pricing.settlements", configured):
        await _cycle(capacity_world)
        (listing_id,) = await _listings(capacity_world)
        with replaced_setting("settlement", _ALKAHEST_DISABLED):
            disabled = await _cycle(capacity_world)
            closed = await _listing(capacity_world, listing_id)
            derivation = await _derivation(capacity_world)
        restored = await _cycle(capacity_world)
        reopened = await _listing(capacity_world, listing_id)

    assert _closes(disabled) == {listing_id: "no_settlement_option"}
    assert "publish" not in disabled["counts"]
    assert (closed["status"], closed["closed_by"]) == ("closed", "reconciliation")
    (refusal,) = derivation["refusals"]
    assert (refusal["reason"], refusal["pool_id"], refusal["mechanisms"]) == (
        "no_settlement_option",
        "pool-a",
        ["alkahest.v1"],
    )
    assert [item["listing_id"] for item in _of(restored, "reopen")] == [listing_id]
    assert (reopened["status"], reopened.get("closed_by")) == ("open", None)


async def test_a_listing_whose_pool_resolves_no_clause_closes_and_reopens(capacity_world):
    """Spec scenario "A pool resolves no settlement clause", on VM."""
    capacity_world.pools.append(pool("pool-a", backing="backed", gpu_count=1))
    await _cycle(capacity_world)
    (listing_id,) = await _listings(capacity_world)

    with replaced_setting("pricing.settlements", []):
        unclaused = await _cycle(capacity_world)
        closed = await _listing(capacity_world, listing_id)
    restored = await _cycle(capacity_world)

    assert _closes(unclaused) == {listing_id: "no_settlement_option"}
    assert "publish" not in unclaused["counts"]
    assert (closed["status"], closed["closed_by"]) == ("closed", "reconciliation")
    assert [item["listing_id"] for item in _of(restored, "reopen")] == [listing_id]


async def test_an_unknown_mechanism_with_no_open_listing_is_refused_not_held(capacity_world):
    """A candidate with no listing has nothing to hold, so an unknown mechanism
    is recorded as its refusal."""
    capacity_world.composition.alkahest_blocker = _UNREACHED
    capacity_world.pools.append(pool("pool-a", backing="backed", gpu_count=1))

    await _cycle(capacity_world)
    derivation = await _derivation(capacity_world)

    assert await _listings(capacity_world) == {}
    assert derivation["holds"] == []
    (refusal,) = derivation["refusals"]
    assert (refusal["reason"], refusal["mechanisms"]) == (
        "settlement_mechanism_unknown",
        ["alkahest.v1"],
    )


async def test_a_listing_whose_only_mechanisms_chain_is_unreached_is_held(capacity_world):
    """Spec scenario "An open listing's mechanism is unreachable": the listing
    stays open on its last-published terms, and the derivation records a hold."""
    capacity_world.pools.append(pool("pool-a", backing="backed", gpu_count=1))
    await _cycle(capacity_world)
    before = await _listings(capacity_world)
    (listing_id,) = before

    capacity_world.composition.alkahest_blocker = _UNREACHED
    report = await _cycle(capacity_world)

    assert await _listings(capacity_world) == before
    assert _closes(report) == {} and _of(report, "refuse") == []
    (hold,) = (await _derivation(capacity_world))["holds"]
    assert (hold["reason"], hold["pool_id"], hold["mechanisms"]) == (
        "settlement_mechanism_unknown",
        "pool-a",
        ["alkahest.v1"],
    )
    assert (await _listing(capacity_world, listing_id))["accepted_escrows"]


async def test_an_unreached_mechanism_beside_one_ruled_out_holds_the_listing(tmp_path):
    """Spec scenario "An unreachable mechanism beside one ruled out by
    configuration": a listing published with only its Alkahest option, beside
    contact exchange that gives its origin no contact, is held once Alkahest's
    chain is unreached, because the offer it published is one the storefront
    would make again once the chain answers."""
    async with publication_app(
        tmp_path,
        contacts={SITE_B: {"email": "sales@other-seller.invalid"}},
        second_site=True,
    ) as world:
        world.pools.append(pool("pool-a", backing="backed", gpu_count=1))
        with replaced_setting("pricing.settlements", [settlement_clause(), contact_clause()]):
            await _cycle(world)
            before = await _listings(world)
            world.composition.alkahest_blocker = _UNREACHED
            report = await _cycle(world)
            after = await _listings(world)
            derivation = await _derivation(world)

    (listing,) = before.values()
    assert [option["mechanism"] for option in listing["settlement_options"]] == [
        "alkahest.v1"
    ]
    assert after == before
    assert _closes(report) == {} and _of(report, "refuse") == []
    (hold,) = derivation["holds"]
    assert (hold["reason"], hold["mechanisms"]) == (
        "settlement_mechanism_unknown",
        ["alkahest.v1"],
    )


async def test_a_mechanism_both_misconfigured_and_unreached_closes_its_listing(
    capacity_world,
):
    """Spec scenario "A mechanism with both kinds of blocker"."""
    capacity_world.pools.append(pool("pool-a", backing="backed", gpu_count=1))
    await _cycle(capacity_world)
    (listing_id,) = await _listings(capacity_world)

    # Both kinds at once, as the preflight reports an oracle-gated section
    # naming no oracle whose chain is down.
    capacity_world.composition.alkahest_blockers = (_RULED_OUT, _UNREACHED)
    report = await _cycle(capacity_world)

    assert _closes(report) == {listing_id: "no_settlement_option"}


async def test_a_stored_override_leaving_no_admissible_clause_closes_the_unbacked_listing(
    tmp_path,
):
    """Spec scenario "A pool override leaves no admissible clause": an open
    unbacked listing whose stored override comes to name only a mechanism VM
    fulfils through capacity is refused with no admissible mechanism and
    closed, and reopens under its identity once the override offers contact
    exchange again."""
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE: {"email": "sales@seller.invalid"}},
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked", gpu_count=1))
        await offer_introduction(world, SITE, "broker-a")
        await _cycle(world)
        (listing_id,) = await _listings(world)

        await PoolOverrideClient(world.client).put_pool_override(
            {
                "site_id": SITE,
                "pool_id": "broker-a",
                "offering_mode": "vm",
                "settlements": [settlement_clause()],
            }
        )
        refused = await _cycle(world)
        closed = await _listing(world, listing_id)
        derivation = await _derivation(world)
        await offer_introduction(world, SITE, "broker-a")
        restored = await _cycle(world)
        reopened = await _listings(world)

    assert _closes(refused) == {listing_id: "no_settlement_option"}
    assert "publish" not in refused["counts"]
    assert (closed["status"], closed["closed_by"]) == ("closed", "reconciliation")
    (refusal,) = derivation["refusals"]
    assert (refusal["reason"], refusal["pool_id"], refusal["mechanisms"]) == (
        "no_settlement_option",
        "broker-a",
        [],
    )
    assert [item["listing_id"] for item in _of(restored, "reopen")] == [listing_id]
    assert set(reopened) == {listing_id}


async def test_an_unreached_mechanism_the_unbacked_listing_cannot_publish_holds_nothing(
    tmp_path,
):
    """Spec scenario "An unreachable mechanism the candidate could never
    publish": a restarted storefront whose configuration no longer gives the
    listing's origin a contact closes its unbacked contact listing, although
    Alkahest's chain is unreached, since unbacked VM supply cannot publish
    Alkahest."""
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE: {"email": "sales@seller.invalid"}},
        second_site=True,
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked", gpu_count=1))
        with replaced_setting("pricing.settlements", [settlement_clause(), contact_clause()]):
            await _cycle(world)
            (listing_id,) = await _listings(world)

    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE_B: {"email": "sales@other-seller.invalid"}},
        second_site=True,
    ) as restarted:
        restarted.pools.append(pool("broker-a", backing="unbacked", gpu_count=1))
        restarted.composition.alkahest_blocker = _UNREACHED
        with replaced_setting("pricing.settlements", [settlement_clause(), contact_clause()]):
            report = await _cycle(restarted)
        derivation = await _derivation(restarted)

    assert _closes(report) == {listing_id: "no_settlement_option"}
    assert derivation["holds"] == []
    (refusal,) = derivation["refusals"]
    assert refusal["mechanisms"] == [CONTACT_MECHANISM]


async def test_a_contact_only_candidate_whose_origin_has_no_contact_yields_no_listing(
    tmp_path,
):
    """Spec scenario "An unbacked candidate's origin has no contact"."""
    async with publication_app(
        tmp_path,
        mechanism_fulfillment=CONTACT_PUBLISHABLE,
        contacts={SITE_B: {"email": "sales@other-seller.invalid"}},
        second_site=True,
    ) as world:
        world.pools.append(pool("broker-a", backing="unbacked", gpu_count=1))
        await offer_introduction(world, SITE, "broker-a")
        report = await _cycle(world)
        listings = await _listings(world)
        derivation = await _derivation(world)

    assert listings == {}
    assert "publish" not in report["counts"]
    (refusal,) = derivation["refusals"]
    assert (refusal["reason"], refusal["pool_id"]) == ("no_settlement_option", "broker-a")
    assert refusal["shape_digest"]


def _stored_terms(row: dict) -> tuple:
    return tuple(
        row.get(name)
        for name in ("accepted_escrows", "settlement_options", "demands", "max_duration_seconds")
    )


@pytest.mark.parametrize("form", ["pool-hint-mapping", "configured-dsl-text"])
async def test_a_clause_that_cannot_be_read_never_closes_its_listing(capacity_world, form):
    """A clause naming Alkahest, whose section is disabled, that Alkahest
    cannot read -- a mapping with a field the clause does not define, or DSL
    text stating Alkahest's fields unqualified -- is a defect, not Alkahest
    ruled out: the candidate is refused as `payload_unbuildable` under its
    site, and its open listing keeps its identity and terms and publishes
    nothing. A readable clause naming the disabled mechanism closes it
    (`test_a_listing_whose_mechanism_is_disabled_closes_and_reopens`)."""
    capacity_world.pools.append(pool("pool-a", backing="backed", gpu_count=1))
    await _cycle(capacity_world)
    (listing_id,) = await _listings(capacity_world)
    before = await _listing(capacity_world, listing_id)
    asset = settlement_clause()["asset"]
    if form == "pool-hint-mapping":
        capacity_world.pools[0] = pool(
            "pool-a",
            backing="backed",
            gpu_count=1,
            pricing={"gpu": {"H100": {"settlements": [{**settlement_clause(), "unknown": True}]}}},
        )
        defaults: dict = {}
    else:
        # The configured per-model default, given as JSON text holding DSL
        # clauses: the one route by which clause text reaches a VM cycle.
        defaults = {
            "gpu": {
                "H100": {
                    "settlements": json.dumps(
                        [
                            f"mechanism=alkahest asset={asset} rate=100/hour chain=anvil "
                            "escrow_kind=erc20_escrow_obligation_default"
                        ]
                    )
                }
            }
        }
    sent = len(capacity_world.registries.sent)
    # Replaced at its root: `pricing.defaults` is unset in the harness, and
    # unsetting a dotted key on exit would leave the table for later tests.
    pricing = {
        **dict(storefront_config.settings.get("pricing") or {}),
        "settlements": [],
        "defaults": defaults,
    }

    with (
        replaced_setting("pricing", pricing),
        replaced_setting("settlement", _ALKAHEST_DISABLED),
    ):
        report = await _cycle(capacity_world)
        after = await _listing(capacity_world, listing_id)
        derivation = await _derivation(capacity_world)

    assert set(await _listings(capacity_world)) == {listing_id}
    assert (after["status"], after.get("closed_by")) == ("open", None)
    assert _stored_terms(after) == _stored_terms(before)
    assert len(capacity_world.registries.sent) == sent
    assert _closes(report) == {} and "publish" not in report["counts"]
    assert derivation["holds"] == []
    (refusal,) = derivation["refusals"]
    assert (refusal["reason"], refusal["pool_id"]) == ("payload_unbuildable", "pool-a")


_SITE_CONTACT = {SITE: {"email": "sales@seller.invalid"}}


async def _unbacked_contact_listing(world) -> str:
    world.pools.append(pool("broker-a", backing="unbacked", gpu_count=1))
    await offer_introduction(world, SITE, "broker-a")
    await _cycle(world)
    (listing_id,) = await _listings(world)
    return listing_id


async def _override_clauses(world, *clauses: dict) -> None:
    await PoolOverrideClient(world.client).put_pool_override(
        {
            "site_id": SITE,
            "pool_id": "broker-a",
            "offering_mode": "vm",
            "settlements": list(clauses),
        }
    )


async def test_a_disabled_mechanism_an_unbacked_listing_cannot_publish_is_not_classified(
    tmp_path,
):
    """Admissibility comes before classification: an unbacked listing whose
    override names only Alkahest, which unbacked VM supply cannot publish,
    closes with no mechanism named once Alkahest is disabled. The disabled
    mechanism is outside what the listing could publish, so it is not reported
    as ruled out."""
    async with publication_app(
        tmp_path, mechanism_fulfillment=CONTACT_PUBLISHABLE, contacts=_SITE_CONTACT
    ) as world:
        listing_id = await _unbacked_contact_listing(world)
        await _override_clauses(world, settlement_clause())
        alkahest_off = {
            **contact_settlement(_SITE_CONTACT),
            "priority": [CONTACT_MECHANISM],
            "alkahest": {"enabled": False},
        }
        with (
            replaced_setting("pricing.settlements", []),
            replaced_setting("settlement", alkahest_off),
        ):
            report = await _cycle(world)
            derivation = await _derivation(world)

    assert _closes(report) == {listing_id: "no_settlement_option"}
    (refusal,) = derivation["refusals"]
    assert (refusal["reason"], refusal["mechanisms"]) == ("no_settlement_option", [])


async def test_only_the_admissible_mechanisms_of_a_mixed_list_are_classified(tmp_path):
    """An unbacked listing whose override names Alkahest, unreached, and
    contact exchange, disabled, closes naming contact exchange alone: the
    disabled mechanism it could publish is ruled out, and Alkahest, which it
    could never publish, is neither ruled out nor unknown, so its outage holds
    nothing."""
    async with publication_app(
        tmp_path, mechanism_fulfillment=CONTACT_PUBLISHABLE, contacts=_SITE_CONTACT
    ) as world:
        listing_id = await _unbacked_contact_listing(world)
        await _override_clauses(world, settlement_clause(), contact_clause())
        settlement = contact_settlement(_SITE_CONTACT)
        contact_off = {
            **settlement,
            "priority": ["alkahest.v1"],
            "contact": {**settlement["contact"], "enabled": False},
        }
        world.composition.alkahest_blocker = _UNREACHED
        with replaced_setting("settlement", contact_off):
            report = await _cycle(world)
            derivation = await _derivation(world)

    assert _closes(report) == {listing_id: "no_settlement_option"}
    assert derivation["holds"] == []
    (refusal,) = derivation["refusals"]
    assert (refusal["reason"], refusal["mechanisms"]) == (
        "no_settlement_option",
        [CONTACT_MECHANISM],
    )
