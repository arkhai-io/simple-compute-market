"""Stages of the rate servicing rows, each ending a delivered rate deal its own way.

Each row is one module per compute lane, on a deal of its own, bought through
the shipped buyer with a default buyer under a shipped preset, against a lane
whose storefront declares rate servicing for ``charged`` and ``returned``. A row
shares the recurring purchase's stages through ``Recurring07``
(``recurring_purchase_stages.py``): the listing, the purchase, delivery at the
Agreement's start and the rate part's start. It then arms the teardown gate
(``Stage09c2``) and ends the deal one way:

- **funds running out** — an on-demand deal paid by the lane's second payer,
  funded with exactly two periods' price before the purchase
  (``Exhaustion00``): lane time set past the second period's end, where the
  payments double records a ``terms`` stop at the funded boundary; the
  storefront records that end at the boundary and tears the deal down, and the
  buyer's read says a top-up cannot revive it (``Exhaustion07``,
  ``Exhaustion08``);
- **a spot seller's preemption** — the seller's notice, as ``deals preempt``
  sends it, held by the payments double as a pending stop until lane time
  reaches the request's time plus the Agreement's seller notice; the storefront
  then records the seller's stop at that instant and tears the deal down, and
  the period it stops in is returned (``Preemption07`` to ``Preemption09``);
- **the maximum term** — lane time brought to the Agreement's end, one period at
  a time so the deal stays funded; the rate part ends there with ``returned``,
  the storefront records the term end and tears the deal down, and the buyer's
  read does not call it funds running out (``MaximumTerm07``, ``MaximumTerm08``).

Each then runs the canonical teardown, ``Stage11a2`` and ``Stage11b``. Every
instant is reached by setting lane time, never by waiting; a wall-time run
reaches only the Agreement's end, and the other rows are blocked there.

No storefront route reads how it classified an end, so a row observes what
follows from the classification: the end recorded with its cause and instant,
no filing, and the teardown. That the storefront classifies a funds-running-out
stop exhaustion, a seller's stop entitled and the term end the term end is each
storefront's application evidence (``test_lifecycle_ends.py``); the buyer's
read, which classifies with the same compute-family classifier, is what a row
reads of it. Each row is lane-double evidence.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import pytest
from market_deal_lifecycle_buyer import FUNDING_STOP
from market_deal_lifecycle_client import SyncSellerLifecycleClient

from tests.e2e.roles.helpers.compute_deal import advance_storefront, assert_lease_watchdog_held
from tests.e2e.roles.helpers.domain_deal import assert_market_run_succeeded, require_state
from tests.e2e.roles.helpers.lane_doubles import payments_controls
from tests.e2e.roles.helpers.payments import payment_setting
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    ASSET,
    PERIOD_GROSS,
    PERIOD_SECONDS,
    RecurringPurchaseDriver,
    RecurringPurchaseState,
    begin_teardown,
    move_lane_time_through,
    payer_available,
    reach_lane_instant,
    transaction_snapshot,
)

log = logging.getLogger(__name__)

#: The periods the funds-running-out row's payer can pay for.
FUNDED_PERIODS = 2
#: The spot row's seller notice: the shipped spot preset's realistic notice.
SPOT_NOTICE_SECONDS = 120


@dataclass
class RateServicingState(RecurringPurchaseState):
    """What a rate servicing row's stages hand each other, beside the recurring
    purchase's."""

    #: The instant the payments double stopped funding the deal.
    funded_boundary: Optional[int] = None
    #: The seller's notice was submitted at this lane instant, and its stop
    #: takes effect at ``stop_effective_at``.
    notice_at: Optional[int] = None
    stop_effective_at: Optional[int] = None
    #: The deal's end is recorded and its teardown dispatched.
    _deal_ended: bool = False


def _the_part(payments_config: Any, deal_state: RateServicingState) -> dict[str, Any]:
    snapshot = transaction_snapshot(payments_config, deal_state.payer_account,
                                    deal_state.settlement_id)
    (part,) = snapshot["parts"]
    return part


def _recorded_end_with_no_filing(deal_driver: RecurringPurchaseDriver,
                                 deal_state: RateServicingState, *, cause: str,
                                 at: int) -> Any:
    """The storefront's lifecycle read of the deal: its end recorded with
    ``cause`` at ``at``, and nothing filed for it."""
    read = deal_driver.lifecycle_read(deal_state.negotiation_id)
    end = read.delivery.recorded_end
    assert end is not None, f"the storefront recorded no end: {read.delivery}"
    assert (end.cause, end.ended_at) == (cause, at), (
        f"the storefront recorded the end {end.cause!r} at {end.ended_at}, not {cause!r} "
        f"at {at}: {end}"
    )
    assert read.filings == [], read.filings
    return read


def _buyer_read(purchase_cli: Any, deal_driver: RecurringPurchaseDriver,
                deal_state: RateServicingState) -> dict[str, Any]:
    """The buyer's own read of its run's deal, as its ``delivery`` command prints it."""
    run = purchase_cli.run(deal_driver.read_arguments(deal_state.purchase_run.run_id))
    assert_market_run_succeeded(run, command="the buyer's delivery read")
    return json.loads(run.stdout().strip().splitlines()[-1])


# ===========================================================================
# Funds running out
# ===========================================================================

class Exhaustion00_PayerFundedForTwoPeriods:
    def test_e00_the_rate_payer_holds_exactly_two_periods(
        self, payments_config, deal_state: RateServicingState,
    ):
        """The lane's second payer is funded with exactly two periods' price.

        It starts with nothing, and only this row funds it, through the
        payments double's funding control; a run before this one on the same
        stack leaves it no more than that, since a deal it paid for either ran
        the balance out or was stopped, returning what it had not earned. The
        purchase then pays from it (``Purchase01`` reads it as the payer).
        """
        payer = str(payment_setting("RATE_PAYER_ACCOUNT"))
        assert payer, "PAYMENTS.RATE_PAYER_ACCOUNT is required for funds running out"
        funded = FUNDED_PERIODS * PERIOD_GROSS
        held = payer_available(payments_config, payer).get(ASSET, 0)
        assert held <= funded, (
            f"the rate payer {payer} already holds {held} {ASSET}, more than the "
            f"{funded} this row funds it to"
        )
        if held < funded:
            with payments_controls() as controls:
                controls.fund(payer, funded - held)
        assert payer_available(payments_config, payer) == {ASSET: funded}
        deal_state.payer_account = payer
        log.info("[e00] Rate payer %s funded to %s %s, %s periods", payer, funded, ASSET,
                 FUNDED_PERIODS)


class Exhaustion07_FundsRunOut:
    def test_e07_the_deal_ends_at_its_funded_boundary(
        self, payments_config, provisioning_client, storefront_admin_client, lane_time,
        deal_driver: RecurringPurchaseDriver, deal_state: RateServicingState,
    ):
        """Lane time past the second period's end stops the deal at its funded boundary.

        The payer's balance paid for two periods from the rate part's start,
        so the payments double funds the deal through their end and no
        further. Lane time is set one second past that boundary and the
        storefront's servicing steps once: the double records a ``terms`` stop
        effective at the boundary, charging both periods, and the storefront
        records that stop as the deal's end at the boundary, files nothing, and
        carries the end out at the site (``begin_teardown``).
        """
        require_state(deal_state, "_accepted_money_shown", "payer_account", "settlement_id",
                      "negotiation_id", "deal_lease", "_teardown_gate_armed")
        assert_lease_watchdog_held(provisioning_client)
        part = _the_part(payments_config, deal_state)
        started = int(part["started"])
        boundary = int(part["rate"]["reservedThrough"])
        assert boundary == started + FUNDED_PERIODS * PERIOD_SECONDS, (
            f"the double funds the deal through {boundary}, not {FUNDED_PERIODS} periods "
            f"from its start at {started}: {part}"
        )
        deal_state._deal_ending = True
        reach_lane_instant(lane_time, boundary + 1, fixed_by_agreement=False)
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)

        part = _the_part(payments_config, deal_state)
        stop = part.get("stop") or {}
        assert (stop.get("cause"), stop.get("effectiveAt")) == ("terms", boundary), part
        assert part.get("reserved", "0") == "0", part
        assert int(part["held"]) + int(part["released"]) == FUNDED_PERIODS * PERIOD_GROSS, part
        _recorded_end_with_no_filing(deal_driver, deal_state, cause="terms", at=boundary)
        fulfillment_id = begin_teardown(provisioning_client, storefront_admin_client,
                                        deal_driver, deal_state)
        deal_state.teardown_fulfillment_id = fulfillment_id
        deal_state.funded_boundary = boundary
        deal_state._deal_ended = True
        log.info("[e07] Agreement %s ran out of funds at %s: terms stop recorded with no "
                 "filing, fulfillment %s tearing down", deal_state.negotiation_id, boundary,
                 fulfillment_id)


class Exhaustion08_BuyerToldANewDealIsNeeded:
    def test_e08_the_buyers_read_says_a_top_up_cannot_revive_the_deal(
        self, purchase_cli, payments_config, deal_driver: RecurringPurchaseDriver,
        deal_state: RateServicingState,
    ):
        """The buyer's read of its deal says why the stop is final.

        The ``delivery`` read classifies the part's ``terms`` stop, effective
        before the Agreement's end, as funds running out, and says the balance
        could not reserve the next period, that a top-up cannot revive the
        deal, and that a new deal is needed. The payer holds nothing more.
        """
        require_state(deal_state, "funded_boundary", "purchase_run", "payer_account",
                      "_teardown_job_completed")
        read = _buyer_read(purchase_cli, deal_driver, deal_state)
        assert read.get("funding_stop") == FUNDING_STOP, read
        assert payer_available(payments_config, deal_state.payer_account).get(ASSET, 0) == 0
        deal_state._payer_charged = True
        log.info("[e08] The buyer's read of Agreement %s says: %s", deal_state.negotiation_id,
                 read["funding_stop"])


# ===========================================================================
# A spot seller's preemption
# ===========================================================================

class Preemption07_SellerNoticeHeld:
    def test_p07_the_sellers_notice_is_held_as_a_pending_stop(
        self, payments_config, provisioning_client, storefront_admin_client, lane_time,
        deal_driver: RecurringPurchaseDriver, deal_state: RateServicingState,
    ):
        """The seller preempts the spot deal with notice, which the double holds.

        The storefront's administrator submits the seller's notice through the
        typed seller lifecycle client, the call ``deals preempt`` makes, with no
        instant asked: the payments authority enforces the Agreement's seller
        notice. The double accepts it as a pending ``payee`` stop effective that
        notice after the lane instant, and a servicing step before then records
        no end: the deal is still delivered.
        """
        require_state(deal_state, "_accepted_money_shown", "payer_account", "settlement_id",
                      "negotiation_id", "deal_lease", "_teardown_gate_armed")
        assert_lease_watchdog_held(provisioning_client)
        if lane_time is None or not lane_time.injected:
            pytest.skip("blocked: the seller's notice takes effect at an instant only "
                        "injected lane time reaches")
        notice_at = lane_time.now()
        deal_state._deal_ending = True
        answer = SyncSellerLifecycleClient(storefront_admin_client).notice(
            deal_state.negotiation_id, operation_key=f"preempt-{deal_state.negotiation_id}",
        )
        assert answer.outcome.status == "accepted", answer
        effective = notice_at + SPOT_NOTICE_SECONDS

        part = _the_part(payments_config, deal_state)
        pending = part.get("pendingStop") or {}
        assert (pending.get("cause"), pending.get("at")) == ("payee", effective), part
        assert part.get("stop") is None, part
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        read = deal_driver.lifecycle_read(deal_state.negotiation_id)
        assert read.delivery.recorded_end is None, read.delivery
        assert read.delivery.progress == "active", read.delivery
        deal_state.notice_at = notice_at
        deal_state.stop_effective_at = effective
        log.info("[p07] Seller's notice on Agreement %s at %s held until %s",
                 deal_state.negotiation_id, notice_at, effective)


class Preemption08_StopTakesEffect:
    def test_p08_the_sellers_stop_ends_the_deal_at_its_effective_time(
        self, payments_config, provisioning_client, storefront_admin_client, lane_time,
        deal_driver: RecurringPurchaseDriver, deal_state: RateServicingState,
    ):
        """At the request's time plus the seller notice the stop takes effect.

        Lane time is set to that instant and the storefront's servicing steps
        once: the double records the ``payee`` stop effective then, returning
        the period it falls in, and the storefront records the seller's stop as
        the deal's end at that instant, files nothing, and carries the end out
        at the site (``begin_teardown``).
        """
        require_state(deal_state, "stop_effective_at", "payer_account", "settlement_id",
                      "deal_lease")
        effective = deal_state.stop_effective_at
        reach_lane_instant(lane_time, effective, fixed_by_agreement=False)
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)

        part = _the_part(payments_config, deal_state)
        stop = part.get("stop") or {}
        assert (stop.get("cause"), stop.get("effectiveAt"), stop.get("partialPeriod")) == (
            "payee", effective, "returned"), part
        assert part.get("reserved", "0") == "0", part
        _recorded_end_with_no_filing(deal_driver, deal_state, cause="payee", at=effective)
        fulfillment_id = begin_teardown(provisioning_client, storefront_admin_client,
                                        deal_driver, deal_state)
        deal_state.teardown_fulfillment_id = fulfillment_id
        deal_state._deal_ended = True
        log.info("[p08] Seller's stop on Agreement %s took effect at %s: end recorded with no "
                 "filing, fulfillment %s tearing down", deal_state.negotiation_id, effective,
                 fulfillment_id)


class Preemption09_UnstartedPeriodReturned:
    def test_p09_the_payer_is_returned_what_the_deal_had_not_earned(
        self, payments_config, deal_state: RateServicingState,
    ):
        """The payer paid only what the deal earned before the seller's stop.

        The stop returns the period it falls in, and the periods reserved ahead
        were never entered, so the payer's available balance is what
        ``Purchase01`` read less what the part kept for the payee, its held and
        released amounts, while nothing else spends from the account.
        """
        require_state(deal_state, "_deal_ended", "payer_account", "payer_available_before",
                      "_teardown_job_completed")
        part = _the_part(payments_config, deal_state)
        kept = int(part["held"]) + int(part["released"])
        before = deal_state.payer_available_before
        after = payer_available(payments_config, deal_state.payer_account)
        assert after == {**before, ASSET: before.get(ASSET, 0) - kept}, (
            f"payer {deal_state.payer_account}'s available balance is {after}; it was "
            f"{before} before the purchase, and the part kept {kept} {ASSET}"
        )
        deal_state._payer_charged = True
        log.info("[p09] Payer %s available %s after the seller's stop; the part kept %s %s",
                 deal_state.payer_account, after, kept, ASSET)


# ===========================================================================
# The maximum term
# ===========================================================================

class MaximumTerm07_TermEnds:
    def test_m07_the_rate_part_ends_at_the_agreements_end(
        self, payments_config, provisioning_client, storefront_admin_client, lane_time,
        deal_driver: RecurringPurchaseDriver, deal_state: RateServicingState,
    ):
        """Lane time at the Agreement's end ends the rate part with ``returned``.

        Lane time is brought to the Agreement's end a period at a time, the
        transaction read at each instant as the storefront's own reads would,
        so the double reserves each next period from the payer's balance and
        the deal stays funded. At the end the storefront's servicing steps
        once: the double records the part's ``terms`` stop at the Agreement's
        end, returning a final partial period, and the storefront records the
        term end at that instant, files nothing, and carries the end out at
        the site (``begin_teardown``).
        """
        require_state(deal_state, "_accepted_money_shown", "payer_account", "settlement_id",
                      "negotiation_id", "deal_lease", "agreement_end", "_teardown_gate_armed")
        assert_lease_watchdog_held(provisioning_client)
        end = int(deal_state.agreement_end.timestamp())
        deal_state._deal_ending = True
        move_lane_time_through(lane_time, end,
                               read=lambda: _the_part(payments_config, deal_state))
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)

        part = _the_part(payments_config, deal_state)
        stop = part.get("stop") or {}
        assert (stop.get("cause"), stop.get("effectiveAt"), stop.get("partialPeriod")) == (
            "terms", end, "returned"), part
        assert part.get("reserved", "0") == "0", part
        _recorded_end_with_no_filing(deal_driver, deal_state, cause="terms", at=end)
        fulfillment_id = begin_teardown(provisioning_client, storefront_admin_client,
                                        deal_driver, deal_state)
        deal_state.teardown_fulfillment_id = fulfillment_id
        deal_state._deal_ended = True
        log.info("[m07] Agreement %s reached its end at %s: terms stop recorded with no "
                 "filing, fulfillment %s tearing down", deal_state.negotiation_id, end,
                 fulfillment_id)


class MaximumTerm08_NotFundsRunningOut:
    def test_m08_the_buyers_read_does_not_call_the_term_end_funds_running_out(
        self, purchase_cli, deal_driver: RecurringPurchaseDriver,
        deal_state: RateServicingState,
    ):
        """The buyer's read classifies the stop at the Agreement's end as the
        term end, so it says nothing of funds running out."""
        require_state(deal_state, "_deal_ended", "purchase_run", "_teardown_job_completed")
        read = _buyer_read(purchase_cli, deal_driver, deal_state)
        assert read.get("funding_stop") is None, read
        deal_state._payer_charged = True
        log.info("[m08] The buyer's read of Agreement %s names no funding stop",
                 deal_state.negotiation_id)
