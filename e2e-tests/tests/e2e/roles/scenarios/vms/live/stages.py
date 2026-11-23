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
buyer's stop waits, as its twin's lane time moves, until a minute after the
Agreement's start, an instant the scenario's own data fixes; the
part is reserved ahead by the authority's own scheduler; the payer's balance is
the one the topology funded, which funds running out reads and, when it
differs from its requirement, is a blocked skip naming it.

A dispute module runs its lane twin's shared stages the same way, waits on wall
time until the payments authority holds the part's first period's earnings
(``LiveDispute07``), and files as its lane twin does, through the same client
code (``rate_dispute/stages.py``'s functions): the storefront's own filing as
the payee, or the buyer's filing and the storefront's contest. It then polls
the hosted dispute authority's signed record, read as the buyer through the
mediation kit's public client, until the case is closed, bounded
(``live_verification.await_case_closed``), and asserts on the record and the
payments snapshot through the lane twin's shared dispute assertion. The ruling
is the authority's own: a mechanical ruling of the payee's filing, which it
documents, or, for the contested case, a person's decision, which reaches the
scenario only through a ruling policy the topology applies. No stage calls an
operator endpoint, and a topology applying no policy leaves the contested
case's ruling unproven, naming the requirement; a storefront holding no
dispute credential, which its refusal of the seller's filing or its lifecycle
read before the contest shows, leaves what needs it unproven the same way.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping

import injected_time
import pytest
from market_deal_lifecycle_contracts.models import LifecycleRead

from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.lane_time import poll_until
from tests.e2e.roles.helpers.live_verification import (
    POLL_INTERVAL,
    LiveSettings,
    Provenance,
    await_case_closed,
)
from tests.e2e.roles.helpers.mediation import (
    MediationTarget,
    pinned_authority_difference,
    read_record,
)
from tests.e2e.roles.helpers.payments import payment_setting
from tests.e2e.roles.helpers.producer_assertions import (
    assert_contested_case_ruled,
    assert_funds_exhausted,
    assert_payee_filing_ruled,
    assert_payee_stop,
    assert_payee_stop_pending,
    assert_payer_stop,
    assert_term_end,
)
from tests.e2e.roles.helpers.rate_servicing_stages import (
    FUNDED_PERIODS,
    submit_the_sellers_notice,
)
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    ASSET,
    STOP_INTO_PERIOD_SECONDS,
    RecurringPurchaseDriver,
    end_by_the_buyers_stop,
    reach_lane_instant,
    transaction_snapshot,
)
from tests.e2e.roles.scenarios.vms.rate_dispute.stages import (
    RateDisputeState,
    contest_as_respondent,
    end_delivery_as_a_failure,
    file_the_buyers_claim,
    filed_as_payee,
    premature_stop_penalty,
)

log = logging.getLogger(__name__)


#: The observations the live dispute modules make: the seller's filing, ruled
#: as the dispute authority documents a mechanical ruling; and the buyer's
#: contested case in three, its filing, the storefront's contest of it, and the
#: ruling a policy the topology applies makes, which a topology applying none
#: leaves unproven while the other two stand.
SELLERS_FILING = "the seller's filing"
BUYERS_FILING = "the buyer's filing"
STOREFRONTS_CONTEST = "the storefront's contest"
POLICY_RULING = "the policy's ruling"
#: The repair reason the storefront's seller lifecycle refuses a filing with
#: when it holds no dispute credential for the Agreement's authority, and
#: reports as the deal's authority outcome on every lifecycle read of it.
MISSING_CREDENTIAL_REPAIR = "repair required: Agreement authority credential is missing"
#: What a topology lacks when the storefront holds no dispute credential.
CREDENTIAL_REQUIREMENT = (
    "the storefront holds no dispute credential for the Agreement's dispute authority, which "
    "the topology provides (e2e-tests/README.md, \"Live verification\")"
)
#: What a topology lacks when no ruling of the buyer's contested case appears.
RULING_POLICY_REQUIREMENT = (
    "the topology applied no ruling policy to it: the buyer's contested case needs a policy "
    "that rules a contested delivery_end with a stop returning its period and a reverse "
    "(e2e-tests/README.md, \"Live verification\")"
)


@dataclass
class LiveRateState(RateDisputeState):
    """What a live module's stages hand each other, beside a rate row's and,
    for a module filing a case, a rate-dispute row's."""

    #: The run's live-evidence label and provenance are logged.
    _live_labelled: bool = False
    #: The payments authority holds the part's first period's earnings.
    _first_period_held: bool = False
    #: The storefront contested the buyer's case on the record.
    _case_contested: bool = False


def storefront_credential_missing(read: LifecycleRead) -> bool:
    """Whether the storefront's lifecycle read of a deal reports that it holds
    no dispute credential for the Agreement's authority: the deal's authority
    outcome refused with ``MISSING_CREDENTIAL_REPAIR``, which the storefront's
    seller lifecycle reports on every read of such a deal, before anything is
    filed."""
    outcome = read.authority.outcome
    return outcome.status == "rejected" and outcome.reason == MISSING_CREDENTIAL_REPAIR


def _stopped(snapshot: Mapping[str, Any]) -> bool:
    return "stop" in snapshot["parts"][0]


def _periods_earned(snapshot: Mapping[str, Any]) -> int:
    return int(snapshot["parts"][0].get("rate", {}).get("periodsEarned", 0))


def _funded_through(snapshot: Mapping[str, Any]) -> int:
    """The transaction's funded boundary: its one rate part's
    ``reservedThrough``. The snapshot's ``fundedThrough`` is the earliest
    boundary of its parts still running, so equal to it while the part runs
    and absent once it has stopped; the part's own reservation is reported
    either way."""
    through = snapshot["parts"][0].get("rate", {}).get("reservedThrough")
    assert through is not None, f"the rate part reports no reservation: {snapshot['parts']}"
    return int(through)


def _poll_snapshot(payments_config: Any, deal_state: LiveRateState, settings: LiveSettings,
                   until: Any, what: str, *, bound: timedelta | None = None) -> dict[str, Any]:
    """The transaction's snapshot, read with the payer's token until ``until``
    holds of it, within ``bound``, the run's polling bound unless given; its
    one rate part checked to be its only part."""
    snapshot: dict[str, Any] = poll_until(
        lambda: transaction_snapshot(payments_config, deal_state.payer_account,
                                     deal_state.settlement_id),
        until, bound=settings.poll_bound if bound is None else bound, interval=POLL_INTERVAL,
        what=f"{what} of transaction {deal_state.settlement_id}",
    )
    assert len(snapshot["parts"]) == 1, snapshot["parts"]
    return snapshot


# ===========================================================================
# The run's label
# ===========================================================================

class Live00_LabelledLiveEvidence:
    def test_l00_the_run_is_labelled_live_evidence_with_its_provenance(
        self, provisioning_client, live_settings: LiveSettings, live_provenance: Provenance,
        deal_state: LiveRateState,
    ):
        """The run's log carries the live-evidence label and its public-safe
        provenance: the source revision the topology runs, the deployment's
        alias for the topology, the payments authority's revision identifier,
        for a module filing a case the mediation authority's, and the
        provisioning mode the provisioning service reports, beside the terms
        the deal is offered on. A run stating no provenance is a blocked
        skip naming the setting at the ``live_provenance`` fixture, which the
        module takes before any stage, so its observation is unproven."""
        provenance = live_provenance
        mocked = provisioning_client.get_system_status().execution.mocked
        mediation = ("" if provenance.mediation_revision is None
                     else f", mediation authority revision {provenance.mediation_revision}")
        log.info("[l00] Live evidence: source revision %s, target %s, payments authority "
                 "revision %s%s, provisioning %s; period %ss, seller notice %ss, term %ss",
                 provenance.source_revision, provenance.target_alias,
                 provenance.payments_revision, mediation, "mock" if mocked else "real",
                 live_settings.period_seconds, live_settings.payee_notice_seconds,
                 live_settings.maximum_term_seconds)
        deal_state._live_labelled = True


# ===========================================================================
# The buyer's stop
# ===========================================================================

class LiveBuyerStop_PayerStopCharged:
    def test_lb_the_payer_stop_charges_the_started_period(
        self, purchase_cli, payments_config, lane_time, live_settings: LiveSettings,
        deal_driver: RecurringPurchaseDriver, deal_state: LiveRateState,
    ):
        """The buyer's own ``end``, the payer's stop, as the lane's buyer end
        sends it; the payments authority records the part stopped by its payer,
        charging the started period (``producer_assertions.assert_payer_stop``).

        As its lane twin does, the stop is sent no earlier than
        ``STOP_INTO_PERIOD_SECONDS`` after the Agreement's start, an instant
        the scenario's own data fixes, reached by waiting for it, or at once
        when the earlier stages took longer, so a fast run's stop does not
        fall in the second the part started. A stop that still does — a part
        started that late — has no started period to charge, and the
        assertion fails it rather than passing on nothing settled. The instant
        must fall before the Agreement's end, or the term end stops the part
        first.
        The stop takes effect with no payer notice, so the snapshot is polled
        only until it carries the stop."""
        require_state(deal_state, "_live_labelled", "_accepted_money_shown", "purchase_run",
                      "payer_account", "settlement_id", "agreement_start", "agreement_end")
        into_period = int(deal_state.agreement_start.timestamp()) + STOP_INTO_PERIOD_SECONDS
        assert into_period < int(deal_state.agreement_end.timestamp()), (
            f"the buyer's stop is sent {STOP_INTO_PERIOD_SECONDS} seconds into the term, at or "
            "past the Agreement's end: LIVE.MAXIMUM_TERM_SECONDS must be longer")
        reach_lane_instant(lane_time, into_period, fixed_by_agreement=True,
                           bound=live_settings.reach_bound)
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
        self, funded_rate_payer: str, deal_driver: RecurringPurchaseDriver,
        deal_state: LiveRateState,
    ):
        """The topology funded the rate payer (``PAYMENTS.RATE_PAYER_ACCOUNT``)
        with exactly ``FUNDED_PERIODS`` periods' price at the run's period, as
        the lane row's funding control does, and the purchase pays from it;
        the scenario funds nothing. The ``funded_rate_payer`` fixture, which
        the module takes before any stage, read the balance: any other is a
        blocked skip naming the requirement before anything is bought."""
        require_state(deal_state, "_live_labelled")
        deal_state.payer_account = funded_rate_payer
        log.info("[le00] Rate payer %s holds %s %s, %s periods", funded_rate_payer,
                 FUNDED_PERIODS * deal_driver.rate_terms.period_gross, ASSET, FUNDED_PERIODS)


class LiveExhaustion07_FundsRunOut:
    def test_le07_the_part_stops_at_its_funded_boundary(
        self, payments_config, lane_time, live_settings: LiveSettings,
        deal_driver: RecurringPurchaseDriver, deal_state: LiveRateState,
    ):
        """The authority's scheduler reserves the part ahead as far as the
        payer's balance pays, and stops it by its terms at the funded boundary.

        The funded boundary is read from the snapshot (``_funded_through``)
        and reached by waiting for it, then the snapshot is polled until the
        part is stopped or the boundary has moved on, the scheduler having
        reserved a further period; a moved boundary is reached in turn. The
        boundary read last before the stop, or a later one the stopping read
        reports, is the one ``producer_assertions.assert_funds_exhausted``
        compares the stop's instant with, settling ``FUNDED_PERIODS`` periods;
        it lies before the Agreement's end, or the stop is a term end's."""
        require_state(deal_state, "_live_labelled", "_accepted_money_shown", "payer_account",
                      "settlement_id", "agreement_end")
        deal_state._deal_ending = True
        snapshot = transaction_snapshot(payments_config, deal_state.payer_account,
                                        deal_state.settlement_id)
        assert len(snapshot["parts"]) == 1, snapshot["parts"]
        boundary = _funded_through(snapshot)
        while not _stopped(snapshot):
            boundary = _funded_through(snapshot)
            reach_lane_instant(lane_time, boundary, fixed_by_agreement=False,
                               recorded_by_authority=True, bound=live_settings.reach_bound)
            snapshot = _poll_snapshot(
                payments_config, deal_state, live_settings,
                lambda read, reached=boundary: (
                    _stopped(read) or _funded_through(read) > reached),
                f"a stop at, or a reservation past, the funded boundary {boundary}",
            )
        # The read that shows the stop may also show a reservation the
        # scheduler made since the boundary last reached, and then the stop
        # falls at that one; a reservation reported shorter than the boundary
        # reached is not taken, so a stop before it differs from the expectation.
        boundary = max(boundary, _funded_through(snapshot))
        end = math.ceil(deal_state.agreement_end.timestamp())
        assert boundary < end, (
            f"the part was funded through {boundary}, the Agreement's end {end} or past it: "
            "its stop is the term end's, not funds running out")
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
        (``producer_assertions.assert_payee_stop_pending``). A notice that
        would fall due at or past the Agreement's end meets the term end
        first, so the run's notice is held to the term left before it is
        sent: one too long fails naming the setting the run owes."""
        require_state(deal_state, "_live_labelled", "_accepted_money_shown", "payer_account",
                      "settlement_id", "negotiation_id", "agreement_end")
        left = int(deal_state.agreement_end.timestamp()) - injected_time.now()
        assert live_settings.payee_notice_seconds < left, (
            f"LIVE.PAYEE_NOTICE_SECONDS is {live_settings.payee_notice_seconds}, and only {left} "
            "seconds of the term are left once the deal is delivered: the notice would meet "
            "the term end")
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


# ===========================================================================
# The dispute modules: both
# ===========================================================================

def _ruled_output(payments_config: Any, mediation_target: MediationTarget,
                  settings: LiveSettings, deal_state: LiveRateState, *,
                  ruling_requirement: str | None = None,
                  ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The dispute authority's record of the deal, read as the buyer through
    the mediation kit's public client until the case is closed, within the
    run's polling bound (``await_case_closed``), then the payments snapshot
    the ruling's effects moved, read by the payer: a closed case's effects
    were each applied at payments, as its closed entry records. Both are
    logged, with the identifiers they are read by."""
    record = await_case_closed(
        lambda: read_record(mediation_target, negotiation_id=deal_state.negotiation_id,
                            transaction=deal_state.settlement_id, agreement=deal_state.agreement),
        case_ref=str(deal_state.case_ref), bound=settings.poll_bound,
        ruling_requirement=ruling_requirement,
    )
    snapshot = transaction_snapshot(payments_config, deal_state.payer_account,
                                    deal_state.settlement_id)
    assert len(snapshot["parts"]) == 1, snapshot["parts"]
    log.info("Producer output for Agreement %s, transaction %s, case %s: %s",
             deal_state.negotiation_id, deal_state.settlement_id, deal_state.case_ref,
             json.dumps({"record": record, "snapshot": snapshot}, sort_keys=True))
    return record, snapshot


class LiveDispute07_FirstPeriodHeld:
    def test_ld07_the_payments_authority_holds_the_first_periods_earnings(
        self, payments_config, mediation_target, live_settings: LiveSettings,
        deal_driver: RecurringPurchaseDriver, deal_state: LiveRateState,
    ):
        """The Agreement pins the run's dispute authority, the one the buyer's
        registry recommends; an Agreement pinning another is the topology's
        unmet requirement, a blocked skip naming both, since the harness reads
        no record of another authority.

        The payments authority earns the part's first period on its own
        schedule, an output of the rate the scenario's purchase started, so
        the snapshot is polled until it shows the period earned and its
        earnings held, or the part stopped. The bound is the time left until
        the first period ends — the start the authority recorded plus the
        Agreement's period, which bounds the wait and is not reached as an
        instant — and the run's polling bound after it. The part must still
        run: a case filed after it has earnings for a ruling to reverse and
        penalise, as the lane twin's has a minute into the second period."""
        require_state(deal_state, "_live_labelled", "_accepted_money_shown",
                      "_teardown_gate_armed", "payer_account", "settlement_id", "agreement")
        difference = pinned_authority_difference(mediation_target, deal_state.agreement)
        if difference is not None:
            pytest.skip(f"blocked: {difference}; the buyer's registry recommends the run's "
                        "dispute authority (e2e-tests/README.md, \"Live verification\")")
        snapshot = transaction_snapshot(payments_config, deal_state.payer_account,
                                        deal_state.settlement_id)
        assert len(snapshot["parts"]) == 1, snapshot["parts"]
        first_period_end =(int(snapshot["parts"][0]["started"])
                            + deal_driver.rate_terms.period_seconds)
        left = timedelta(seconds=max(0, first_period_end - injected_time.now()))
        snapshot = _poll_snapshot(
            payments_config, deal_state, live_settings,
            lambda read: _stopped(read) or (_periods_earned(read) >= 1
                                            and int(read["parts"][0]["held"]) > 0),
            "the first period's earnings held", bound=left + live_settings.poll_bound,
        )
        part = snapshot["parts"][0]
        assert part.get("stop") is None, part
        deal_state._first_period_held = True
        log.info("[ld07] Transaction %s after %s: %s periods earned, %s held",
                 deal_state.settlement_id, first_period_end, _periods_earned(snapshot),
                 part["held"])


# ===========================================================================
# The seller's filing
# ===========================================================================

class LiveSellerFiling09_StorefrontFilesAsPayee:
    def test_ls09_the_administrators_end_files_as_the_payee(
        self, storefront_admin_client, deal_state: LiveRateState,
    ):
        """The storefront's administrator ends the delivery as a failure, as
        the lane twin's does: the storefront records the operator's end, files
        ``delivery_end`` as the payee with the hosted dispute authority, which
        accepts the filing, and begins the teardown, held at its gate
        (``rate_dispute.stages.end_delivery_as_a_failure``,
        ``filed_as_payee``). The end the storefront recorded is the one its
        filing claims. A storefront holding no dispute credential for the
        Agreement's authority refuses the filing, naming its repair; that is
        the topology's unmet requirement, a blocked skip naming it."""
        require_state(deal_state, "_first_period_held", "negotiation_id", "settlement_id")
        deal_state._deal_ending = True
        ended = end_delivery_as_a_failure(storefront_admin_client, deal_state)
        if (ended.get("lifecycle_outcome") or {}).get("reason") == MISSING_CREDENTIAL_REPAIR:
            pytest.skip(f"blocked: {CREDENTIAL_REQUIREMENT}")
        deal_state.delivery_end_at, deal_state.case_ref = filed_as_payee(ended)
        log.info("[ls09] Operator end of Agreement %s at %s filed as case %s",
                 deal_state.negotiation_id, deal_state.delivery_end_at, deal_state.case_ref)


class LiveSellerFiling10_MechanicalRulingRead:
    def test_ls10_the_authoritys_mechanical_ruling_matches_the_lane_twins(
        self, payments_config, mediation_target, live_settings: LiveSettings,
        deal_driver: RecurringPurchaseDriver, deal_state: LiveRateState,
    ):
        """The hosted dispute authority rules the payee's filing mechanically,
        on its own schedule, as it documents; the scenario calls no operator
        endpoint. Its record is polled until the case is closed, and the record
        and snapshot are held to the lane twin's assertion
        (``producer_assertions.assert_payee_filing_ruled``): the filing and its
        protection of the part, the ruling's basis, delivery end and effects
        each applied, the authority's stop returning its period with its
        reversal of any earnings since the end, the Agreement's penalty capped
        at what the part then held, the extension lifted, and the case closed.
        The claimed end is the one the storefront recorded, the period the
        run's. No stage runs after it."""
        require_state(deal_state, "case_ref", "delivery_end_at", "agreement", "negotiation_id",
                      "settlement_id", "payer_account")
        record, snapshot = _ruled_output(payments_config, mediation_target, live_settings,
                                         deal_state)
        terms = deal_driver.rate_terms
        assert_payee_filing_ruled(
            record, snapshot, case_ref=str(deal_state.case_ref),
            payee=str(payment_setting("SELLER_ACCOUNT")), claimed_end=deal_state.delivery_end_at,
            authority=mediation_target.account,
            penalty=premature_stop_penalty(deal_state.agreement),
            period_price=terms.period_gross, period_seconds=terms.period_seconds,
        )
        deal_state._ruling_applied = True
        log.info("[ls10] Case %s ruled: stopped at %s, reversed %s, case closed",
                 deal_state.case_ref, snapshot["parts"][0]["stop"].get("effectiveAt"),
                 snapshot["parts"][0]["reversed"])


# ===========================================================================
# The buyer's contested case
# ===========================================================================

class LiveContestedCase08_BuyerFiles:
    def test_lc08_the_buyers_filing_is_accepted_and_the_part_held(
        self, mediation_target, buyer_evidence: Path, deal_state: LiveRateState,
    ):
        """The buyer files ``delivery_end`` through the mediation kit's dispute
        adapter, as the lane twin's does, claiming the end now; the hosted
        dispute authority accepts the filing and holds the part
        (``rate_dispute.stages.file_the_buyers_claim``)."""
        require_state(deal_state, "_first_period_held", "negotiation_id", "settlement_id",
                      "agreement")
        deal_state.delivery_end_at = injected_time.now()
        deal_state.case_ref = file_the_buyers_claim(mediation_target, buyer_evidence, deal_state)
        log.info("[lc08] The buyer filed case %s on Agreement %s, claiming the end at %s",
                 deal_state.case_ref, deal_state.negotiation_id, deal_state.delivery_end_at)


class LiveContestedCase09_StorefrontContests:
    #: The buyer's filing stands without the contest.
    observations = (STOREFRONTS_CONTEST, POLICY_RULING)

    def test_lc09_a_servicing_step_contests_the_case_as_respondent(
        self, storefront_admin_client, deal_driver: RecurringPurchaseDriver,
        deal_state: LiveRateState,
    ):
        """One servicing step: the storefront's respondent discovery finds the
        case on the hosted authority's respondent listing and contests it on
        the record, as the lane twin's does
        (``rate_dispute.stages.contest_as_respondent``).

        The storefront's lifecycle read of the deal comes first: a storefront
        holding no dispute credential for the Agreement's authority cannot
        contest, and its read says so (``storefront_credential_missing``);
        that is the topology's unmet requirement, a blocked skip naming it, so
        the contest and the ruling are unproven while the buyer's filing
        stands."""
        require_state(deal_state, "case_ref", "negotiation_id")
        if storefront_credential_missing(deal_driver.lifecycle_read(deal_state.negotiation_id)):
            pytest.skip(f"blocked: {CREDENTIAL_REQUIREMENT}")
        contest_as_respondent(storefront_admin_client, deal_driver, deal_state)
        deal_state._case_contested = True
        log.info("[lc09] The storefront contested case %s", deal_state.case_ref)


class LiveContestedCase10_PolicyRuling:
    #: A topology applying no ruling policy leaves this observation alone
    #: unproven.
    observations = (POLICY_RULING,)

    def test_lc10_the_policys_ruling_matches_the_lane_twins(
        self, payments_config, mediation_target, live_settings: LiveSettings,
        deal_driver: RecurringPurchaseDriver, deal_state: LiveRateState,
    ):
        """A contested case is a person's decision, which reaches the scenario
        only through the ruling policy the topology applies; the scenario
        calls no operator endpoint. The record is polled until the case is
        closed: with no ruling of it by the run's polling bound, the stage is a
        blocked skip naming the policy requirement, so this observation is
        unproven while the filing and the contest stand. A ruling is held to
        the lane twin's assertion
        (``producer_assertions.assert_contested_case_ruled``): the filing and
        its protection, the contest before the ruling, the ruling's effects
        each applied, the authority's stop returning its period with its
        reversal of any earnings since the ruled end, payments reversing the
        reverse effect's amount, the extension lifted, and the case closed;
        the ruling's delivery end and reverse amount are the policy's, so not
        compared. No stage runs after it."""
        require_state(deal_state, "_case_contested", "case_ref", "delivery_end_at", "agreement",
                      "negotiation_id", "settlement_id", "payer_account")
        record, snapshot = _ruled_output(payments_config, mediation_target, live_settings,
                                         deal_state, ruling_requirement=RULING_POLICY_REQUIREMENT)
        # A stopped part is the authority's to end; any other is left to the
        # module's cleanup, which ends it by the buyer's own stop.
        deal_state._deal_ending = _stopped(snapshot)
        terms = deal_driver.rate_terms
        assert_contested_case_ruled(
            record, snapshot, case_ref=str(deal_state.case_ref),
            payer=str(deal_state.payer_account), payee=str(payment_setting("SELLER_ACCOUNT")),
            claimed_end=deal_state.delivery_end_at, authority=mediation_target.account,
            period_price=terms.period_gross, period_seconds=terms.period_seconds,
        )
        deal_state._ruling_applied = True
        log.info("[lc10] The policy ruled case %s: stopped, reversed %s, case closed",
                 deal_state.case_ref, snapshot["parts"][0]["reversed"])
