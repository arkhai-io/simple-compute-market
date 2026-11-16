"""Recurring publication and the cached-acceptance door through the served VM
storefront.

Carried from ``domains/vms/storefront/tests/integration/test_publication_loop.py``;
restored there, these cases join that module, whose helpers ``_listings``,
``_listing``, ``_row`` and ``_vm_provision`` are repeated here as they stood.
Each runs over ``recurring_world``, which stands fixtures at the recurring encoder,
term-timing and billing-projection ports.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict

import pytest
from storefront_client import StorefrontClientError

from tests.fixtures.publication_cycle import validate_cycle_report
from tests.recurring_world import (
    AVAILABLE_UNTIL,
    MAX_DURATION_SECONDS,
    MECHANISM,
    PAYEE,
    QUALIFIED,
    recurring_world,
    undeclared,
)
from tests.recurring_world import clauses as recurring_clauses

pytestmark = pytest.mark.asyncio


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


def _vm_provision(duration_seconds: int = 3600) -> dict:
    return {
        "kind": "compute.v1",
        "version": 1,
        "payload": {"duration_seconds": duration_seconds, "ssh_public_key": ""},
    }


# The servicing declaration at the publication and cached-acceptance doors.


def _recurring(options: list[dict]) -> list[dict]:
    return [option for option in options if "period" in option["settlement"]]


def _derived_class(option: dict) -> str:
    """The class a buyer reads off an option: billed once is reserved; billed per
    period, a payee entitlement makes it spot and its absence on-demand."""
    if "period" not in option["settlement"]:
        return "reserved"
    entitlements = option["lifecycle"]["early_termination"]["entitlements"]
    return "spot" if "payee" in entitlements else "on-demand"


async def test_one_listing_offers_reserved_on_demand_and_spot_on_its_capacity_identity(
    tmp_path,
):
    """Declaring rate servicing adds the on-demand and spot options to the
    listing the pool already publishes, beside its reserved Alkahest and once
    payment options: the same listing and shape, publishing both bounds, each
    option separately identified, and the class each derives from its billing
    and entitlements, never a stored field."""
    async with recurring_world(tmp_path, treatments=None) as world:
        validate_cycle_report(await world.publish())
        ((listing_id, dark),) = (await _listings(world.app)).items()

        world.declare(QUALIFIED)
        validate_cycle_report(await world.publish())
        listings = await _listings(world.app)
        listing = await _listing(world.app, listing_id)

    assert [_derived_class(option) for option in dark["settlement_options"]] == ["reserved"] * 2
    assert list(listings) == [listing_id]
    assert listing["listing_resource"] == dark["listing_resource"]
    assert (listing["max_duration_seconds"], listing["available_until_utc"]) == (
        MAX_DURATION_SECONDS, AVAILABLE_UNTIL,
    )
    options = listing["settlement_options"]
    assert {option["option_id"] for option in dark["settlement_options"]} < {
        option["option_id"] for option in options
    }
    assert sorted(
        (option["settlement"]["schema"], _derived_class(option)) for option in options
    ) == [
        ("alkahest.v1", "reserved"),
        (MECHANISM, "on-demand"),
        (MECHANISM, "reserved"),
        (MECHANISM, "spot"),
    ]
    assert len({option["option_id"] for option in options}) == 4
    assert all("class" not in option and "class" not in option.get("lifecycle", {})
               for option in options)


async def test_publication_omits_recurring_options_whose_treatments_are_undeclared(
    tmp_path,
):
    """A recurring option publishes only under a declaration qualifying every
    treatment it names. Narrowing the declaration omits both recurring options on
    the next cycle, each with its diagnostic, while the reserved and once options
    keep the listing's capacity identity."""
    async with recurring_world(tmp_path) as world:
        report = await world.publish()
        validate_cycle_report(report)
        ((listing_id, listing),) = (await _listings(world.app)).items()
        published = listing["settlement_options"]
        recurring = _recurring(published)
        assert (len(published), len(recurring)) == (4, 2)
        assert not undeclared(report)
        peers = {option["option_id"] for option in published if option not in recurring}

        world.declare(frozenset({"charged"}))
        report = await world.publish()
        validate_cycle_report(report)
        listings = await _listings(world.app)

    assert list(listings) == [listing_id]
    assert {option["option_id"] for option in listings[listing_id]["settlement_options"]} == peers
    refusals = undeclared(report)
    assert len(refusals) == 2
    assert all("does not declare returned" in item["detail"] for item in refusals)


async def test_an_on_demand_option_stating_no_penalty_publishes_the_configured_multiple(
    tmp_path,
):
    """The on-demand preset states no premature-stop penalty, so it publishes its
    per-period price, 625000 at 2.5 an hour per 15 minutes, times the composition's
    configured multiple; spot, which carries a seller stop, publishes none."""
    async with recurring_world(tmp_path, default_penalty_periods=6) as world:
        validate_cycle_report(await world.publish())
        ((_listing_id, listing),) = (await _listings(world.app)).items()

    penalties = {
        "payee" in option["lifecycle"]["early_termination"]["entitlements"]:
            option["lifecycle"]["early_termination"].get("premature_stop_penalty")
        for option in _recurring(listing["settlement_options"])
    }
    assert penalties == {False: str(625000 * 6), True: None}


@pytest.mark.parametrize(("clause_deadline", "refused"), [(900, 0), (None, 3)],
                         ids=["clause-configured", "neither"])
async def test_a_clause_s_deadline_publishes_where_the_pool_supplies_none(
    tmp_path, clause_deadline, refused,
):
    """With no pool deadline, each payment option, once or recurring, publishes the
    deadline its clause configures and no default buyer's refusal is reported; a
    clause configuring none publishes no deadline, and each payment option is
    reported as refused by a default buyer for lacking one."""
    async with recurring_world(
        tmp_path, pool_deadline=None, published=recurring_clauses(delivery_deadline_seconds=clause_deadline),
    ) as world:
        report = await world.publish()
        validate_cycle_report(report)
        ((_listing_id, listing),) = (await _listings(world.app)).items()

    payments = [option for option in listing["settlement_options"]
                if option["settlement"]["schema"] == MECHANISM]
    assert len(payments) == 3
    assert {option["lifecycle"].get("delivery_deadline_seconds") for option in payments} == {clause_deadline}
    refusals = [item for item in report["actions"] if item.get("reason") == "default_buyer_refusal"]
    assert len(refusals) == refused
    assert all(item["detail"].endswith("no delivery deadline") for item in refusals)


def _negotiation_rows(db) -> list[tuple]:
    with sqlite3.connect(db.db_path) as connection:
        return connection.execute(
            "SELECT * FROM negotiation_threads ORDER BY negotiation_id"
        ).fetchall()


async def test_a_cached_recurring_selection_whose_treatment_is_withdrawn_is_refused(
    tmp_path,
):
    """A buyer holding a recurring option published under the full declaration
    selects it after the storefront stops declaring one of its treatments: the
    seller answers the signed 409 asking for a refetch, and writes no negotiation."""
    async with recurring_world(tmp_path) as world:
        await world.publish()
        ((listing_id, listing),) = (await _listings(world.app)).items()
        on_demand = next(
            option for option in _recurring(listing["settlement_options"])
            if "payee" not in option["lifecycle"]["early_termination"]["entitlements"]
        )
        world.declare(frozenset({"charged"}))
        before = _negotiation_rows(world.app.db)

        with pytest.raises(StorefrontClientError) as refused:
            await world.app.buyer.negotiate_new(
                listing_id=listing_id,
                initial_amount=1,
                provision_terms=_vm_provision(3600),
                settlement_selection={
                    "option_id": on_demand["option_id"],
                    "settlement": {"schema": MECHANISM, "payer_account": PAYEE},
                },
                selection_only=True,
            )

        assert refused.value.status_code == 409
        assert "settlement_option_withdrawn_refetch" in str(refused.value)
        assert "does not declare returned" in str(refused.value)
        assert _negotiation_rows(world.app.db) == before
