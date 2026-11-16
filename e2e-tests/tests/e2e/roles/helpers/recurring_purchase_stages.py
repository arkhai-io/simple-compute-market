"""Stages of a recurring purchase through the shipped buyer, defined once.

A recurring purchase buys a seller's recurring on-demand option in
``arkhai.payments.v1`` through the domain's own buyer CLI (``market buy``,
``market bare-metal buy``) with a default buyer, against a lane whose storefront
declares rate servicing for ``charged`` and ``returned``. That declaration is a
lane fixture, never a shipped default. End service asks the payments adapter
whether to deliver the committed deal, so the deal is delivered: the site
activates it, then the storefront starts the rate part at the payments double,
then the deal is available. The buyer ends the deal by its own ``end``, the
payer's stop at the payments double and a hint to the storefront; the stop
charges the started period, and the storefront records the payer's end and
tears the delivery down. The result is lane-double evidence of the money a buyer
is shown and approves for a per-period Agreement, of rate delivery and of the
buyer's end.

A recurring purchase module declares, in order, each by subclassing it with an
empty body:

- the canonical deal's readiness stages a buyer purchase shares (``Stage00`` to
  ``Stage00c2``, a mock lane's ``Stage00e``, ``Stage00f1``, which seeds the
  supply through the driver, and ``Stage00h``), then its own listing stage,
  which writes ``seller_listing_id`` and ``listing_published``;
- ``Purchase01`` to ``Purchase04`` of ``buyer_purchase_stages.py``, arming the
  create gate (``Stage07a``) before the buy and releasing and draining it
  (``Stage08b2``) after the correlation, then ``Recurring04``'s mandate;
- the canonical deal's delivery, ``Stage09a`` to ``Stage09c``, with its own
  stage closing the listing (``Stage09a2``) before ``Stage09b``, then
  ``Recurring05``'s rate start, ``Purchase09``'s end of the purchase command,
  and ``Recurring06``'s accepted money;
- the buyer's end: ``Stage09c2`` arming the teardown gate, ``Recurring07``,
  ``Stage11a2`` and ``Stage11b``'s teardown, then ``Recurring08``'s balance.

``tests/unit/test_recurring_purchase_stages.py`` holds every recurring purchase
module to that order.

What differs between domains reaches a stage through the ``deal_driver``
fixture, a ``RecurringPurchaseDriver``: the buyer purchase's driver, the
storefront loop that services the domain's deals, and the storefront's
lifecycle read as the purchase's buyer.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Protocol

from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM, verify_receipt, verify_snapshot
from market_core.schemas import SettlementOption, compute_rate_total
from market_deal_lifecycle_buyer import EndDeliveryProgress
from market_deal_lifecycle_contracts.models import Accepted, LifecycleRead

from tests.e2e.roles.helpers.buyer_purchase_stages import (
    PurchaseDriver,
    PurchaseState,
    available_balances,
)
from tests.e2e.roles.helpers.cleanup import CleanupStep
from tests.e2e.roles.helpers.compute_deal import advance_storefront, assert_lease_watchdog_held
from tests.e2e.roles.helpers.compute_deal_stages import utc_instant
from tests.e2e.roles.helpers.domain_deal import assert_market_run_succeeded, require_state
from tests.e2e.roles.helpers.payments import (
    buyer_payments_client,
    dispute_window_seconds,
    payment_setting,
)

log = logging.getLogger(__name__)

#: The recurring option's period, and the reserve ahead it states: one period,
#: so approval reserves exactly one period's price.
PERIOD = "PT15M"
PERIOD_SECONDS = 900
RESERVE_AHEAD_SECONDS = 900
#: The option's approval expiry. Approval window, delivery deadline and one
#: period must fit within the listing's maximum duration, or publication
#: refuses the option for leaving no runway.
APPROVAL_WINDOW = "PT5M"
#: The seller's asking rate, USD 1.00 an hour.
HOURLY_RATE = "1.00"
#: One period's price at that rate, in USD/6 base units.
PERIOD_GROSS = 250_000
ASSET = "USD/6"
#: The title of the accepted Agreement's disclosure the shipped buyers print on
#: stderr, which they share.
DISCLOSURE_TITLE = "Accepted Agreement: price, horizon and lifecycle terms before approval"


def recurring_settlement(*, seller_account: str, delivery_deadline_seconds: int) -> dict[str, Any]:
    """The payments publication clause of a recurring on-demand option.

    USD 1.00 an hour paid to ``seller_account`` per ``PERIOD``, with no setup
    charge and no payee notice, so the shipped on-demand preset: the payer's
    stop charges its started period, and the term end returns the last one.
    The run's dispute coverage covers ``delivery_deadline_seconds``.
    """
    return {
        "mechanism": ARKHAI_PAYMENTS_MECHANISM, "asset": ASSET, "rate": HOURLY_RATE, "per": "hour",
        "recurring": {"period": PERIOD, "reserve_ahead_seconds": RESERVE_AHEAD_SECONDS},
        "mechanism_input": {
            "payee_account": seller_account, "asset": ASSET,
            "approval_window": APPROVAL_WINDOW,
            "delivery_deadline_seconds": delivery_deadline_seconds,
            "dispute_window_seconds": dispute_window_seconds(
                delivery_deadline_seconds=delivery_deadline_seconds,
            ),
        },
    }


def check_recurring_option(option: SettlementOption, *, delivery_deadline_seconds: int) -> None:
    """What the seller published for ``recurring_settlement``: one period's
    price per ``PERIOD``, the on-demand entitlements a default buyer accepts,
    and the pool's delivery deadline."""
    params = option.settlement_params
    assert (params.get("period"), params.get("reserve_ahead_seconds")) == (
        PERIOD, RESERVE_AHEAD_SECONDS,
    ), option
    assert params.get("approval_window") == APPROVAL_WINDOW, option
    assert "setup_amount" not in params, option
    assert option.price_asset == ASSET, option
    assert compute_rate_total(option.price_rates[0], PERIOD_SECONDS) == PERIOD_GROSS, option
    early = option.lifecycle["early_termination"]
    assert early["entitlements"] == {
        "payer": {"notice_seconds": 0, "settles_through": "started_period"},
    }, early
    assert early["settles_through"] == "last_boundary", early
    # A default buyer refuses an on-demand option without a positive penalty.
    assert int(early["premature_stop_penalty"]) > 0, early
    assert option.lifecycle["delivery_deadline_seconds"] == delivery_deadline_seconds, option


@dataclass
class RecurringPurchaseState(PurchaseState):
    """What a recurring purchase's stages hand each other, beside the purchase's.

    ``Purchase04``'s correlation writes the purchase's ``negotiation_id``,
    ``settlement_id``, ``agreement`` and ``payment_settlement``, which
    ``Recurring04`` checks, and ``Recurring07`` writes
    ``_buyer_teardown_requested`` before the buyer's end and
    ``teardown_fulfillment_id`` once the teardown is dispatched.
    """

    #: The payments double's receipt gross for the transaction: what approval
    #: reserved from the payer.
    receipt_gross: Optional[int] = None
    #: The payments double started the rate part no earlier than the whole
    #: second of the site's activation, and the storefront reads the deal active.
    _rate_started: bool = False
    #: The ended purchase command's stderr showed the accepted money.
    _accepted_money_shown: bool = False
    #: What the buyer's ``end`` printed once its payer's stop was accepted.
    buyer_end: Optional[dict[str, Any]] = None


class RecurringPurchaseDriver(PurchaseDriver, Protocol):
    """What a domain supplies to a recurring purchase, beside a purchase's part."""

    #: The storefront loop whose cycle services the domain's committed deals:
    #: it reads their payments and carries out their recorded ends at the site.
    servicing_loop: str

    def lifecycle_read(self, negotiation_id: str) -> LifecycleRead:
        """The storefront's lifecycle read of the deal, as its buyer reads it."""


def _snapshot(payments_config: Any, payer: str, transaction: str) -> dict[str, Any]:
    """The transaction's snapshot at the payments double, read with the buyer's
    own token, as JSON."""
    with buyer_payments_client(payments_config, payer) as client:
        signed = client.get_transaction(transaction)
    return signed.snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)


def approved_run_id(run_dir: Path) -> str | None:
    """The run whose log records an approved payment, or ``None``.

    A recurring purchase's profile keeps the one buy run, so this finds it
    even when the purchase command failed before a stage recorded it. A line a
    crash left half-written is skipped.
    """
    for path in sorted(run_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event") == "payment_approved":
                return path.stem
    return None


def recurring_purchase_cleanup(
    purchase_cli: Any, deal_driver: RecurringPurchaseDriver, deal_state: RecurringPurchaseState,
) -> list[CleanupStep]:
    """Whatever the stages left: a purchase command still running, and an
    approved payment still reserved or running at the payments double.

    The seller's refund refuses a rate deal, so a payment the stages left is
    stopped by the buyer's own ``end``, the one ``Recurring07`` runs. Its stop
    is journaled under one operation key, so running it again after a partial
    end resumes that stop rather than sending a second one.
    """
    def stop_purchase_command() -> None:
        if deal_state.purchase_run is not None:
            deal_state.purchase_run.terminate()

    def end_by_the_buyers_stop() -> None:
        if deal_state.buyer_end is not None:
            return
        run_id = approved_run_id(purchase_cli.run_dir)
        if run_id is None:
            return
        run = purchase_cli.run(deal_driver.teardown_arguments(run_id))
        assert_market_run_succeeded(run, command=deal_driver.teardown_command)

    return [
        ("stop the purchase command", stop_purchase_command),
        ("end the deal by the buyer's own stop", end_by_the_buyers_stop),
    ]


# ===========================================================================
# The approval
# ===========================================================================

class Recurring04_MandateApproved:
    def test_r04_the_buyer_approved_one_rate_part_charging_one_periods_price(
        self, payments_config, deal_state: RecurringPurchaseState,
    ):
        """The correlated Agreement's mandate, and what the payments double approved.

        ``Purchase04`` correlated the run's events as one paid deal; its
        mandate is one rate part charging one period's price per period. The
        double's snapshot and receipt verify against the receipt keys the
        payments configuration trusts, bound to that Agreement and mandate;
        the receipt reserves whole periods of that price, and the payer's
        available balance fell by exactly the receipt's gross, while nothing
        else spends from the payer account (a topology guarantee this scenario
        cannot check, so it is logged beside the result). Read before
        ``Stage09a`` converges the fulfillment, so before delivery can start
        the rate part.
        """
        require_state(deal_state, "purchase_run", "negotiation_id", "settlement_id",
                      "agreement", "payment_settlement", "payer_available_before")
        run = deal_state.purchase_run
        negotiation_id = deal_state.negotiation_id
        agreement = deal_state.agreement
        data = deal_state.payment_settlement

        mandate = data.mandate.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert len(mandate["parts"]) == 1, (
            f"the mandate of {negotiation_id} has {len(mandate['parts'])} parts, where a "
            f"recurring option with no setup charge has one rate part: {mandate['parts']}"
        )
        (part,) = mandate["parts"]
        assert (part["kind"], part["asset"], part["amount"], part["period"]) == (
            "rate", ASSET, str(PERIOD_GROSS), PERIOD,
        ), part

        payer = str(deal_state.payer_account)
        payee = str(payment_setting("SELLER_ACCOUNT"))
        with buyer_payments_client(payments_config, payer) as client:
            signed = client.get_transaction(data.transaction_id)
            after = available_balances(client.get_balance(payer))
        trust = payments_config.receipt_trust
        bound = {"mandate": data.mandate, "agreement_json": agreement,
                 "livemode": payments_config.livemode}
        assert verify_snapshot(signed, trust, **bound), (
            f"the snapshot of {data.transaction_id} is not the pinned service's for this "
            "Agreement and mandate"
        )
        assert verify_receipt(signed.snapshot.receipt, trust, **bound), (
            f"the receipt of {data.transaction_id} does not cover the Agreement's mandate"
        )
        receipt = signed.snapshot.receipt.receipt.model_dump(mode="json", by_alias=True, exclude_none=True)
        assert (receipt["from"], receipt["to"]) == (payer, payee), receipt
        assert len(receipt["parts"]) == 1, receipt["parts"]
        (reserved,) = receipt["parts"]
        assert reserved["rate"]["period"] == PERIOD, reserved
        gross = int(reserved["gross"])
        assert gross == PERIOD_GROSS * int(reserved["rate"]["periodsReserved"]) > 0, reserved

        before = deal_state.payer_available_before
        dropped = {
            asset: before.get(asset, 0) - after.get(asset, 0)
            for asset in sorted(set(before) | set(after))
            if before.get(asset, 0) != after.get(asset, 0)
        }
        log.info("[r04] Payer %s is assumed dedicated to this run (a topology guarantee); "
                 "available fell by %s, transaction %s reserved %s", payer, dropped,
                 data.transaction_id, gross)
        assert dropped == {ASSET: gross}, (
            f"payer {payer}'s available balance fell by {dropped}; approval of "
            f"{data.transaction_id} reserved {gross} {ASSET}"
        )
        deal_state.receipt_gross = gross
        log.info("[r04] Run %s: Agreement %s, transaction %s: one rate part of %s %s per %s",
                 run.run_id, negotiation_id, data.transaction_id, PERIOD_GROSS, ASSET, PERIOD)


# ===========================================================================
# Delivery
# ===========================================================================

def _unix_second(instant: datetime) -> int:
    """The whole Unix second ``instant`` falls in: the payments double records
    its instants in whole seconds, so one it records after ``instant`` is no
    earlier than this."""
    return int(instant.timestamp())


class Recurring05_RateStartedAfterActivation:
    def test_r05_the_rate_part_started_after_the_sites_activation(
        self, storefront_admin_client, payments_config,
        deal_driver: RecurringPurchaseDriver, deal_state: RecurringPurchaseState,
    ):
        """The delivered deal's rate part started after the site activated it.

        One pass of the storefront loop that services the domain's deals runs
        first, so what is read follows the storefront's own servicing of a
        running rate deal as well as the delivery's drive. The lease
        ``Stage09c`` recorded names the site's activation; the payments double
        records the part started, and one start event, no earlier than the
        whole second of that activation, since delivery starts billing only once
        the site has activated the deal. The double records whole seconds, so a
        start within the activation's own second passes either way; each
        storefront's ``test_rate_delivery.py`` proves billing starts from the
        recorded activation. The lifecycle read
        names the committed transaction and shows the deal active, with no end
        and no filing.
        """
        require_state(deal_state, "negotiation_id", "settlement_id", "payer_account",
                      "settlement_status", "deal_lease")
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        lease = deal_state.deal_lease.refresh()
        activated = _unix_second(utc_instant(lease.get("activated_at_utc")))

        snapshot = _snapshot(payments_config, deal_state.payer_account, deal_state.settlement_id)
        (part,) = snapshot["parts"]
        assert part.get("started") is not None, f"the double records no rate start: {part}"
        assert int(part["started"]) >= activated, (
            f"the rate part started at {part['started']}, before the site activated the "
            f"deal at {lease.get('activated_at_utc')}: {part}"
        )
        starts = [event for event in snapshot["events"]
                  if event.get("event", {}).get("kind") == "start"]
        assert len(starts) == 1, snapshot["events"]
        assert int(starts[0]["receivedAt"]) >= activated, (starts, lease)

        read = deal_driver.lifecycle_read(deal_state.negotiation_id)
        assert read.commitment_ref == deal_state.settlement_id, read
        assert read.delivery.progress == "active", read.delivery
        assert read.delivery.recorded_end is None, read.delivery
        assert read.filings == [], read.filings
        deal_state._rate_started = True
        log.info("[r05] Agreement %s delivered under transaction %s: activated %s, rate part "
                 "started %s, progress %s", deal_state.negotiation_id, deal_state.settlement_id,
                 lease.get("activated_at_utc"), part["started"], read.delivery.progress)


class Recurring06_AcceptedMoneyShown:
    def test_r06_the_purchase_command_showed_the_accepted_money(
        self, deal_driver: RecurringPurchaseDriver, deal_state: RecurringPurchaseState,
    ):
        """The ended purchase command showed the buyer the money it approved.

        ``Purchase09`` waited for the command to end, once the settlement read
        ready. Its stderr holds the accepted Agreement's terms: the per-period
        price, the setup charge, the initial reserve — the receipt's gross,
        what approval took from the payer — and the maximum accepted end, the
        Agreement's start plus its duration. This stage observes only that
        stderr holds them, not when they were printed; each buyer's own tests
        prove they precede its settlement stage, which approves (bare metal's
        ``test_cli_completion.py``, VM's ``test_buy_orchestrator.py``).
        """
        require_state(deal_state, "purchase_run", "_rate_started", "agreement", "receipt_gross")
        run = deal_state.purchase_run
        assert run.exited, (
            f"{deal_driver.buy_command} run {run.run_id} is still running; Purchase09 waits "
            "for it to end"
        )
        agreement = deal_state.agreement
        start = datetime.fromisoformat(str(agreement["start_utc"]).replace("Z", "+00:00"))
        end = start + timedelta(seconds=int(agreement["duration_seconds"]))
        shown = run.stderr()
        expected = (
            DISCLOSURE_TITLE,
            f"  Accepted price: {PERIOD_GROSS} minor units of {ASSET} per_period "
            f"({PERIOD}, {PERIOD_SECONDS} seconds)",
            f"  Setup once charge: 0 minor units of {ASSET}",
            f"  Initial reserve: {deal_state.receipt_gross} minor units of {ASSET};",
            f"  Maximum accepted end: {end.isoformat()}",
        )
        missing = [row for row in expected if row not in shown]
        assert not missing, (
            f"{deal_driver.buy_command} run {run.run_id} did not show {missing}; "
            f"its stderr:\n{shown[-3000:]}"
        )
        deal_state._accepted_money_shown = True
        log.info("[r06] Run %s showed the accepted per-period price, setup, reserve and end",
                 run.run_id)


# ===========================================================================
# The buyer's end
# ===========================================================================

class Recurring07_BuyerEnds:
    def test_r07_the_buyers_end_charges_the_started_period_and_begins_the_teardown(
        self, purchase_cli, payments_config, provisioning_client, storefront_admin_client,
        deal_driver: RecurringPurchaseDriver, deal_state: RecurringPurchaseState,
    ):
        """The buyer's ``end`` stops the payment, and the storefront ends the delivery.

        The normal end of a rate deal: the payer's stop at the payments double,
        accepted, then a hint, which makes the storefront read the double. The
        stop takes effect at once, with no payer notice, inside the started
        period, which it charges: the part is stopped by the payer, charging
        one period's price to the payee and reserving nothing more. On the
        hint's read the storefront records the payer's stop as the deal's end,
        before the delivery deadline, so it files no seller non-delivery: the
        scenario does not wait for that deadline.

        One pass of the storefront loop that services the domain's deals then
        runs the cycle its timer would, which carries out a recorded end at the
        site; bare metal's hint has already carried it out, and VM's leaves it
        to that cycle. Either way the end leaves the lease ``releasing``, never
        released, so ``Stage11b``'s own lease cycle is what releases it, and one
        convergence advance dispatches the teardown, the state ``Stage11b``
        starts from, as a buyer purchase's teardown does (``Purchase10``).
        """
        require_state(deal_state, "_accepted_money_shown", "purchase_run", "payer_account",
                      "negotiation_id", "settlement_id", "deal_lease", "lease_id",
                      "reserved_resource_id")
        # The release is Stage11b's own lease cycle, not the timer's.
        assert_lease_watchdog_held(provisioning_client)
        deal_state._buyer_teardown_requested = True
        run = purchase_cli.run(deal_driver.teardown_arguments(deal_state.purchase_run.run_id))
        assert_market_run_succeeded(run, command=deal_driver.teardown_command)
        ended = json.loads(run.stdout().strip().splitlines()[-1])
        progress = EndDeliveryProgress.model_validate(ended["progress"])
        assert progress.mode == "normal_stop", progress
        assert isinstance(progress.payment, Accepted), progress
        deal_state.buyer_end = ended

        snapshot = _snapshot(payments_config, deal_state.payer_account, deal_state.settlement_id)
        (part,) = snapshot["parts"]
        stop = part.get("stop") or {}
        assert (stop.get("cause"), stop.get("partialPeriod")) == ("payer", "charged"), part
        assert part.get("reserved", "0") == "0", part
        assert int(part["held"]) + int(part["released"]) == PERIOD_GROSS, part

        read = deal_driver.lifecycle_read(deal_state.negotiation_id)
        assert read.delivery.recorded_end is not None, read.delivery
        assert read.delivery.recorded_end.cause == "payer", read.delivery
        assert read.filings == [], read.filings

        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        # The cycle files nothing for an end the payer's stop recorded.
        filings = deal_driver.lifecycle_read(deal_state.negotiation_id).filings
        assert filings == [], filings
        lease = deal_state.deal_lease.refresh()
        assert lease.get("status") == "releasing", (
            "the buyer's end should leave the lease releasing for the lease "
            f"lifecycle's own cycle to release: {lease}"
        )
        status = deal_driver.purchase_fulfillment(deal_state.negotiation_id)
        fulfillment_id = str(status.get("fulfillment_id") or "")
        assert fulfillment_id and fulfillment_id == lease.get("fulfillment_id"), (status, lease)
        pending = provisioning_client.get_fulfillment_status(fulfillment_id).model_dump(mode="json")
        assert pending.get("state") == "teardown_dispatch_pending", pending

        provisioning_client.advance_fulfillment_convergence_cycle()
        dispatched = provisioning_client.get_fulfillment_status(fulfillment_id).model_dump(mode="json")
        assert dispatched.get("state") == "tearing_down", dispatched
        assert deal_state.deal_lease.resource_consumed(
            storefront_admin_client, deal_state.reserved_resource_id
        )
        deal_state.teardown_fulfillment_id = fulfillment_id
        log.info("[r07] Buyer ended Agreement %s: payer's stop accepted charging the started "
                 "period, end recorded at %s with no filing; lease %s releasing, fulfillment %s "
                 "tearing down", deal_state.negotiation_id, read.delivery.recorded_end.ended_at,
                 deal_state.lease_id, fulfillment_id)


class Recurring08_PayerChargedOnePeriod:
    def test_r08_the_payer_paid_one_periods_price(
        self, payments_config, deal_state: RecurringPurchaseState,
    ):
        """The started period was charged and the rest of the reservation
        returned: the payer's available balance is what ``Purchase01`` read,
        less one period's price, while nothing else spends from the account."""
        require_state(deal_state, "buyer_end", "payer_account", "payer_available_before")
        payer = str(deal_state.payer_account)
        with buyer_payments_client(payments_config, payer) as client:
            after = available_balances(client.get_balance(payer))
        before = deal_state.payer_available_before
        expected = {**before, ASSET: before.get(ASSET, 0) - PERIOD_GROSS}
        assert after == expected, (
            f"payer {payer}'s available balance is {after} after the buyer's stop; it was "
            f"{before} before the purchase, and one period costs {PERIOD_GROSS} {ASSET}"
        )
        log.info("[r08] Payer %s available %s: one period's %s %s charged", payer, after,
                 PERIOD_GROSS, ASSET)
