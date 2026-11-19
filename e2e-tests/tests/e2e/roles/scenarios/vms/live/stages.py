"""The live verification scenarios' own stages, which each live module subclasses.

A live module runs its lane twin's shared stages against the run's external
payments target, on wall time, until the input its lane twin gave the payments
double; it then gives the live payments authority the same input, through the
same client code (``end_by_the_buyers_stop``, ``submit_the_sellers_notice``),
reads the authority's signed transaction snapshot until the output appears,
bounded (``lane_time.poll_until``), and asserts on it through the lane twin's
shared assertion (``producer_assertions.py``). No stage runs after that
assertion: the storefront's handling of the output is the lane twin's
evidence.

Where the lane twin moves lane time or calls a double's control, the live
stage takes the input as the producer sees it: the instant a stop or a funded
boundary falls at is read from the authority's own record and reached by
waiting for it, bounded (``LaneTime.reach``, ``recorded_by_authority``); the
part is reserved ahead by the authority's own scheduler; the payer's balance is
the one the topology funded, which funds running out reads and, when it
differs from its requirement, is a blocked skip naming it.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Any, Mapping

import pytest

from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.lane_time import poll_until
from tests.e2e.roles.helpers.live_verification import (
    POLL_INTERVAL,
    LiveSettings,
    live_provenance,
)
from tests.e2e.roles.helpers.payments import payment_setting
from tests.e2e.roles.helpers.producer_assertions import (
    assert_funds_exhausted,
    assert_payee_stop,
    assert_payee_stop_pending,
    assert_payer_stop,
    assert_term_end,
)
from tests.e2e.roles.helpers.rate_servicing_stages import (
    FUNDED_PERIODS,
    RateServicingState,
    submit_the_sellers_notice,
)
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    ASSET,
    RecurringPurchaseDriver,
    end_by_the_buyers_stop,
    payer_available,
    reach_lane_instant,
    transaction_snapshot,
)

log = logging.getLogger(__name__)


@dataclass
class LiveRateState(RateServicingState):
    """What a live module's stages hand each other, beside a rate row's."""

    #: The run's live-evidence label and provenance are logged.
    _live_labelled: bool = False


def _stopped(snapshot: Mapping[str, Any]) -> bool:
    return "stop" in snapshot["parts"][0]


def _poll_snapshot(payments_config: Any, deal_state: LiveRateState, settings: LiveSettings,
                   until: Any, what: str) -> dict[str, Any]:
    """The transaction's snapshot, read with the payer's token until ``until``
    holds of it, within the run's polling bound; its one rate part checked to
    be its only part."""
    snapshot: dict[str, Any] = poll_until(
        lambda: transaction_snapshot(payments_config, deal_state.payer_account,
                                     deal_state.settlement_id),
        until, bound=settings.poll_bound, interval=POLL_INTERVAL,
        what=f"{what} of transaction {deal_state.settlement_id}",
    )
    assert len(snapshot["parts"]) == 1, snapshot["parts"]
    return snapshot


# ===========================================================================
# The run's label
# ===========================================================================

class Live00_LabelledLiveEvidence:
    def test_l00_the_run_is_labelled_live_evidence_with_its_provenance(
        self, provisioning_client, live_settings: LiveSettings, deal_state: LiveRateState,
    ):
        """The run's log carries the live-evidence label and its public-safe
        provenance: the source revision the topology runs, the deployment's
        alias for the topology, the payments authority's revision identifier,
        and the provisioning mode the provisioning service reports, beside the
        terms the deal is offered on. A run stating no provenance is a blocked
        skip naming the setting, so its observation is unproven."""
        provenance = live_provenance()
        mocked = provisioning_client.get_system_status().execution.mocked
        log.info("[l00] Live evidence: source revision %s, target %s, payments authority "
                 "revision %s, provisioning %s; period %ss, seller notice %ss, term %ss",
                 provenance.source_revision, provenance.target_alias,
                 provenance.payments_revision, "mock" if mocked else "real",
                 live_settings.period_seconds, live_settings.payee_notice_seconds,
                 live_settings.maximum_term_seconds)
        deal_state._live_labelled = True


# ===========================================================================
# The buyer's stop
# ===========================================================================

class LiveBuyerStop_PayerStopCharged:
    def test_lb_the_payer_stop_charges_the_started_period(
        self, purchase_cli, payments_config, live_settings: LiveSettings,
        deal_driver: RecurringPurchaseDriver, deal_state: LiveRateState,
    ):
        """The buyer's own ``end``, the payer's stop, as the lane's buyer end
        sends it; the payments authority records the part stopped by its payer,
        charging the started period (``producer_assertions.assert_payer_stop``).
        The stop takes effect with no payer notice, so the snapshot is polled
        only until it carries the stop."""
        require_state(deal_state, "_live_labelled", "_accepted_money_shown", "purchase_run",
                      "payer_account", "settlement_id")
        deal_state._buyer_teardown_requested = True
        deal_state.buyer_end = end_by_the_buyers_stop(purchase_cli, deal_driver, deal_state)
        snapshot = _poll_snapshot(payments_config, deal_state, live_settings, _stopped,
                                  "the payer's stop")
        terms = deal_driver.rate_terms
        assert_payer_stop(snapshot, payer=str(deal_state.payer_account),
                          period_price=terms.period_gross, period_seconds=terms.period_seconds)
        stop = snapshot["parts"][0]["stop"]
        log.info("[lb] Transaction %s: the payer's stop effective at %s, %s settled",
                 deal_state.settlement_id, stop.get("effectiveAt"),
                 stop.get("settled", {}).get("gross"))


# ===========================================================================
# Funds running out
# ===========================================================================

class LiveExhaustion00_RatePayerHoldsTheFundedPeriods:
    def test_le00_the_rate_payer_holds_exactly_the_funded_periods(
        self, payments_config, deal_driver: RecurringPurchaseDriver,
        deal_state: LiveRateState,
    ):
        """The topology funded the rate payer (``PAYMENTS.RATE_PAYER_ACCOUNT``)
        with exactly ``FUNDED_PERIODS`` periods' price at the run's period, as
        the lane row's funding control does; the scenario funds nothing. A
        payer named but holding anything else is a blocked skip naming the
        requirement, and the purchase then pays from it."""
        require_state(deal_state, "_live_labelled")
        payer = str(payment_setting("RATE_PAYER_ACCOUNT"))
        if not payer:
            pytest.skip("blocked: funds running out pays from PAYMENTS.RATE_PAYER_ACCOUNT, "
                        "which the run does not name")
        required = FUNDED_PERIODS * deal_driver.rate_terms.period_gross
        held = payer_available(payments_config, payer).get(ASSET, 0)
        if held != required:
            pytest.skip(f"blocked: funds running out needs the rate payer {payer} funded with "
                        f"exactly {required} {ASSET}, {FUNDED_PERIODS} periods at the run's "
                        f"period, and it holds {held}")
        deal_state.payer_account = payer
        log.info("[le00] Rate payer %s holds %s %s, %s periods", payer, held, ASSET,
                 FUNDED_PERIODS)


class LiveExhaustion07_FundsRunOut:
    def test_le07_the_part_stops_at_its_funded_boundary(
        self, payments_config, lane_time, live_settings: LiveSettings,
        deal_driver: RecurringPurchaseDriver, deal_state: LiveRateState,
    ):
        """The authority's scheduler reserves the part ahead as far as the
        payer's balance pays, and stops it by its terms at the funded boundary.

        The funded boundary is read from the snapshot and reached by waiting
        for it, then the snapshot is polled until the part is stopped or the
        boundary has moved on, the scheduler having reserved a further period;
        a moved boundary is reached in turn. The boundary read last before the
        stop is the one ``producer_assertions.assert_funds_exhausted`` compares
        the stop's instant with, settling ``FUNDED_PERIODS`` periods."""
        require_state(deal_state, "_live_labelled", "_accepted_money_shown", "payer_account",
                      "settlement_id")
        deal_state._deal_ending = True
        snapshot = transaction_snapshot(payments_config, deal_state.payer_account,
                                        deal_state.settlement_id)
        assert len(snapshot["parts"]) == 1, snapshot["parts"]
        boundary = snapshot.get("fundedThrough")
        while not _stopped(snapshot):
            boundary = int(snapshot["fundedThrough"])
            reach_lane_instant(lane_time, boundary, fixed_by_agreement=False,
                               recorded_by_authority=True, bound=live_settings.reach_bound)
            snapshot = _poll_snapshot(
                payments_config, deal_state, live_settings,
                lambda read, reached=boundary: (
                    _stopped(read) or int(read.get("fundedThrough") or 0) > reached),
                f"a stop at, or a reservation past, the funded boundary {boundary}",
            )
        terms = deal_driver.rate_terms
        assert_funds_exhausted(snapshot, funded_boundary=boundary, funded_periods=FUNDED_PERIODS,
                               period_price=terms.period_gross)
        deal_state.funded_boundary = boundary
        log.info("[le07] Transaction %s ran out of funds at %s", deal_state.settlement_id,
                 boundary)


# ===========================================================================
# A spot seller's preemption
# ===========================================================================

class LivePreemption07_SellerNoticeHeld:
    def test_lp07_the_sellers_notice_is_held_as_a_pending_stop(
        self, payments_config, storefront_admin_client, live_settings: LiveSettings,
        deal_state: LiveRateState,
    ):
        """The seller's notice, as the lane's preemption row sends it; the
        payments authority holds it as a pending ``payee`` stop due the
        Agreement's seller notice after its receipt
        (``producer_assertions.assert_payee_stop_pending``)."""
        require_state(deal_state, "_live_labelled", "_accepted_money_shown", "payer_account",
                      "settlement_id", "negotiation_id")
        deal_state._deal_ending = True
        submit_the_sellers_notice(storefront_admin_client, deal_state)
        snapshot = _poll_snapshot(
            payments_config, deal_state, live_settings,
            lambda read: "pendingStop" in read["parts"][0] or _stopped(read),
            "the seller's pending stop",
        )
        assert_payee_stop_pending(snapshot, payee=str(payment_setting("SELLER_ACCOUNT")),
                                  payee_notice_seconds=live_settings.payee_notice_seconds)
        deal_state.stop_effective_at = int(snapshot["parts"][0]["pendingStop"]["at"])
        log.info("[lp07] Transaction %s: the seller's stop is pending until %s",
                 deal_state.settlement_id, deal_state.stop_effective_at)


class LivePreemption08_StopTakesEffect:
    def test_lp08_the_sellers_stop_takes_effect_returning_its_period(
        self, payments_config, lane_time, live_settings: LiveSettings,
        deal_driver: RecurringPurchaseDriver, deal_state: LiveRateState,
    ):
        """The pending stop's instant, which the authority recorded, is reached
        by waiting for it, and the snapshot polled until the stop is final:
        the ``payee`` stop at the notice's receipt plus the seller notice,
        returning the period it falls in
        (``producer_assertions.assert_payee_stop``)."""
        require_state(deal_state, "stop_effective_at", "payer_account", "settlement_id")
        reach_lane_instant(lane_time, deal_state.stop_effective_at, fixed_by_agreement=False,
                           recorded_by_authority=True, bound=live_settings.reach_bound)
        snapshot = _poll_snapshot(payments_config, deal_state, live_settings, _stopped,
                                  "the seller's stop")
        terms = deal_driver.rate_terms
        assert_payee_stop(snapshot, payee=str(payment_setting("SELLER_ACCOUNT")),
                          payee_notice_seconds=live_settings.payee_notice_seconds,
                          period_price=terms.period_gross, period_seconds=terms.period_seconds)
        log.info("[lp08] Transaction %s: the seller's stop took effect at %s",
                 deal_state.settlement_id, snapshot["parts"][0]["stop"].get("effectiveAt"))


# ===========================================================================
# The term end
# ===========================================================================

class LiveTermEnd07_PartEndsAtTheAgreementsEnd:
    def test_lt07_the_part_ends_at_the_agreements_end(
        self, payments_config, lane_time, live_settings: LiveSettings,
        deal_driver: RecurringPurchaseDriver, deal_state: LiveRateState,
    ):
        """The Agreement's end, an instant the Agreement fixes, rounded up to
        the whole second the mandate ends the part at, is reached by waiting
        for it, and the snapshot polled until the part is stopped: by its terms
        at that end, returning the final partial period
        (``producer_assertions.assert_term_end``). The authority's scheduler
        has kept the part reserved through the term, which the shared buyer's
        balance pays for."""
        require_state(deal_state, "_live_labelled", "_accepted_money_shown", "payer_account",
                      "settlement_id", "agreement_end")
        end = math.ceil(deal_state.agreement_end.timestamp())
        deal_state._deal_ending = True
        reach_lane_instant(lane_time, end, fixed_by_agreement=True,
                           bound=live_settings.reach_bound)
        snapshot = _poll_snapshot(payments_config, deal_state, live_settings, _stopped,
                                  "the term end's stop")
        terms = deal_driver.rate_terms
        assert_term_end(snapshot, agreement_end=end, period_price=terms.period_gross,
                        period_seconds=terms.period_seconds)
        log.info("[lt07] Transaction %s ended at the Agreement's end %s",
                 deal_state.settlement_id, end)
