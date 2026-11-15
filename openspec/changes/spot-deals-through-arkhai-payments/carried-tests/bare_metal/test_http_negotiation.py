"""A recurring selection negotiated through the bare-metal storefront app.

Carried from ``domains/bare_metal/storefront/tests/test_http_negotiation.py``;
restored there, these cases join that module. Each runs over
``recurring_world``, which stands fixtures at the recurring encoder and
term-timing ports.
"""

from __future__ import annotations

import sqlite3

import pytest
from storefront_client import StorefrontClientError

from recurring_world import (
    APPROVAL_WINDOW_SECONDS,
    DELIVERY_DEADLINE_SECONDS,
    MECHANISM as RECURRING_MECHANISM,
    PAYEE,
    PERIOD_SECONDS,
    recurring_world,
)


def _negotiation_rows(db) -> list[tuple]:
    with sqlite3.connect(db.db_path) as connection:
        return connection.execute(
            "SELECT * FROM negotiation_threads ORDER BY negotiation_id"
        ).fetchall()


async def test_a_cached_recurring_selection_whose_treatment_is_withdrawn_is_refused(
    tmp_path,
) -> None:
    """A buyer holding a recurring option published under the full declaration
    selects it after the storefront stops declaring one of its treatments: the
    seller answers the signed 409 asking for a refetch, and writes no negotiation."""
    async with recurring_world(tmp_path) as world:
        report = await world.publish()
        (listing_id,) = [
            item["listing_id"] for item in report["actions"] if item["action"] == "publish"
        ]
        options = (await world.admin.get_listing(listing_id)).extra["settlement_options"]
        on_demand = next(
            option for option in options
            if "period" in option["settlement"]
            and "payee" not in option["lifecycle"]["early_termination"]["entitlements"]
        )
        world.declare(frozenset({"charged"}))
        before = _negotiation_rows(world.db)

        with pytest.raises(StorefrontClientError) as refused:
            await world.buyer.negotiate_new(
                listing_id=listing_id,
                initial_amount=1,
                provision_terms={"kind": "bare_metal.v2", "version": 1, "payload": {
                    "duration_seconds": 3600,
                    "ssh_public_key": "ssh-ed25519 fixture",
                    "access_method": "ssh",
                }},
                settlement_selection={
                    "option_id": on_demand["option_id"],
                    "settlement": {"schema": RECURRING_MECHANISM, "payer_account": PAYEE},
                },
                selection_only=True,
            )

        assert refused.value.status_code == 409
        assert "settlement_option_withdrawn_refetch" in str(refused.value)
        assert "does not declare returned" in str(refused.value)
        assert _negotiation_rows(world.db) == before


#: The shortest recurring horizon the runway admits for a buyer naming no start:
#: the approval window, then the delivery deadline, then one whole period.
_MINIMUM_HORIZON = APPROVAL_WINDOW_SECONDS + DELIVERY_DEADLINE_SECONDS + PERIOD_SECONDS


async def test_a_horizon_leaving_no_runway_is_refused_naming_the_minimum_that_passes(
    tmp_path,
) -> None:
    """A recurring horizon must leave the delivery deadline and one period after
    the latest approval the option permits: 300 + 1200 + 900 seconds here. One
    second short is refused before any negotiation is written, naming that
    minimum so the buyer can re-propose it."""
    async with recurring_world(tmp_path) as world:
        report = await world.publish()
        (listing_id,) = [
            item["listing_id"] for item in report["actions"] if item["action"] == "publish"
        ]
        options = (await world.admin.get_listing(listing_id)).extra["settlement_options"]
        on_demand = next(
            option for option in options
            if "period" in option["settlement"]
            and "payee" not in option["lifecycle"]["early_termination"]["entitlements"]
        )
        before = _negotiation_rows(world.db)

        with pytest.raises(StorefrontClientError) as refused:
            await world.buyer.negotiate_new(
                listing_id=listing_id,
                # One period at the clause's 2.5 an hour, in base units.
                initial_amount=625_000,
                provision_terms={"kind": "bare_metal.v2", "version": 1, "payload": {
                    "duration_seconds": _MINIMUM_HORIZON - 1,
                    "ssh_public_key": "ssh-ed25519 fixture",
                    "access_method": "ssh",
                }},
                settlement_selection={
                    "option_id": on_demand["option_id"],
                    "expiration_unix": 2_147_483_647,
                    "settlement": {"schema": RECURRING_MECHANISM, "payer_account": PAYEE},
                },
                selection_only=True,
            )

        assert (
            f"The horizon leaves no runway: minimum duration_seconds is {_MINIMUM_HORIZON}"
            in str(refused.value)
        )
        assert _negotiation_rows(world.db) == before
