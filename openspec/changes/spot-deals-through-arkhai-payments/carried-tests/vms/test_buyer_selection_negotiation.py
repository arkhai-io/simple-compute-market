"""A buyer's recurring selection negotiated through the served VM storefront.

Carried from
``domains/vms/storefront/tests/integration/test_buyer_selection_negotiation.py``;
restored there, these cases join that module, whose helpers ``_as_published`` and
``_registry_listing`` are repeated here as they stood. Each runs over
``recurring_world``, which stands fixtures at the recurring encoder, term-timing
and billing-projection ports.

A buyer that names no horizon on a recurring option leaves it to the seller to
resolve; the buyer's own checks on the signed acceptance must then admit what the
served storefront signed. A horizon the buyer names must leave room to deliver
after the latest approval, and a refusal names the shortest one that does.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from dataclasses import asdict

import pytest

from arkhai_vms_buyer.pricing_record import (
    retained_pricing_record,
    verify_pricing_acceptance,
)
from market_core.schemas import Agreement
from market_identity import RequestEnvelope, TrustedIdentitySet, canonical_body_hash, sign_request
from market_settlement_runtime.horizon import check_accepted_horizon
from storefront_client import StorefrontClientError

from tests.fake_site import TEST_MARKETPLACE_SIGNER
from tests.recurring_world import (
    APPROVAL_WINDOW_SECONDS,
    DELIVERY_DEADLINE_SECONDS,
    MAX_DURATION_SECONDS,
    MECHANISM,
    PAYEE,
    PERIOD,
    PERIOD_SECONDS,
    SHAPE_PRICING,
    billing,
    payment_clause,
    recurring_world,
)


def _as_published(world, listing: dict) -> dict:
    """The storefront's listing beside its signed publication and trust, as a
    registry returns them. A storefront's local listing alone cannot prove a
    published rate."""
    return {**listing, **_registry_listing(world, listing["listing_id"])}


def _registry_listing(world, listing_id: str) -> dict:
    """The body the storefront published, with nothing of its local listing,
    beside the seller-signed publication proof and publisher trust a registry
    keeps for it. The proof is signed here with the seller's key, standing for
    the registry's retained copy of the storefront's signed request."""
    publication = world.registries.to("publish", listing_id)[0][1]
    request = sign_request(signer=TEST_MARKETPLACE_SIGNER, envelope=RequestEnvelope(
        principal=TEST_MARKETPLACE_SIGNER.identity, role="seller", method="POST",
        operation="listing.publish", resource="listings",
        request_id="buyer-selection-publication", timestamp=1_793_966_340,
        body_hash=canonical_body_hash(publication),
    ))
    return {
        **publication,
        "publisher_principals": TrustedIdentitySet(
            identities=(TEST_MARKETPLACE_SIGNER.identity,)
        ).model_dump(mode="json"),
        "publisher_publication": {
            "body_base64": base64.b64encode(json.dumps(publication).encode()).decode(),
            "request": request.model_dump(mode="json"),
        },
    }


# A buyer naming no horizon on a recurring option. The production buyer client
# cannot open such a negotiation: it sizes its bounds through the installed
# payments projection, which refuses rate parameters. These cases therefore open
# through the storefront's typed client and run the buyer's own acceptance checks
# on the signed reply.

#: The buyer's provision terms, naming no duration.
_NO_HORIZON = {"kind": "compute.v1", "version": 1, "payload": {"ssh_public_key": ""}}


async def _published(world) -> dict:
    """The world's one listing after a publication cycle, as one mapping."""
    await world.publish()
    (summary,) = (await world.app.client.list_listings(status="open")).listings
    listing = await world.app.client.get_listing(summary.listing_id)
    return {**listing.extra, **{key: value for key, value in asdict(listing).items() if key != "extra"}}


def _on_demand(listing: dict) -> dict:
    return next(
        option for option in listing["settlement_options"]
        if "period" in option["settlement"]
        and "payee" not in option["lifecycle"]["early_termination"]["entitlements"]
    )


def _recurring_selection(option: dict) -> dict:
    return {
        "option_id": option["option_id"],
        "expiration_unix": 2_147_483_647,
        "settlement": {"schema": MECHANISM, "payer_account": PAYEE},
    }


async def test_an_omitted_horizon_is_accepted_at_the_default_bound_the_buyer_checks(
    tmp_path,
) -> None:
    """The served storefront resolves an omitted horizon to the listing's default
    bound and signs it; the buyer's accepted-horizon check admits that signed
    default against the bounds the served listing advertises."""
    async with recurring_world(tmp_path) as world:
        listing = await _published(world)
        option = _on_demand(listing)
        reply = await world.app.buyer.negotiate_new(
            listing_id=listing["listing_id"],
            # One period at the clause's 2.5 an hour, in base units.
            initial_amount=625_000,
            provision_terms=_NO_HORIZON,
            settlement_selection=_recurring_selection(option),
            selection_only=True,
        )

    assert reply["action"] == "accept"
    agreement = reply["agreement"]
    assert listing["max_duration_seconds"] == MAX_DURATION_SECONDS
    assert agreement["duration_seconds"] == MAX_DURATION_SECONDS
    assert "duration_seconds" not in agreement["provision_terms"]["payload"]
    assert agreement["settlement"] == option
    check_accepted_horizon(
        start_utc=agreement["start_utc"],
        duration_seconds=agreement["duration_seconds"],
        requested_duration_seconds=None,
        max_duration_seconds=listing["max_duration_seconds"],
        available_until_utc=listing["available_until_utc"],
    )


async def test_a_buyer_that_named_no_duration_verifies_the_accepted_pricing(tmp_path) -> None:
    """At the pricing pin: a shape-priced recurring acceptance whose buyer named
    no duration passes the buyer's pricing verification against the Agreement's
    resolved duration, since the provision terms it signed carry none to compare."""
    on_demand = payment_clause(None, recurring={"period": PERIOD, "reserve_ahead_seconds": 1800})
    async with recurring_world(tmp_path, pricing=SHAPE_PRICING, published=[on_demand]) as world:
        listing = _as_published(world.app, await _published(world))
        (option,) = listing["settlement_options"]
        reply = await world.app.buyer.negotiate_new(
            listing_id=listing["listing_id"],
            # The listed rates exactly, as basis points of them.
            initial_amount=10_000,
            provision_terms=_NO_HORIZON,
            settlement_selection=_recurring_selection(option),
            selection_only=True,
        )

    assert listing.get("rate_structure")
    assert reply["action"] == "accept"
    agreement = Agreement.model_validate(reply["agreement"])
    assert agreement.duration_seconds == MAX_DURATION_SECONDS
    verify_pricing_acceptance(
        retained_pricing_record(listing), agreement, reply,
        multiplier=10_000, project_billing=billing,
    )


# A horizon the buyer names on a recurring option, which the served storefront
# holds to the runway at acceptance.

#: The shortest recurring horizon the runway admits for a buyer naming no start:
#: the approval window, then the delivery deadline, then one whole period.
_MINIMUM_HORIZON = APPROVAL_WINDOW_SECONDS + DELIVERY_DEADLINE_SECONDS + PERIOD_SECONDS


def _negotiation_rows(db) -> list[tuple]:
    with sqlite3.connect(db.db_path) as connection:
        return connection.execute(
            "SELECT * FROM negotiation_threads ORDER BY negotiation_id"
        ).fetchall()


def _horizon(duration_seconds: int) -> dict:
    return {**_NO_HORIZON, "payload": {**_NO_HORIZON["payload"], "duration_seconds": duration_seconds}}


async def test_a_horizon_leaving_no_runway_is_refused_naming_the_minimum_that_passes(
    tmp_path,
) -> None:
    """A recurring horizon must leave the delivery deadline and one period after
    the latest approval the option permits: 300 + 1200 + 900 seconds here. One
    second short is refused before any negotiation is written, naming the minimum, and
    the buyer re-proposing that minimum is accepted at it."""
    async with recurring_world(tmp_path) as world:
        listing = await _published(world)
        option = _on_demand(listing)
        before = _negotiation_rows(world.app.db)

        async def propose(duration_seconds: int) -> dict:
            return await world.app.buyer.negotiate_new(
                listing_id=listing["listing_id"],
                initial_amount=625_000,
                provision_terms=_horizon(duration_seconds),
                settlement_selection=_recurring_selection(option),
                selection_only=True,
            )

        with pytest.raises(StorefrontClientError) as refused:
            await propose(_MINIMUM_HORIZON - 1)
        refused_rows = _negotiation_rows(world.app.db)
        reply = await propose(_MINIMUM_HORIZON)

    assert (
        f"The horizon leaves no runway: minimum duration_seconds is {_MINIMUM_HORIZON}"
        in str(refused.value)
    )
    assert refused_rows == before
    assert reply["action"] == "accept"
    assert reply["agreement"]["duration_seconds"] == _MINIMUM_HORIZON
