"""A recurring payments deal is settled but not delivered while rate servicing is not composed.

Application integration: the running bare-metal app, its typed clients and
SQLite persistence, with the installed recurring wiring under a declaration
listing ``charged`` and ``returned`` (``recurring_world``). The buyer negotiates
the published on-demand option, approves its mandate at the in-process payments
engine and settles through the typed client; the settle path starts delivery
through the real delivery path and end service.
"""

import json
import time

from market_arkhai_payments import PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_deal_lifecycle.delivery import DeliveryAuthorization
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction

from recurring_world import MECHANISM, PAYMENTS_SERVICE, recurring_world

#: Fixture payer account; never a real account.
PAYER = "11111111-1111-4111-8111-111111111111"


async def accepted_recurring_deal(world) -> tuple[str, PaymentSettlementData]:
    """Publish, then negotiate the on-demand option to acceptance through the buyer's typed client."""
    report = await world.publish()
    (listing_id,) = [item["listing_id"] for item in report["actions"] if item["action"] == "publish"]
    options = (await world.admin.get_listing(listing_id)).extra["settlement_options"]
    on_demand = next(
        option for option in options
        if "period" in option["settlement"]
        and "payee" not in option["lifecycle"]["early_termination"]["entitlements"]
    )
    reply = await world.buyer.negotiate_new(
        listing_id=listing_id,
        # One period at the clause's 2.5 an hour, in base units.
        initial_amount=625_000,
        provision_terms={"kind": "bare_metal.v2", "version": 1, "payload": {
            "duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 fixture", "access_method": "ssh",
        }},
        settlement_selection={
            "option_id": on_demand["option_id"],
            "settlement": {"schema": MECHANISM, "payer_account": PAYER},
        },
        selection_only=True,
    )
    assert reply["action"] == "accept"
    negotiation_id = reply["agreement"]["negotiation_id"]
    thread = await world.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    raw = thread["settlement_data"]
    return negotiation_id, PaymentSettlementData.parse(json.loads(raw) if isinstance(raw, str) else raw)


def approve(payments: FakePaymentsClient, data: PaymentSettlementData) -> None:
    """The buyer's approval of the mandate at the payments engine."""
    payments.observed_at = int(time.time())
    payments.engine.fund(PAYER, "USD/6", 10**9)
    payments.receipt = payments.engine.approve(data.mandate, account=PAYER)


async def test_a_settled_recurring_deal_is_not_delivered_while_rate_servicing_is_not_composed(tmp_path):
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    async with recurring_world(tmp_path, payments=payments) as world:
        negotiation_id, data = await accepted_recurring_deal(world)
        assert any(part.root.kind == "rate" for part in data.mandate.parts)
        approve(payments, data)

        settled = await world.buyer.settle_agreement(negotiation_id)

        # The settle answers the deal's deferred delivery: still planning, with
        # no reservation or fulfillment.
        assert settled.status == "planning"
        assert settled.extra["capacity_reservation_id"] is None
        assert settled.extra.get("fulfillment_id") is None

        with transaction(world.db.db_path) as conn:
            session = EndSession(conn)
            record = session.read(negotiation_id)
            intents = session.intents(negotiation_id)
            lifecycle = conn.execute(
                """SELECT state, capacity_reservation_id, fulfillment_id FROM bare_metal_fulfillment_lifecycle
                   WHERE negotiation_id=?""",
                (negotiation_id,),
            ).fetchone()
    # The receipt verified and the deal's servicing record exists, as a rate deal.
    assert record.commitment_ref == data.transaction_id and record.committed_at is not None
    assert record.available_at is None
    # End service refused the commit with its code, before any capacity,
    # fulfillment or billing.
    [authorization] = [intent for intent in intents if intent.kind == "authorization"]
    answer = DeliveryAuthorization.model_validate(authorization.result)
    assert answer.status == "refuse" and answer.code == "rate_servicing_unavailable"
    assert not [intent for intent in intents if intent.kind == "billing"]
    # The deal's delivery holds no reservation and began no fulfillment.
    assert lifecycle == ("planning", None, None)
    # The payments engine records no rate start: nothing was submitted.
    assert payments.count("submit_event") == 0
