"""Stages of a recurring purchase through the shipped buyer, defined once.

A recurring purchase buys a seller's recurring on-demand option in
``arkhai.payments.v1`` through the domain's own buyer CLI (``market buy``,
``market bare-metal buy``) with a default buyer, against a lane whose storefront
declares rate servicing for ``charged`` and ``returned``. That declaration is a
lane fixture, never a shipped default: it lets the seller publish the option and
accept it, not service it. End service services no rate deal, so it refuses the
commit: the buyer approves and commits, and the deal is never delivered. The
seller's refund refuses a rate deal, so the buyer ends the deal by its own
``end``, the payer's stop at the payments double and a hint to the storefront,
and its whole reservation returns. The result is lane-double evidence of the
money a buyer is shown and approves for a per-period Agreement and of the
refused commit, never of rate delivery.

A recurring purchase module declares, in order, each by subclassing it with an
empty body:

- the canonical deal's readiness stages a buyer purchase shares (``Stage00`` to
  ``Stage00c2``, a mock lane's ``Stage00e``, ``Stage00f1``, which seeds the
  supply through the driver, and ``Stage00h``), then its own listing stage,
  which writes ``seller_listing_id`` and ``listing_published``;
- ``Purchase01`` to ``Purchase03`` of ``buyer_purchase_stages.py``: the payer's
  balance, the listing discovered, the purchase command run to its commit;
- ``Recurring04`` to ``Recurring08`` here.

``tests/unit/test_recurring_purchase_stages.py`` holds every recurring purchase
module to that order. Nothing is delivered, so no mock gate is armed and no
stage from fulfillment onwards runs.

What differs between domains reaches a stage through the ``deal_driver``
fixture, a ``RecurringPurchaseDriver``: the buyer purchase's driver, the
storefront loop that services the domain's deals, how the domain's purchase
command ends once its commit is accepted, and the storefront's lifecycle read
as the purchase's buyer.
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
    accepted_purchase,
    available_balances,
)
from tests.e2e.roles.helpers.cleanup import CleanupStep
from tests.e2e.roles.helpers.compute_deal import advance_storefront
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
#: The rows the buyer prints on stderr before it approves, which the shipped
#: buyers share.
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

    ``Recurring04`` writes the purchase's ``negotiation_id``, ``settlement_id``,
    ``settlement_ref``, ``agreement`` and ``payment_settlement``, as a buyer
    purchase's correlation does, and ``Recurring07`` its
    ``_buyer_teardown_requested`` before the buyer's end.
    """

    #: The payments double's receipt gross for the transaction: what approval
    #: reserved from the payer.
    receipt_gross: Optional[int] = None
    #: End service refused the commit, and nothing was delivered or started.
    _commit_refused: bool = False
    #: The purchase command has ended, and its pre-approval display was read.
    _purchase_run_closed: bool = False
    #: What the buyer's ``end`` printed once its payer's stop was accepted.
    buyer_end: Optional[dict[str, Any]] = None


class RecurringPurchaseDriver(PurchaseDriver, Protocol):
    """What a domain supplies to a recurring purchase, beside a purchase's part."""

    #: The storefront's site ledger, read for the deal's reservations.
    site_capacity: Any
    #: The storefront loop that services the domain's committed deals.
    servicing_loop: str

    def close_purchase_run(self, run: Any, deal_state: Any) -> None:
        """End the domain's purchase command once its commit is accepted,
        asserting what it recorded of a deal that is never delivered."""

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
    approved payment still reserved at the payments double.

    The seller's refund refuses a rate deal, so a reservation the stages left
    is released by the buyer's own ``end``, the one ``Recurring07`` runs. Its
    stop is journaled under one operation key, so running it again after a
    partial end resumes that stop rather than sending a second one.
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
        """The run's Agreement and mandate, and what the payments double approved.

        The run's events correlate one paid deal (``accepted_purchase``), and
        its mandate is one rate part charging one period's price per period.
        The double's snapshot and receipt verify against the
        receipt keys the payments configuration trusts, bound to that Agreement
        and mandate; the receipt reserves whole periods of that price, and the
        payer's available balance fell by exactly the receipt's gross, while
        nothing else spends from the payer account (a topology guarantee this
        scenario cannot check, so it is logged beside the result).
        """
        require_state(deal_state, "purchase_run", "seller_listing_id", "purchase_option_id",
                      "payer_available_before")
        run = deal_state.purchase_run
        negotiation_id, agreement, data = accepted_purchase(
            run, listing_id=deal_state.seller_listing_id, option_id=deal_state.purchase_option_id,
        )

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
        deal_state.negotiation_id = negotiation_id
        deal_state.settlement_id = data.transaction_id
        # The negotiation is what every storefront resolves a payments deal by.
        deal_state.settlement_ref = negotiation_id
        deal_state.agreement = agreement
        deal_state.payment_settlement = data
        deal_state.receipt_gross = gross
        log.info("[r04] Run %s: Agreement %s, transaction %s: one rate part of %s %s per %s",
                 run.run_id, negotiation_id, data.transaction_id, PERIOD_GROSS, ASSET, PERIOD)


# ===========================================================================
# The refused commit
# ===========================================================================

class Recurring05_CommitRefused:
    def test_r05_end_service_refused_the_commit_and_nothing_is_delivered(
        self, storefront_admin_client, payments_config,
        deal_driver: RecurringPurchaseDriver, deal_state: RecurringPurchaseState,
    ):
        """The commit was accepted, and end service refused to deliver the deal.

        One pass of the storefront loop that services the domain's deals runs
        first, so what is read follows the storefront's own servicing as well
        as the commit's drive. The lifecycle read names the committed
        transaction, and shows delivery never active, no end and no filing;
        the site holds no reservation for the negotiation; and the payments
        double records no rate start, neither the part's start nor a start
        event. Why end service refused, its repair reason, is read by no
        storefront interface, so its own tests prove it.
        """
        require_state(deal_state, "negotiation_id", "settlement_id", "payer_account")
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        read = deal_driver.lifecycle_read(deal_state.negotiation_id)
        assert read.commitment_ref == deal_state.settlement_id, read
        assert read.delivery.progress != "active", read.delivery
        assert read.delivery.recorded_end is None, read.delivery
        assert read.filings == [], read.filings
        held = deal_driver.site_capacity.reservations_for_negotiation(deal_state.negotiation_id)
        assert held == [], f"the site holds capacity for the refused deal: {held}"

        snapshot = _snapshot(payments_config, deal_state.payer_account, deal_state.settlement_id)
        (part,) = snapshot["parts"]
        assert "started" not in part, part
        kinds = [event.get("event", {}).get("kind") for event in snapshot["events"]]
        assert "start" not in kinds, snapshot["events"]
        deal_state._commit_refused = True
        log.info("[r05] Agreement %s committed under transaction %s and not delivered: "
                 "progress %s, no reservation, no rate start", deal_state.negotiation_id,
                 deal_state.settlement_id, read.delivery.progress)


class Recurring06_PurchaseRunClosed:
    def test_r06_the_purchase_command_showed_the_accepted_money_before_approval(
        self, deal_driver: RecurringPurchaseDriver, deal_state: RecurringPurchaseState,
    ):
        """The purchase command ends, having shown the buyer the money it approved.

        How the domain's command ends once its commit is accepted is the
        driver's. Its stderr holds the accepted Agreement's terms, which the
        shipped buyers print before they approve: the per-period price, the
        setup charge, the initial reserve — the receipt's gross, what approval
        took from the payer — and the maximum accepted end, the Agreement's
        start plus its duration. That they precede the approval is the buyers'
        code, not something this stage observes.
        """
        require_state(deal_state, "purchase_run", "_commit_refused", "agreement", "receipt_gross")
        run = deal_state.purchase_run
        deal_driver.close_purchase_run(run, deal_state)
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
            f"{deal_driver.buy_command} run {run.run_id} did not show {missing} before "
            f"approval; its stderr:\n{shown[-3000:]}"
        )
        deal_state._purchase_run_closed = True
        log.info("[r06] Run %s showed the accepted per-period price, setup, reserve and end "
                 "before approval", run.run_id)


# ===========================================================================
# The buyer's end
# ===========================================================================

class Recurring07_BuyerEnds:
    def test_r07_the_buyers_end_stops_the_payment_and_the_seller_records_the_payers_end(
        self, purchase_cli, payments_config,
        deal_driver: RecurringPurchaseDriver, deal_state: RecurringPurchaseState,
    ):
        """The buyer's ``end`` stops the payment; the storefront records the payer's end.

        The normal end of a rate deal: the payer's stop at the payments double,
        accepted, then a hint, which makes the storefront read the double. The
        stop takes effect at once, with no payer notice and nothing started, so
        the part is stopped by the payer with nothing held or reserved. The
        storefront records the payer's stop as the deal's end, before the
        delivery deadline, so it files no seller non-delivery: the scenario
        does not wait for that deadline.
        """
        require_state(deal_state, "_purchase_run_closed", "negotiation_id", "settlement_id")
        deal_state._buyer_teardown_requested = True
        run = purchase_cli.run(deal_driver.teardown_arguments(deal_state.purchase_run.run_id))
        assert_market_run_succeeded(run, command=deal_driver.teardown_command)
        ended = json.loads(run.stdout().strip().splitlines()[-1])
        progress = EndDeliveryProgress.model_validate(ended["progress"])
        assert progress.mode == "normal_stop", progress
        assert isinstance(progress.payment, Accepted), progress

        snapshot = _snapshot(payments_config, deal_state.payer_account, deal_state.settlement_id)
        (part,) = snapshot["parts"]
        assert "started" not in part, part
        assert part.get("stop", {}).get("cause") == "payer", part
        assert (part["held"], part.get("reserved", "0")) == ("0", "0"), part

        read = deal_driver.lifecycle_read(deal_state.negotiation_id)
        assert read.delivery.recorded_end is not None, read.delivery
        assert read.delivery.recorded_end.cause == "payer", read.delivery
        assert read.filings == [], read.filings
        deal_state.buyer_end = ended
        log.info("[r07] Buyer ended Agreement %s: payer's stop accepted, end recorded at %s, "
                 "no filing", deal_state.negotiation_id, read.delivery.recorded_end.ended_at)


class Recurring08_PayerBalanceRestored:
    def test_r08_the_payers_available_balance_is_restored(
        self, payments_config, deal_state: RecurringPurchaseState,
    ):
        """The unearned reservation returned: the payer's available balance is
        what ``Purchase01`` read, while nothing else spends from the account."""
        require_state(deal_state, "buyer_end", "payer_account", "payer_available_before")
        payer = str(deal_state.payer_account)
        with buyer_payments_client(payments_config, payer) as client:
            after = available_balances(client.get_balance(payer))
        assert after == deal_state.payer_available_before, (
            f"payer {payer}'s available balance is {after} after the buyer's stop; it was "
            f"{deal_state.payer_available_before} before the purchase"
        )
        log.info("[r08] Payer %s available restored to %s", payer, after)
