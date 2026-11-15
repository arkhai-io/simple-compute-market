"""A recurring payments deal is settled but not delivered while rate servicing is not composed.

Application integration: the served VM storefront, its typed clients and SQLite
persistence, with the installed recurring wiring under a declaration listing
``charged`` and ``returned`` (``tests.recurring_world``). The buyer negotiates
the published on-demand option, approves its mandate at the in-process
payments engine and settles through the typed client; delivery runs through the
real delivery path and end service, with the site and provisioning service
replaced at the clients the storefront wraps them in.
"""

from __future__ import annotations

import json
import sqlite3
import time
from copy import deepcopy
from dataclasses import asdict

from arkhai_vms import make_vm_provision_terms
from market_arkhai_payments import PaymentSettlementData
from market_deal_lifecycle.delivery import DeliveryAuthorization
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction

from tests.recurring_world import MECHANISM, recurring_world, settlement

#: Fixture payer account; never a real account.
PAYER = "11111111-1111-4111-8111-111111111111"


async def _published(world) -> dict:
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


async def accepted_recurring_deal(world) -> tuple[str, PaymentSettlementData]:
    """Negotiate the world's on-demand option to acceptance through the buyer's typed client."""
    listing = await _published(world)
    option = _on_demand(listing)
    reply = await world.app.buyer.negotiate_new(
        listing_id=listing["listing_id"],
        # One period at the clause's 2.5 an hour, in base units.
        initial_amount=625_000,
        provision_terms=make_vm_provision_terms(
            duration_seconds=3600, ssh_public_key="ssh-ed25519 test",
        ).model_dump(mode="json"),
        settlement_selection={
            "option_id": option["option_id"], "expiration_unix": 2_147_483_647,
            "settlement": {"schema": MECHANISM, "payer_account": PAYER},
        },
        selection_only=True,
    )
    assert reply["action"] == "accept"
    negotiation_id = reply["agreement"]["negotiation_id"]
    thread = await world.app.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    raw = thread["settlement_data"]
    return negotiation_id, PaymentSettlementData.parse(json.loads(raw) if isinstance(raw, str) else raw)


def approve(settled, data: PaymentSettlementData) -> None:
    """The buyer's approval of the mandate at the payments engine."""
    settled.payments.observed_at = int(time.time())
    settled.payments.engine.fund(PAYER, "USD/6", 10**9)
    settled.payments.receipt = settled.payments.engine.approve(data.mandate, account=PAYER)


async def test_a_settled_recurring_deal_is_not_delivered_while_rate_servicing_is_not_composed(tmp_path):
    async with recurring_world(tmp_path) as world, settlement(world) as settled:
        negotiation_id, data = await accepted_recurring_deal(world)
        assert any(part.root.kind == "rate" for part in data.mandate.parts)
        approve(settled, data)
        held = deepcopy(world.app.site.reservations)

        await world.app.buyer.settle_agreement(negotiation_id)
        await settled.delivered(negotiation_id)

        # The receipt verified and the deal's servicing record exists, as a
        # rate deal.
        with transaction(world.app.db.db_path) as conn:
            session = EndSession(conn)
            record = session.read(negotiation_id)
            intents = session.intents(negotiation_id)
        assert record.commitment_ref == data.transaction_id and record.committed_at is not None
        assert record.available_at is None
        # End service refused the commit with its code, before any capacity,
        # fulfillment or billing.
        [authorization] = [intent for intent in intents if intent.kind == "authorization"]
        answer = DeliveryAuthorization.model_validate(authorization.result)
        assert answer.status == "refuse" and answer.code == "rate_servicing_unavailable"
        assert not [intent for intent in intents if intent.kind == "billing"]
        assert world.app.site.reservations == held
        assert all(row.get("state") != "leased" for row in world.app.site.reservations.values())
        assert settled.provisioning.scheduled == [] and settled.provisioning.begins == []
        # The payments engine records no rate start: nothing was submitted.
        assert settled.payments.count("submit_event") == 0
        # The deal's delivery is deferred, holding no reservation or fulfillment.
        with sqlite3.connect(world.app.db.db_path) as conn:
            row = conn.execute(
                """SELECT status, capacity_reservation_id, fulfillment_id FROM vm_delivery_records
                   WHERE negotiation_id=?""", (negotiation_id,),
            ).fetchone()
        assert row == ("provisioning", None, None)
