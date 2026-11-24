"""A restarted bare-metal storefront resumes its rate deals from its database and the authorities.

Application integration: the composed bare-metal storefront and its typed
clients over SQLite (``recurring_world``), its deal delivered through the real
delivery path, the payments service the in-process engine behind
``PaymentsClient``. The storefront is stopped and composed again over the same
database file while the payments service, which outlives it, keeps its
records; the restarted storefront's ``deal-servicing`` loop is stepped through
the typed admin client. Its site is a fresh fake, holding no reservation, so
these cases assert what the storefront records, not the site's teardown. The
restart cases for once-only Alkahest deals are ``tests/test_restart_recovery.py``.
"""

from __future__ import annotations

import json
import time

from market_arkhai_payments import PaymentSettlementData
from market_arkhai_payments.fixtures import FakePaymentsClient
from market_deal_servicing import EndSession
from market_deal_servicing.evidence import transaction

from integration.test_lifecycle_ends import recorded_end
from integration.test_rate_delivery import PAYER, approve
from recurring_world import MECHANISM, PAYMENTS_SERVICE, recurring_world

#: The spot preset's seller notice, which ``recurring_world`` publishes.
SPOT_NOTICE_SECONDS = 120
#: The recurring presets' period, in seconds.
PERIOD_SECONDS = 900


async def _delivered(tmp_path, payments, *, spot: bool) -> tuple[str, PaymentSettlementData]:
    """A recurring deal, on-demand or spot, negotiated, settled and delivered by a
    storefront that then stops."""
    async with recurring_world(tmp_path, payments=payments) as world:
        report = await world.publish()
        (listing_id,) = [item["listing_id"] for item in report["actions"] if item["action"] == "publish"]
        options = (await world.admin.get_listing(listing_id)).extra["settlement_options"]
        option = next(
            option for option in options
            if "period" in option["settlement"]
            and ("payee" in option["lifecycle"]["early_termination"]["entitlements"]) == spot
        )
        # One period of the preset's hourly rate, in base units.
        rate = 1.5 if spot else 2.5
        reply = await world.buyer.negotiate_new(
            listing_id=listing_id,
            initial_amount=int(rate * 10**6 * PERIOD_SECONDS / 3600),
            provision_terms={"kind": "bare_metal.v2", "version": 1, "payload": {
                "duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 fixture", "access_method": "ssh",
            }},
            settlement_selection={
                "option_id": option["option_id"],
                "settlement": {"schema": MECHANISM, "payer_account": PAYER},
            },
            selection_only=True,
        )
        assert reply["action"] == "accept", reply
        negotiation_id = reply["agreement"]["negotiation_id"]
        thread = await world.db.load_negotiation_thread_row(negotiation_id=negotiation_id)
        raw = thread["settlement_data"]
        data = PaymentSettlementData.parse(json.loads(raw) if isinstance(raw, str) else raw)
        approve(payments, data)
        await world.buyer.settle_agreement(negotiation_id)
        with transaction(world.db.db_path) as conn:
            assert EndSession(conn).read(negotiation_id).available_at is not None
    return negotiation_id, data


def _record(path, negotiation_id):
    with transaction(path) as conn:
        session = EndSession(conn)
        return session.read(negotiation_id), session.selected_end(negotiation_id)


async def test_a_running_rate_deal_stays_served_after_a_restart(tmp_path):
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    negotiation_id, data = await _delivered(tmp_path, payments, spot=False)

    payments.observed_at = int(time.time())
    async with recurring_world(tmp_path, payments=payments) as world:
        await world.admin.admin_pause_lifecycle_loops()
        serviced = await world.admin.admin_run_lifecycle_cycle("deal-servicing")
        redriven = await world.admin.admin_run_lifecycle_cycle("delivery-recovery")
        read = await world.buyer_lifecycle.read(negotiation_id)
        record, end = _record(world.db.db_path, negotiation_id)

    assert serviced["processed"] >= 1 and redriven["redriven"] == 0
    assert end is None and read.delivery.recorded_end is None
    assert read.delivery.progress == "active" and record.available_at is not None
    assert [part.final_stop for part in read.authority.parts] == [None]


async def test_an_ending_deal_ends_when_the_restarted_storefront_reads_its_stop(tmp_path):
    """The buyer stops at the payment authority while the storefront is down;
    the restarted storefront records nothing until its servicing cycle reads
    the stop, then records the buyer's entitled stop as the deal's end."""
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    negotiation_id, data = await _delivered(tmp_path, payments, spot=False)
    payments.observed_at = int(time.time())
    payments.engine.submit(data.transaction_id, {
        "account": PAYER, "requestId": "buyer-stop", "event": {"kind": "stop"},
    })

    async with recurring_world(tmp_path, payments=payments) as world:
        await world.admin.admin_pause_lifecycle_loops()
        before = (await world.buyer_lifecycle.read(negotiation_id)).delivery.recorded_end
        await world.admin.admin_run_lifecycle_cycle("deal-servicing")
        after = (await world.buyer_lifecycle.read(negotiation_id)).delivery.recorded_end
        stop, classification = recorded_end(world.db.db_path, negotiation_id)

    assert before is None
    assert after.cause == "payer" == stop.cause and classification.kind == "entitled_stop"


async def test_a_pending_seller_stop_takes_effect_at_its_instant_after_a_restart(tmp_path):
    """The seller stops a spot deal at the payment authority with its notice
    while the storefront is down. The restarted storefront's cycle before the
    stop's instant records no end; its cycle once the instant has passed records
    the seller's stop at that instant."""
    payments = FakePaymentsClient(signer=PAYMENTS_SERVICE)
    negotiation_id, data = await _delivered(tmp_path, payments, spot=True)
    requested = int(time.time())
    payments.observed_at = requested
    payments.engine.submit(data.transaction_id, {
        "account": data.mandate.to.root, "requestId": "seller-stop", "event": {"kind": "stop"},
    })
    instant = requested + SPOT_NOTICE_SECONDS

    now = [requested]
    async with recurring_world(tmp_path, payments=payments, clock=lambda: now[0]) as world:
        await world.admin.admin_pause_lifecycle_loops()
        await world.admin.admin_run_lifecycle_cycle("deal-servicing")
        _, pending = _record(world.db.db_path, negotiation_id)
        now[0] = payments.observed_at = instant + 1
        await world.admin.admin_run_lifecycle_cycle("deal-servicing")
        stop, classification = recorded_end(world.db.db_path, negotiation_id)

    assert pending is None
    assert stop.cause == "payee" and stop.ended_at == instant
    assert classification.kind == "entitled_stop"
