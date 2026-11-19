"""A recurring payments deal is delivered, and an undelivered one meets its deadline.

Application integration: the served VM storefront, its typed clients and SQLite
persistence, with the installed recurring wiring under a declaration listing
``charged`` and ``returned`` (``tests.recurring_world``). The buyer negotiates
the published on-demand option, approves its mandate at the in-process
payments engine and settles through the typed client; delivery runs through the
real delivery path and end service, with the site and provisioning service
replaced at the clients the storefront wraps them in. A deal is left
undelivered by an unreachable site, so its commit is allowed and nothing is
placed.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from datetime import datetime

from arkhai_vms import make_vm_provision_terms
from market_arkhai_payments import PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_deal_lifecycle.delivery import DeliveryAuthorization
from market_deal_lifecycle_contracts.models import LifecycleRead
from market_deal_servicing import DeliveryRecord, EndSession
from market_deal_servicing.evidence import transaction

from tests.recurring_world import MECHANISM, PAYMENTS_SERVICE, recurring_world, settlement

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


def _instant(value: str) -> int:
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


async def test_a_settled_recurring_deal_is_activated_then_billed_and_made_available(tmp_path):
    async with recurring_world(tmp_path) as world, settlement(world) as settled:
        negotiation_id, data = await accepted_recurring_deal(world)
        assert any(part.root.kind == "rate" for part in data.mandate.parts)
        approve(settled, data)

        await world.app.buyer.settle_agreement(negotiation_id)
        await settled.delivered(negotiation_id)

        with transaction(world.app.db.db_path) as conn:
            session = EndSession(conn)
            record = session.read(negotiation_id)
            intents = session.intents(negotiation_id)
        with sqlite3.connect(world.app.db.db_path) as conn:
            row = conn.execute(
                """SELECT status, capacity_reservation_id, activated_at_utc FROM vm_delivery_records
                   WHERE negotiation_id=?""", (negotiation_id,),
            ).fetchone()
        snapshot = settled.payments.engine.snapshot(data.transaction_id).snapshot

    # Committed, placed and activated at the site, and available.
    status, reservation, recorded_activation = row
    assert status == "ready" and record.available_at is not None
    assert settled.site.rows[reservation]["state"] == "leased"
    activated_at = _instant(settled.site.rows[reservation]["activated_at_utc"])
    assert recorded_activation == activated_at
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
    assert settled.payments.count("submit_event") == 1
    assert [part.started is not None for part in snapshot.parts] == [True]
    assert record.available_at >= activated_at


async def settled_undelivered_deal(tmp_path, payments) -> tuple[str, PaymentSettlementData, DeliveryRecord]:
    """A recurring deal settled while its site is unreachable, by a storefront
    that then stops: its commit is allowed and nothing is placed."""
    async with recurring_world(tmp_path) as world, settlement(world, payments=payments) as settled:
        negotiation_id, data = await accepted_recurring_deal(world)
        approve(settled, data)
        settled.site.unreachable = True
        await world.app.buyer.settle_agreement(negotiation_id)
        await settled.delivered(negotiation_id)
        with transaction(world.app.db.db_path) as conn:
            session = EndSession(conn)
            record = session.read(negotiation_id)
            intents = session.intents(negotiation_id)
        assert settled.site.rows == {} and record.available_at is None
        assert [DeliveryAuthorization.model_validate(intent.result).status for intent in intents
                if intent.kind == "authorization"] == ["allow"]
        assert not [intent for intent in intents if intent.kind == "billing"]
    return negotiation_id, data, record


async def recovered(tmp_path, payments, negotiation_id, *, at: int) -> LifecycleRead:
    """Restart the storefront over the same database at ``at``, run its recovery
    cycle, and return the buyer's lifecycle read of the deal.

    The read is made of the storefront opened again at wall time: lifecycle
    requests and answers are signed at each side's clock and refused when the
    two differ by more than their allowed skew, as a clock moved past the
    deadline does.
    """
    payments.observed_at = at
    async with recurring_world(tmp_path) as world, settlement(world, payments=payments, clock=lambda: at):
        await world.app.client.admin_run_lifecycle_cycle("deal-servicing")
    async with recurring_world(tmp_path) as world, settlement(world, payments=payments) as settled:
        return await settled.buyer_lifecycle.read(negotiation_id)


async def test_a_buyer_stop_while_the_storefront_is_down_wins_over_the_deadline_at_recovery(tmp_path):
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    negotiation_id, data, record = await settled_undelivered_deal(tmp_path, payments)

    # With the storefront stopped, the buyer stops at the payment authority
    # before the delivery deadline; no hint reaches the storefront.
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
    async with recurring_world(tmp_path) as world, settlement(
        world, payments=payments, clock=lambda: record.deadline + 60,
    ):
        await world.app.client.admin_run_lifecycle_cycle("deal-servicing")
        # The cycle asked the authority for the deal, and the read failed.
        assert payments.count("get_transaction") > reads
        with transaction(world.app.db.db_path) as conn:
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
