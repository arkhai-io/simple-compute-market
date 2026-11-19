"""Stages of a recurring purchase through the shipped buyer, defined once.

A recurring purchase buys a seller's recurring option in ``arkhai.payments.v1``
through the domain's own buyer CLI (``market buy``, ``market bare-metal buy``)
with a default buyer, against a lane whose storefront declares rate servicing
for ``charged`` and ``returned``. That declaration is a lane fixture, never a
shipped default. End service asks the payments adapter whether to deliver the
committed deal, so the deal is delivered: the site activates it, then the
storefront starts the rate part at the payments double, then the deal is
available. The buyer ends the deal by its own ``end``, the payer's stop at the
payments double and a hint to the storefront; the stop charges the started
period, and the storefront records the payer's end, tears the delivery down,
and lists the deal ``ended`` once the release is proven. The result is
lane-double evidence of the money a buyer is shown and approves for a
per-period Agreement, of rate delivery and of the buyer's end.

Every instant is reached by setting lane time (``helpers/lane_time.py``), never
by waiting: lane time is one frozen instant every party shares, so the stages
set the Agreement's start before stepping delivery recovery, and an instant
inside the first period before the buyer's stop, which a stop at the start
itself would leave uncharged. A run on wall time reaches only an instant the
Agreement fixes, by waiting for it, and needs no other: its clock moves on its
own.

A recurring purchase module declares, in order, each by subclassing it with an
empty body:

- the canonical deal's readiness stages a buyer purchase shares (``Stage00`` to
  ``Stage00c2``, a mock lane's ``Stage00e``, ``Stage00f1``, which seeds the
  supply through the driver, and ``Stage00h``), then its own listing stage,
  which writes ``seller_listing_id`` and ``listing_published``;
- ``Purchase01`` to ``Purchase04`` of ``buyer_purchase_stages.py``, arming the
  create gate (``Stage07a``) before the buy and releasing and draining it
  (``Stage08b2``) after the correlation, then ``Recurring04``'s mandate;
- the canonical deal's convergence, ``Stage09a``, with its own stage closing the
  listing (``Stage09a2``), then ``Recurring05``'s delivery recovery at the
  Agreement's start, ``Stage09b`` and ``Stage09c``, then ``Recurring06``'s rate
  start, ``Purchase09``'s end of the purchase command, and ``Recurring07``'s
  accepted money;
- the deal's ending: here the buyer's end, ``Stage09c2`` arming the teardown
  gate, ``Recurring08``, ``Stage11a2`` and ``Stage11b``'s teardown, then
  ``Recurring09``'s balance and ``Recurring10``'s seller list.

The rate servicing rows (``rate_servicing_stages.py``) share every stage up to
``Recurring07`` and end their deals their own ways.
``tests/unit/test_recurring_purchase_stages.py`` holds every module to its
order.

What differs between domains reaches a stage through the ``deal_driver``
fixture, a ``RecurringPurchaseDriver``: the buyer purchase's driver, the
storefront loop that services the domain's deals, the storefront's lifecycle
read as the purchase's buyer, and the buyer's own read of its run's deal.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Protocol

import pytest
from market_arkhai_payments import ARKHAI_PAYMENTS_MECHANISM, verify_receipt, verify_snapshot
from market_core.schemas import SettlementOption, compute_rate_total
from market_deal_lifecycle_buyer import EndDeliveryProgress
from market_deal_lifecycle_client import SyncSellerLifecycleClient
from market_deal_lifecycle_contracts.models import (
    Accepted,
    DealSummary,
    LifecycleRead,
    ListDealsRequest,
)

from tests.e2e.roles.helpers.buyer_purchase_stages import (
    PurchaseDriver,
    PurchaseState,
    available_balances,
)
from tests.e2e.roles.helpers.cleanup import CleanupStep
from tests.e2e.roles.helpers.compute_deal import advance_storefront, assert_lease_watchdog_held
from tests.e2e.roles.helpers.compute_deal_stages import reach_agreement_instant, utc_instant
from tests.e2e.roles.helpers.domain_deal import assert_market_run_succeeded, require_state
from tests.e2e.roles.helpers.lane_time import LaneTime, wait_until
from tests.e2e.roles.helpers.payments import (
    buyer_payments_client,
    dispute_window_seconds,
    payment_flag,
    payment_setting,
)
from tests.e2e.roles.helpers.producer_assertions import assert_payer_stop

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
#: The storefront loop that re-drives unfinished deliveries.
DELIVERY_RECOVERY = "delivery-recovery"
#: How far into its first period the buyer stops the deal. Lane time holds
#: still between sets, so a stop with no time set would fall at the start
#: itself, where the double charges nothing of a period not yet entered.
STOP_INTO_PERIOD_SECONDS = 60


def recurring_settlement(
    *, seller_account: str, delivery_deadline_seconds: int,
    payee_notice_seconds: int | None = None,
) -> dict[str, Any]:
    """The payments publication clause of a recurring option.

    USD 1.00 an hour paid to ``seller_account`` per ``PERIOD``, with no setup
    charge, so a shipped preset: the payer's stop charges its started period,
    and the term end returns the last one. With no payee notice it is the
    on-demand preset; ``payee_notice_seconds`` makes it the spot preset, whose
    seller may stop with that notice, returning the period it stops in. The
    run's dispute coverage covers ``delivery_deadline_seconds``.
    """
    recurring: dict[str, Any] = {"period": PERIOD, "reserve_ahead_seconds": RESERVE_AHEAD_SECONDS}
    if payee_notice_seconds is not None:
        recurring["payee_notice_seconds"] = payee_notice_seconds
    return {
        "mechanism": ARKHAI_PAYMENTS_MECHANISM, "asset": ASSET, "rate": HOURLY_RATE, "per": "hour",
        "recurring": recurring,
        "mechanism_input": {
            "payee_account": seller_account, "asset": ASSET,
            "approval_window": APPROVAL_WINDOW,
            "delivery_deadline_seconds": delivery_deadline_seconds,
            "dispute_window_seconds": dispute_window_seconds(
                delivery_deadline_seconds=delivery_deadline_seconds,
            ),
        },
    }


def check_recurring_option(
    option: SettlementOption, *, delivery_deadline_seconds: int,
    payee_notice_seconds: int | None = None,
) -> None:
    """What the seller published for ``recurring_settlement``: one period's
    price per ``PERIOD``, the entitlements a default buyer accepts — the
    payer's alone for on-demand, beside the seller's notice stop returning its
    period for spot — and the pool's delivery deadline."""
    params = option.settlement_params
    assert (params.get("period"), params.get("reserve_ahead_seconds")) == (
        PERIOD, RESERVE_AHEAD_SECONDS,
    ), option
    assert params.get("approval_window") == APPROVAL_WINDOW, option
    assert "setup_amount" not in params, option
    assert option.price_asset == ASSET, option
    assert compute_rate_total(option.price_rates[0], PERIOD_SECONDS) == PERIOD_GROSS, option
    early = option.lifecycle["early_termination"]
    entitlements = {"payer": {"notice_seconds": 0, "settles_through": "started_period"}}
    if payee_notice_seconds is not None:
        entitlements["payee"] = {"notice_seconds": payee_notice_seconds,
                                 "settles_through": "last_boundary"}
    assert early["entitlements"] == entitlements, early
    assert early["settles_through"] == "last_boundary", early
    if payee_notice_seconds is None:
        # A default buyer refuses an on-demand option without a positive penalty.
        assert int(early["premature_stop_penalty"]) > 0, early
    assert option.lifecycle["delivery_deadline_seconds"] == delivery_deadline_seconds, option


@dataclass
class RecurringPurchaseState(PurchaseState):
    """What a recurring purchase's stages hand each other, beside the purchase's.

    ``Purchase04``'s correlation writes the purchase's ``negotiation_id``,
    ``settlement_id``, ``agreement`` and ``payment_settlement``, which
    ``Recurring04`` checks, and an ending writes ``_buyer_teardown_requested``
    or ``_deal_ending`` before it ends the deal and ``teardown_fulfillment_id``
    once the teardown is dispatched.
    """

    #: The payments double's receipt gross for the transaction: what approval
    #: reserved from the payer.
    receipt_gross: Optional[int] = None
    #: A delivery-recovery step ran once lane time held the Agreement's start.
    _delivery_recovered: bool = False
    #: The payments double started the rate part no earlier than the whole
    #: second of the site's activation, and the storefront reads the deal active.
    _rate_started: bool = False
    #: The ended purchase command's stderr showed the accepted money.
    _accepted_money_shown: bool = False
    #: What the buyer's ``end`` printed once its payer's stop was accepted.
    buyer_end: Optional[dict[str, Any]] = None
    #: An ending other than the buyer's own stop has begun, so cleanup sends
    #: no stop of the buyer's.
    _deal_ending: bool = False
    #: The payer paid what the ending charged, and no more.
    _payer_charged: bool = False


class RecurringPurchaseDriver(PurchaseDriver, Protocol):
    """What a domain supplies to a recurring purchase, beside a purchase's part."""

    #: The storefront loop whose cycle services the domain's committed deals:
    #: it reads their payments and carries out their recorded ends at the site.
    servicing_loop: str

    def lifecycle_read(self, negotiation_id: str) -> LifecycleRead:
        """The storefront's lifecycle read of the deal, as its buyer reads it."""

    def read_arguments(self, run_id: str) -> list[str]:
        """The domain's buyer read of the run's deal (``delivery``), and its arguments."""


def transaction_snapshot(payments_config: Any, payer: str, transaction: str) -> dict[str, Any]:
    """The transaction's snapshot at the payments double, read with the payer's
    own token, as JSON. A read brings the transaction to the double's time,
    recording any stop due by then, and never reserves a further period: only
    the double's reservation control does (``rate_servicing_stages.py``)."""
    with buyer_payments_client(payments_config, payer) as client:
        signed = client.get_transaction(transaction)
    return signed.snapshot.model_dump(mode="json", by_alias=True, exclude_none=True)


def payer_available(payments_config: Any, payer: str) -> dict[str, int]:
    """The payer's own available balance by asset, read with its token."""
    with buyer_payments_client(payments_config, payer) as client:
        return available_balances(client.get_balance(payer))


def buyer_read(purchase_cli: Any, deal_driver: RecurringPurchaseDriver,
               deal_state: RecurringPurchaseState) -> dict[str, Any]:
    """The buyer's own read of its run's deal, as its ``delivery`` command prints it."""
    run = purchase_cli.run(deal_driver.read_arguments(deal_state.purchase_run.run_id))
    assert_market_run_succeeded(run, command="the buyer's delivery read")
    return json.loads(run.stdout().strip().splitlines()[-1])


def lane_double_run(lane_time: LaneTime | None) -> bool:
    """Whether the run is a Compose lane's: injected lane time and the lane's own
    payments double (``PAYMENTS.LANE_OWNED``), whose controls only such a run
    reaches."""
    return lane_time is not None and lane_time.injected and bool(payment_flag("LANE_OWNED"))


def reach_lane_instant(lane_time: LaneTime | None, instant: int, *,
                       fixed_by_agreement: bool) -> int:
    """Bring the lane to ``instant``, or past it, and return the lane instant.

    An injected run sets lane time; a wall run, or one with no lane time, waits
    only for an instant the Agreement fixes, and is a blocked skip for any
    other.
    """
    if lane_time is None:
        if not fixed_by_agreement:
            pytest.skip(f"blocked: reaching {instant} needs lane time, and the run has none")
        return int(wait_until(datetime.fromtimestamp(instant, timezone.utc)).timestamp())
    return lane_time.reach(instant, fixed_by_agreement=fixed_by_agreement)


def seller_deal(storefront_admin_client: Any, negotiation_id: str) -> DealSummary:
    """The deal as the seller's list shows it, read page by page as its
    administrator through the typed seller lifecycle client."""
    client = SyncSellerLifecycleClient(storefront_admin_client)
    request = ListDealsRequest(limit=100)
    while True:
        page = client.list(request)
        for deal in page.deals:
            if deal.negotiation_id == negotiation_id:
                return deal
        if page.continuation is None:
            raise AssertionError(f"the seller's list does not show {negotiation_id}")
        request = ListDealsRequest(limit=100, continuation=page.continuation)


def begin_teardown(
    provisioning_client: Any, storefront_admin_client: Any,
    deal_driver: RecurringPurchaseDriver, deal_state: RecurringPurchaseState,
) -> str:
    """The delivery's end carried out at the site, held at its teardown gate.

    Once the storefront has recorded the deal's end and a servicing step has
    run, the end has left the lease ``releasing``, never released, so
    ``Stage11b``'s own lease cycle is what releases it, and one convergence
    advance dispatches the teardown, the state ``Stage11b`` starts from, as a
    buyer purchase's teardown does (``Purchase10``). Returns the fulfillment,
    which the calling stage records for the teardown stages.
    """
    lease = deal_state.deal_lease.refresh()
    assert lease.get("status") == "releasing", (
        "the deal's end should leave the lease releasing for the lease "
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
    return fulfillment_id


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
    stopped by the buyer's own ``end``, the one ``Recurring08`` runs. Its stop
    is journaled under one operation key, so running it again after a partial
    end resumes that stop rather than sending a second one. A deal another
    ending has begun to end is left to it.
    """
    def stop_purchase_command() -> None:
        if deal_state.purchase_run is not None:
            deal_state.purchase_run.terminate()

    def end_by_the_buyers_stop() -> None:
        if deal_state.buyer_end is not None or deal_state._deal_ending:
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
                      "agreement", "payment_settlement", "payer_account",
                      "payer_available_before")
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


class Recurring05_DeliveryRecoveredAtTheStart:
    def test_r05_delivery_recovery_runs_once_the_agreement_starts(
        self, storefront_admin_client, lane_time, deal_state: RecurringPurchaseState,
    ):
        """Lane time is brought to the Agreement's start, and the storefront's
        delivery re-drive steps once.

        The fulfillment has converged (``Stage09a``), so what remains of
        delivery is the site's activation, the rate part's start and
        availability, which ``Stage09b``, ``Stage09c`` and ``Recurring06``
        observe. Both shipped buyers ask for a deal starting at acceptance, so
        lane time already holds the start, and the storefront's own drive of
        the delivery its commit began may finish it before the re-drive runs:
        the step's report is logged, not asserted. That the re-drive itself
        delivers a deal reaching its start is each storefront's
        delivery-recovery evidence and the VM delivery-timing scenario's.
        """
        require_state(deal_state, "provisioning_result_injected", "agreement_start",
                      "_listing_reconciled")
        reached = reach_agreement_instant(lane_time, deal_state.agreement_start)
        report = advance_storefront(storefront_admin_client, DELIVERY_RECOVERY)
        deal_state._delivery_recovered = True
        log.info("[r05] Lane at %s, the Agreement's start %s; %s re-drove %s",
                 reached.isoformat(), deal_state.agreement_start.isoformat(),
                 DELIVERY_RECOVERY, report.get("redriven"))


class Recurring06_RateStartedAfterActivation:
    def test_r06_the_rate_part_started_after_the_sites_activation(
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
        the site has activated the deal. Lane time holds one instant from the
        start on, so the two fall in the same second; each storefront's
        ``test_rate_delivery.py`` proves billing starts from the recorded
        activation. The lifecycle read names the committed transaction and
        shows the deal active, with no end and no filing.
        """
        require_state(deal_state, "negotiation_id", "settlement_id", "payer_account",
                      "settlement_status", "deal_lease", "_delivery_recovered")
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        lease = deal_state.deal_lease.refresh()
        activated = _unix_second(utc_instant(lease.get("activated_at_utc")))

        snapshot = transaction_snapshot(payments_config, deal_state.payer_account,
                                        deal_state.settlement_id)
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
        log.info("[r06] Agreement %s delivered under transaction %s: activated %s, rate part "
                 "started %s, progress %s", deal_state.negotiation_id, deal_state.settlement_id,
                 lease.get("activated_at_utc"), part["started"], read.delivery.progress)


class Recurring07_AcceptedMoneyShown:
    def test_r07_the_purchase_command_showed_the_accepted_money(
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
        log.info("[r07] Run %s showed the accepted per-period price, setup, reserve and end",
                 run.run_id)


# ===========================================================================
# The buyer's end
# ===========================================================================

class Recurring08_BuyerEnds:
    def test_r08_the_buyers_end_charges_the_started_period_and_begins_the_teardown(
        self, purchase_cli, payments_config, provisioning_client, storefront_admin_client,
        lane_time, deal_driver: RecurringPurchaseDriver, deal_state: RecurringPurchaseState,
    ):
        """The buyer's ``end`` stops the payment, and the storefront ends the delivery.

        The normal end of a rate deal, a minute into its first period: lane
        time is set there first, since it has held the start since delivery.
        The payer's stop at the payments double is accepted, then a hint makes
        the storefront read the double. The stop takes effect at once, with no
        payer notice, inside the started period, which it charges: the part is
        stopped by the payer, charging the started period's price to the payee
        and reserving nothing more
        (``producer_assertions.assert_payer_stop``). On the hint's read the
        storefront records the
        payer's stop as the deal's end, before the delivery deadline, so it
        files no seller non-delivery: the scenario does not wait for that
        deadline. That the storefront classifies the stop an entitled one is
        each storefront's application evidence (``test_lifecycle_ends.py``):
        no route reads a classification, so the lane observes what follows from
        it, an end recorded with no filing.

        One pass of the storefront loop that services the domain's deals then
        runs the cycle its timer would, which carries out a recorded end at the
        site; bare metal's hint has already carried it out, and VM's leaves it
        to that cycle. Either way the teardown begins (``begin_teardown``).
        """
        require_state(deal_state, "_accepted_money_shown", "purchase_run", "payer_account",
                      "negotiation_id", "settlement_id", "deal_lease", "lease_id",
                      "reserved_resource_id", "agreement_start")
        # The release is Stage11b's own lease cycle, not the timer's.
        assert_lease_watchdog_held(provisioning_client)
        if lane_time is not None and lane_time.injected:
            lane_time.reach(int(deal_state.agreement_start.timestamp()) + STOP_INTO_PERIOD_SECONDS,
                            fixed_by_agreement=False)
        deal_state._buyer_teardown_requested = True
        run = purchase_cli.run(deal_driver.teardown_arguments(deal_state.purchase_run.run_id))
        assert_market_run_succeeded(run, command=deal_driver.teardown_command)
        ended = json.loads(run.stdout().strip().splitlines()[-1])
        progress = EndDeliveryProgress.model_validate(ended["progress"])
        assert progress.mode == "normal_stop", progress
        assert isinstance(progress.payment, Accepted), progress
        deal_state.buyer_end = ended

        snapshot = transaction_snapshot(payments_config, deal_state.payer_account,
                                        deal_state.settlement_id)
        assert len(snapshot["parts"]) == 1, snapshot["parts"]
        assert_payer_stop(snapshot, payer=str(deal_state.payer_account),
                          period_price=PERIOD_GROSS, period_seconds=PERIOD_SECONDS)
        stop = snapshot["parts"][0]["stop"]

        read = deal_driver.lifecycle_read(deal_state.negotiation_id)
        assert read.delivery.recorded_end is not None, read.delivery
        assert read.delivery.recorded_end.cause == "payer", read.delivery
        assert read.filings == [], read.filings

        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        # The cycle files nothing for an end the payer's stop recorded.
        filings = deal_driver.lifecycle_read(deal_state.negotiation_id).filings
        assert filings == [], filings
        fulfillment_id = begin_teardown(provisioning_client, storefront_admin_client,
                                        deal_driver, deal_state)
        deal_state.teardown_fulfillment_id = fulfillment_id
        log.info("[r08] Buyer ended Agreement %s: payer's stop accepted at %s charging the "
                 "started period, end recorded at %s with no filing; lease %s releasing, "
                 "fulfillment %s tearing down", deal_state.negotiation_id,
                 stop.get("effectiveAt"), read.delivery.recorded_end.ended_at,
                 deal_state.lease_id, fulfillment_id)


class Recurring09_PayerChargedOnePeriod:
    def test_r09_the_payer_paid_one_periods_price(
        self, payments_config, deal_state: RecurringPurchaseState,
    ):
        """The started period was charged and the rest of the reservation
        returned: the payer's available balance is what ``Purchase01`` read,
        less one period's price, while nothing else spends from the account."""
        require_state(deal_state, "buyer_end", "payer_account", "payer_available_before")
        payer = str(deal_state.payer_account)
        after = payer_available(payments_config, payer)
        before = deal_state.payer_available_before
        expected = {**before, ASSET: before.get(ASSET, 0) - PERIOD_GROSS}
        assert after == expected, (
            f"payer {payer}'s available balance is {after} after the buyer's stop; it was "
            f"{before} before the purchase, and one period costs {PERIOD_GROSS} {ASSET}"
        )
        deal_state._payer_charged = True
        log.info("[r09] Payer %s available %s: one period's %s %s charged", payer, after,
                 PERIOD_GROSS, ASSET)


class Recurring10_SellerListsTheDealEnded:
    def test_r10_the_sellers_list_shows_the_deal_ended_once_released(
        self, storefront_admin_client, deal_driver: RecurringPurchaseDriver,
        deal_state: RecurringPurchaseState,
    ):
        """Once the release is proven, the seller's list shows the deal ``ended``.

        ``Stage11b`` released the lease, which the storefront heard through the
        capacity-released callback. One servicing step then reads the deal's
        authorities, saving a read of its dispute authority — for a deal nobody
        filed on, the authority's answer that it holds no record of the
        Agreement, read as no case on the premise that the storefront's
        credential is the Agreement's payee's, which no route lets it check — and
        carries out what remains of its physical end, so the list, read as the
        storefront's administrator through the typed seller client, has every
        condition of *ended* to judge from its saved views: the resource
        released, the rate part stopped, and no case open. It lists the deal
        ``ended``, with no outstanding code.
        """
        require_state(deal_state, "negotiation_id", "_payer_charged", "_teardown_job_completed")
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        deal = seller_deal(storefront_admin_client, deal_state.negotiation_id)
        assert (deal.state, deal.ending) == ("ended", []), (
            f"the seller's list shows {deal.negotiation_id} {deal.state} with "
            f"{deal.ending_reasons}: {deal}"
        )
        assert deal.parts and all(part.final_stop is not None for part in deal.parts), deal.parts
        assert deal.open_cases == [], deal
        log.info("[r10] The seller's list shows Agreement %s ended, its part stopped by %s",
                 deal.negotiation_id, [part.final_stop.cause for part in deal.parts])
