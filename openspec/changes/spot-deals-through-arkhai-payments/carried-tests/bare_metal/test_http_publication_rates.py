"""Recurring publication through the bare-metal storefront app and its typed clients.

Carried from ``domains/bare_metal/storefront/tests/test_http_publication_rates.py``;
restored there, these cases join that module, whose helper ``_listing_id`` is
repeated here as it stood. Each runs over ``recurring_world``, which stands
fixtures at the recurring encoder and term-timing ports.
"""

from __future__ import annotations

import pytest

from recurring_world import (
    AVAILABLE_UNTIL,
    MAX_DURATION_SECONDS,
    MECHANISM,
    QUALIFIED,
    recurring_world,
    undeclared,
)

pytestmark = pytest.mark.asyncio


def _listing_id(report: dict) -> str:
    (published,) = [item for item in report["actions"] if item["action"] == "publish"]
    return str(published["listing_id"])


def _recurring(options: list[dict]) -> list[dict]:
    return [option for option in options if "period" in option["settlement"]]


def _derived_class(option: dict) -> str:
    """The class a buyer reads off an option: billed once is reserved; billed per
    period, a payee entitlement makes it spot and its absence on-demand."""
    if "period" not in option["settlement"]:
        return "reserved"
    entitlements = option["lifecycle"]["early_termination"]["entitlements"]
    return "spot" if "payee" in entitlements else "on-demand"


async def test_one_listing_offers_reserved_on_demand_and_spot_on_its_capacity_identity(tmp_path):
    """Declaring rate servicing adds the on-demand and spot options to the
    listing the pool already publishes, beside its reserved Alkahest and once
    payment options: the same listing and machine, publishing both bounds, each
    option separately identified, and the class each derives from its billing
    and entitlements, never a stored field."""
    async with recurring_world(tmp_path, treatments=None) as world:
        listing_id = _listing_id(await world.publish())
        dark = await world.admin.get_listing(listing_id)

        world.declare(QUALIFIED)
        report = await world.publish()
        listing = await world.admin.get_listing(listing_id)

    assert [_derived_class(option) for option in dark.extra["settlement_options"]] == ["reserved"] * 2
    assert [item for item in report["actions"] if item["action"] == "publish"] == []
    assert listing.status == "open"
    assert listing.listing_resource == dark.listing_resource
    assert (listing.max_duration_seconds, listing.extra["available_until_utc"]) == (
        MAX_DURATION_SECONDS, AVAILABLE_UNTIL,
    )
    options = listing.extra["settlement_options"]
    assert {option["option_id"] for option in dark.extra["settlement_options"]} < {
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


async def test_publication_omits_recurring_options_whose_treatments_are_undeclared(tmp_path):
    """A recurring option publishes only under a declaration qualifying every
    treatment it names. Narrowing the declaration omits both recurring options on
    the next step, each with its diagnostic, while the reserved and once options
    keep the listing's capacity identity."""
    async with recurring_world(tmp_path) as world:
        report = await world.publish()
        listing_id = _listing_id(report)
        published = (await world.admin.get_listing(listing_id)).extra["settlement_options"]
        recurring = _recurring(published)
        assert (len(published), len(recurring)) == (4, 2)
        assert not undeclared(report)
        peers = {option["option_id"] for option in published if option not in recurring}

        world.declare(frozenset({"charged"}))
        report = await world.publish()
        listing = await world.admin.get_listing(listing_id)

    assert listing.status == "open"
    assert [item for item in report["actions"] if item["action"] == "publish"] == []
    assert {option["option_id"] for option in listing.extra["settlement_options"]} == peers
    refusals = undeclared(report)
    assert len(refusals) == 2
    assert all("does not declare returned" in item["detail"] for item in refusals)


@pytest.mark.parametrize(("clause_deadline", "refused"), [(900, 0), (None, 3)],
                         ids=["clause-configured", "neither"])
async def test_a_clause_s_deadline_publishes_where_the_pool_supplies_none(
    tmp_path, clause_deadline, refused,
):
    """With no pool deadline, each payment option, once or recurring, publishes the
    deadline its clause configures and no default buyer's refusal is reported; a
    clause configuring none publishes no deadline, and each payment option is
    reported as refused by a default buyer for lacking one."""
    async with recurring_world(tmp_path, pool_deadline=None, clause_deadline=clause_deadline) as world:
        report = await world.publish()
        published = (await world.admin.get_listing(_listing_id(report))).extra["settlement_options"]

    payments = [option for option in published if option["settlement"]["schema"] == MECHANISM]
    assert len(payments) == 3
    assert {option["lifecycle"].get("delivery_deadline_seconds") for option in payments} == {clause_deadline}
    refusals = [item for item in report["actions"] if item.get("reason") == "default_buyer_refusal"]
    assert len(refusals) == refused
    assert all(item["detail"].endswith("no delivery deadline") for item in refusals)


async def test_an_on_demand_option_stating_no_penalty_publishes_the_configured_multiple(tmp_path):
    """The on-demand preset states no premature-stop penalty, so it publishes its
    per-period price, 625000 at 2.5 an hour per 15 minutes, times the composition's
    configured multiple; spot, which carries a seller stop, publishes none."""
    async with recurring_world(tmp_path, default_penalty_periods=6) as world:
        listing_id = _listing_id(await world.publish())
        published = (await world.admin.get_listing(listing_id)).extra["settlement_options"]

    penalties = {
        "payee" in option["lifecycle"]["early_termination"]["entitlements"]:
            option["lifecycle"]["early_termination"].get("premature_stop_penalty")
        for option in _recurring(published)
    }
    assert penalties == {False: str(625000 * 6), True: None}
