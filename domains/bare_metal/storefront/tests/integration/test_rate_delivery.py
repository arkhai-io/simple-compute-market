"""A recurring payments deal is delivered, and an undelivered one meets its deadline.

Application integration: the running bare-metal app, its typed clients and
SQLite persistence, with the installed recurring wiring under a declaration
listing ``charged`` and ``returned`` (``recurring_world``). The buyer negotiates
the published on-demand option, approves its mandate at the in-process payments
engine and settles through the typed client; the settle path starts delivery
through the real delivery path and end service, with the site and provisioning
service replaced at the clients the storefront wraps them in. A deal is left
undelivered by an unreachable site, so its commit is allowed and nothing is
placed.
"""

import json
import time
from datetime import datetime

from market_arkhai_payments import PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_deal_lifecycle.delivery import DeliveryAuthorization
from market_deal_lifecycle_contracts.models import LifecycleRead
from market_deal_servicing import DeliveryRecord, EndSession
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


async def test_a_settled_recurring_deal_is_activated_then_billed_and_made_available(tmp_path):
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    async with recurring_world(tmp_path, payments=payments) as world:
        negotiation_id, data = await accepted_recurring_deal(world)
        assert any(part.root.kind == "rate" for part in data.mandate.parts)
        approve(payments, data)

        await world.buyer.settle_agreement(negotiation_id)

        with transaction(world.db.db_path) as conn:
            session = EndSession(conn)
            record = session.read(negotiation_id)
            intents = session.intents(negotiation_id)
            lifecycle = conn.execute(
                """SELECT state, capacity_reservation_id, activated_at_utc FROM bare_metal_fulfillment_lifecycle
                   WHERE negotiation_id=?""",
                (negotiation_id,),
            ).fetchone()
        capacity, provisioning = world.capacity, world.provisioning
    snapshot = payments.engine.snapshot(data.transaction_id).snapshot

    # Committed, placed and activated at the site, its fulfillment begun, and
    # available. The row keeps the fulfillment state recorded at dispatch until
    # a status read refreshes it from provisioning.
    _, reservation, recorded_activation = lifecycle
    assert reservation == "reservation-a"
    assert len(capacity.commit_calls) >= 1 and len(provisioning.begin_calls) == 1
    activated_at = int(datetime.fromisoformat(capacity.activated_at).timestamp())
    assert recorded_activation == activated_at
    assert record.available_at is not None and record.available_at >= activated_at
    # The commit was allowed by the payment authority, not refused.
    commit = next(
        DeliveryAuthorization.model_validate(intent.result) for intent in intents
        if intent.kind == "authorization" and intent.payload["phase"] == "commit"
    )
    assert commit.status == "allow"
    # Billing started once, from the site's activation: the journaled billing
    # start names that activation, and the payments engine holds the started rate.
    [billing] = [intent for intent in intents if intent.kind == "billing"]
    assert billing.state == "done"
    activated = billing.payload["activated_delivery"]
    assert (activated["record_ref"], activated["activated_at"]) == (reservation, activated_at)
    assert payments.count("submit_event") == 1
    assert [part.started is not None for part in snapshot.parts] == [True]


async def settled_undelivered_deal(tmp_path, payments) -> tuple[str, PaymentSettlementData, DeliveryRecord]:
    """A recurring deal settled while its site is unreachable, by an app that
    then stops: its commit is allowed and nothing is placed."""
    async with recurring_world(tmp_path, payments=payments) as world:
        negotiation_id, data = await accepted_recurring_deal(world)
        approve(payments, data)
        world.capacity.unreachable = True
        await world.buyer.settle_agreement(negotiation_id)
        with transaction(world.db.db_path) as conn:
            session = EndSession(conn)
            record = session.read(negotiation_id)
            intents = session.intents(negotiation_id)
        assert world.capacity.reservation_sites == {} and world.capacity.commit_calls == []
        assert world.provisioning.begin_calls == [] and record.available_at is None
        assert [DeliveryAuthorization.model_validate(intent.result).status for intent in intents
                if intent.kind == "authorization"] == ["allow"]
        assert not [intent for intent in intents if intent.kind == "billing"]
    return negotiation_id, data, record


async def recovered(tmp_path, payments, negotiation_id, *, at: int) -> LifecycleRead:
    """Restart the app over the same database at ``at``, run its delivery
    recovery, and return the buyer's lifecycle read of the deal.

    The read is made of the app opened again at wall time: lifecycle requests
    and answers are signed at each side's clock and refused when the two
    differ by more than their allowed skew, as a clock moved past the deadline
    does.
    """
    payments.observed_at = at
    async with recurring_world(tmp_path, payments=payments, clock=lambda: at) as world:
        await world.admin.admin_run_lifecycle_cycle("deal-servicing")
    async with recurring_world(tmp_path, payments=payments) as world:
        return await world.buyer_lifecycle.read(negotiation_id)


async def test_a_buyer_stop_while_the_storefront_is_down_wins_over_the_deadline_at_recovery(tmp_path):
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    negotiation_id, data, record = await settled_undelivered_deal(tmp_path, payments)

    # With the app stopped, the buyer stops at the payment authority before
    # the delivery deadline; no hint reaches the storefront.
    stopped_at = record.committed_at + 60
    assert stopped_at < record.deadline
    payments.observed_at = stopped_at
    payments.engine.submit(data.transaction_id, {
        "account": PAYER, "requestId": "buyer-stop", "event": {"kind": "stop"},
    })

    read = await recovered(tmp_path, payments, negotiation_id, at=record.deadline + 60)

    # The payer's end, recorded from the authority at recovery, is the deal's,
    # and no seller non-delivery is recorded or filed.
    assert read.delivery.recorded_end is not None
    assert (read.delivery.recorded_end.cause, read.delivery.recorded_end.ended_at) == ("payer", stopped_at)
    assert read.filings == []


async def test_recovery_after_the_deadline_records_seller_non_delivery_for_an_undelivered_rate_deal(tmp_path):
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    negotiation_id, _, record = await settled_undelivered_deal(tmp_path, payments)

    read = await recovered(tmp_path, payments, negotiation_id, at=record.deadline + 60)

    # The buyer never stopped: recovery reads the authority first, so its one
    # cycle records the deadline as seller non-delivery and journals the filing.
    assert read.delivery.recorded_end is not None
    assert (read.delivery.recorded_end.cause, read.delivery.recorded_end.ended_at) == (
        "non_delivery", record.deadline,
    )
    assert len(read.filings) == 1


async def test_an_unreadable_authority_at_the_deadline_records_nothing_until_a_later_read(tmp_path):
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    negotiation_id, _, record = await settled_undelivered_deal(tmp_path, payments)

    # The payments service cannot be read at recovery past the deadline: the
    # deadline awaits an observation of the authority, so nothing is recorded
    # and no filing is journaled.
    payments.unavailable = True
    payments.observed_at = record.deadline + 60
    reads = payments.count("get_transaction")
    async with recurring_world(tmp_path, payments=payments, clock=lambda: record.deadline + 60) as world:
        await world.admin.admin_run_lifecycle_cycle("deal-servicing")
        # The cycle asked the authority for the deal, and the read failed.
        assert payments.count("get_transaction") > reads
        with transaction(world.db.db_path) as conn:
            session = EndSession(conn)
            requests = session.requests(negotiation_id)
            filings = [intent for intent in session.intents(negotiation_id) if intent.kind == "filing"]
    assert requests == [] and filings == []

    # Once the authority is read again, the next recovery admits the deadline.
    payments.unavailable = False
    read = await recovered(tmp_path, payments, negotiation_id, at=record.deadline + 120)

    assert read.delivery.recorded_end is not None
    assert (read.delivery.recorded_end.cause, read.delivery.recorded_end.ended_at) == (
        "non_delivery", record.deadline,
    )
    assert len(read.filings) == 1
