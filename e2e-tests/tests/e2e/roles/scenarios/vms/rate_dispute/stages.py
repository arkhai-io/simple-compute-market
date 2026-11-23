"""VM stages of a dispute on a running rate deal, which each rate-dispute row subclasses.

Each row is one module on a deal of its own, bought through ``market buy`` by a
default buyer under the shipped on-demand preset, against the lane's
``[charged, returned]`` declaration, and delivered: the recurring purchase's
stages through ``Recurring07``, with the teardown gate armed (``Stage09c2``).
Lane time is then set a minute into the second period, so the first period's
earnings are held (``RateDispute07``), and a case is filed and ruled with an
authority stop:

- **the seller's filing** — the lane's payments double first reserves the part
  through the Agreement's end (``Reservation06``), since the ruling falls past
  the part's first reservation. A rule is installed for the storefront's filing,
  held at its gate, ruling as the dispute authority documents a mechanical
  ruling: basis ``payee_filed``, a delivery end, a ``stop`` at that end
  returning its period, whose application reverses the earnings since the end,
  and a ``penalty`` of the Agreement's premature-stop penalty, closing the case
  (``SellerFiling08``).
  The storefront's administrator ends delivery as a failure, which records the
  end and files ``delivery_end`` as the payee (``SellerFiling09``). With the
  ruling still at its gate, lane time moves past the second period's end, so the
  part earns that period after the delivery end; the ruling then resumes and
  applies every effect at that instant (``SellerFiling10``), and a servicing
  step records the authority's stop with no further filing (``SellerFiling11``);
- **the buyer's contested case** — the buyer files through the mediation kit's
  dispute adapter in the harness (``ContestedCase08``), a servicing step answers
  the case as respondent, which contests it (``ContestedCase09``), an operator
  decision rules a ``stop`` returning its period and a ``reverse`` of the held
  first period, closing the case (``ContestedCase10``), and a servicing step
  records the ruled end with no filing (``ContestedCase11``).

Each then runs the canonical teardown, ``Stage11a2`` and ``Stage11b``, reads the
payer's returns (``RateDispute12``) and, the case closed, the seller's list
reading the deal ``ended`` with no open extension (``RateDispute13``).

What the authorities emit — the dispute authority's signed record of the case,
read as the buyer through the mediation kit's public client, and the payments
snapshot its effects moved — is asserted through the row's assertion in
``producer_assertions.py``, apart from the read. No storefront route reads how
the storefront classified the authority's stop, so a row observes what follows
from its classification ``ruling``: the end recorded with no filing for it.

The rules, the decision and the reservation are the lane doubles' controls, so
these stages run only against a Compose lane's doubles on injected lane time,
and are a blocked skip anywhere else. Each row is lane-double evidence. The
inputs a row gives the dispute authority through this repository's own client
code — the administrator's end and the storefront's filing
(``end_delivery_as_a_failure``, held to its filing by ``filed_as_payee``), the
buyer's filing (``file_the_buyers_claim``), the storefront's contest
(``contest_as_respondent``) — are functions apart from the stages, which the
live verification modules give a hosted authority the same way
(``scenarios/vms/live/stages.py``). These stages are not named ``Test*``: a
module collects each by subclassing it with an empty body, in its run order.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pytest
from lane_double_controls import Rule, Ruling
from market_deal_lifecycle.terms import decode_terms

from tests.e2e.roles.helpers.compute_deal import advance_storefront, assert_lease_watchdog_held
from tests.e2e.roles.helpers.domain_deal import require_state
from tests.e2e.roles.helpers.lane_doubles import LaneDoubleRules
from tests.e2e.roles.helpers.lane_time import LaneTime
from tests.e2e.roles.helpers.mediation import MediationTarget, file_as_buyer, read_record
from tests.e2e.roles.helpers.payments import payment_setting
from tests.e2e.roles.helpers.producer_assertions import (
    assert_contested_case_ruled,
    assert_payee_filing_ruled,
)
from tests.e2e.roles.helpers.rate_servicing_stages import RateServicingState
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    PERIOD_GROSS,
    PERIOD_SECONDS,
    RecurringPurchaseDriver,
    begin_teardown,
    lane_double_run,
    payer_available,
    reach_lane_instant,
    seller_deal,
    transaction_snapshot,
)

log = logging.getLogger(__name__)

#: How far into the second period a row files: past the first period's end, so
#: its earnings are held, and before the second's.
INTO_SECOND_PERIOD_SECONDS = PERIOD_SECONDS + 60
#: The mediation double's rule for the seller's filing.
SELLER_FILING_RULE = "vm-rate-dispute-seller-filing"
#: The administrator's reason for ending the seller's delivery.
SELLER_FAILURE_REASON = "the seller's delivery failed"


@dataclass
class RateDisputeState(RateServicingState):
    """What a rate-dispute row's stages hand each other, beside a rate row's."""

    #: The instant the case's delivery end falls at, lane time's in a lane and
    #: the wall clock's in a live run: the seller's recorded end, or the
    #: buyer's claimed one.
    delivery_end_at: Optional[int] = None
    #: The Agreement's premature-stop penalty the seller's filing is ruled with.
    penalty: Optional[int] = None
    #: The case the row filed.
    case_ref: Optional[str] = None
    #: The authorities applied the ruling and closed the case.
    _ruling_applied: bool = False


def _require_lane_doubles(lane_time: LaneTime | None) -> None:
    """A blocked skip unless the run is a Compose lane's, whose doubles' controls
    a rate-dispute row programs."""
    if not lane_double_run(lane_time):
        pytest.skip("blocked: a rate-dispute row programs the lane doubles' rules, decisions "
                    "and reservation, which only a Compose lane's injected run with its own "
                    "payments target reaches (PAYMENTS.LANE_OWNED)")


def _the_part(payments_config: Any, deal_state: RateDisputeState) -> dict[str, Any]:
    snapshot = transaction_snapshot(payments_config, deal_state.payer_account,
                                    deal_state.settlement_id)
    assert len(snapshot["parts"]) == 1, snapshot["parts"]
    part: dict[str, Any] = snapshot["parts"][0]
    return part


def _the_case(rules: LaneDoubleRules, transaction: str) -> Any:
    (case,) = rules.controls["mediation"].cases(transaction).cases
    return case


def _producer_output(payments_config: Any, mediation_target: MediationTarget,
                     deal_state: RateDisputeState) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The dispute authority's record of the deal, read as the buyer, and the
    payments snapshot, read by the payer; both logged, with the identifiers
    they are read by."""
    record = read_record(mediation_target, negotiation_id=deal_state.negotiation_id,
                         transaction=deal_state.settlement_id, agreement=deal_state.agreement)
    snapshot = transaction_snapshot(payments_config, deal_state.payer_account,
                                    deal_state.settlement_id)
    log.info("Producer output for Agreement %s, transaction %s, case %s: %s",
             deal_state.negotiation_id, deal_state.settlement_id, deal_state.case_ref,
             json.dumps({"record": record, "snapshot": snapshot}, sort_keys=True))
    return record, snapshot


def premature_stop_penalty(agreement: Any) -> int:
    """The Agreement's premature-stop penalty, which a mechanical ruling of a
    payee's ``delivery_end`` takes from the part's held earnings, capped."""
    terms = decode_terms(agreement["settlement"]["lifecycle"])
    assert terms is not None and terms.early_termination is not None, terms
    return int(terms.early_termination.premature_stop_penalty)


def end_delivery_as_a_failure(storefront_admin_client: Any,
                              deal_state: RateDisputeState) -> dict[str, Any]:
    """The storefront's administrator ends the deal's delivery as a failure,
    through the storefront client's interruption; the storefront's answer,
    which ``filed_as_payee`` holds to its filing."""
    ended: dict[str, Any] = storefront_admin_client.admin_interrupt_deal(
        deal_state.negotiation_id, reason=SELLER_FAILURE_REASON, interruption_kind="failure",
    )
    return ended


def filed_as_payee(ended: dict[str, Any]) -> tuple[int, str]:
    """The administrator's end recorded the operator's end, filed
    ``delivery_end`` as the payee, which the dispute authority accepted, and
    began the teardown. The instant the storefront recorded the end at, which
    its filing claims, and the case the authority filed."""
    assert ended["settlement_action"] == "delivery_end_filing", ended
    outcome = ended["lifecycle_outcome"]
    assert outcome["status"] == "accepted" and outcome.get("filing"), ended
    recorded = ended["delivery"]["recorded_end"]
    assert recorded["cause"] == "operator_end", ended
    assert ended["delivery"]["progress"] == "tearing_down", ended
    return int(recorded["ended_at"]), str(outcome["filing"]["case_ref"])


def file_the_buyers_claim(mediation_target: MediationTarget, buyer_evidence: Path,
                          deal_state: RateDisputeState) -> str:
    """The buyer files ``delivery_end`` at ``delivery_end_at`` through the
    mediation kit's dispute adapter, as its lifecycle would; the authority
    accepts the filing and holds the one part by an extension. The case it
    filed."""
    outcome = file_as_buyer(mediation_target, negotiation_id=deal_state.negotiation_id,
                            transaction=deal_state.settlement_id,
                            agreement=deal_state.agreement, store=buyer_evidence,
                            ended_at=deal_state.delivery_end_at)
    assert outcome.status == "accepted" and outcome.filing is not None, outcome
    assert [(part.part, part.status) for part in outcome.filing.parts] == [("0", "held")], outcome
    return str(outcome.filing.case_ref)


def contest_as_respondent(storefront_admin_client: Any, deal_driver: RecurringPurchaseDriver,
                          deal_state: RateDisputeState) -> None:
    """One servicing step: the storefront's respondent discovery finds the
    buyer's case on the authority's respondent listing and answers it on the
    record, one append by the seller's account, which contests the claim;
    delivery stays active, no end recorded."""
    advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
    read = deal_driver.lifecycle_read(deal_state.negotiation_id)
    answers = [event.actor for event in read.authority.disputes
               if event.kind == "appended" and event.case_ref == deal_state.case_ref]
    assert answers == [str(payment_setting("SELLER_ACCOUNT"))], read.authority.disputes
    assert (read.delivery.progress, read.delivery.recorded_end) == ("active", None), read.delivery


def _ruling_recorded(deal_driver: RecurringPurchaseDriver, deal_state: RateDisputeState, *,
                     filings: list[str]) -> Any:
    """The storefront's read once a servicing step read the ruling: the end
    recorded as the ruling's at the case's delivery end, the part's final stop
    the authority's, and no filing beyond ``filings``' outcomes."""
    read = deal_driver.lifecycle_read(deal_state.negotiation_id)
    end = read.delivery.recorded_end
    assert end is not None, f"the storefront recorded no end: {read.delivery}"
    assert (end.cause, end.ended_at) == ("ruling", deal_state.delivery_end_at), (
        f"the storefront recorded the end {end.cause!r} at {end.ended_at}, not the ruling's "
        f"at {deal_state.delivery_end_at}: {end}"
    )
    (part,) = read.authority.parts
    assert part.final_stop is not None and part.final_stop.cause == "authority", part
    assert [filing.outcome.status for filing in read.filings] == filings, read.filings
    return read


# ===========================================================================
# Both rows
# ===========================================================================

class RateDispute07_FirstPeriodHeld:
    def test_d07_the_first_periods_earnings_are_held(
        self, payments_config, lane_time, deal_state: RateDisputeState,
    ):
        """Lane time a minute into the second period: the payments double has
        earned the first period and holds it, and the part runs on.

        That instant is the case's delivery end, the seller's recorded end or
        the buyer's claimed one, since lane time holds it until a stage moves it.
        """
        require_state(deal_state, "_accepted_money_shown", "_teardown_gate_armed",
                      "payer_account", "settlement_id")
        _require_lane_doubles(lane_time)
        started = int(_the_part(payments_config, deal_state)["started"])
        instant = started + INTO_SECOND_PERIOD_SECONDS
        reach_lane_instant(lane_time, instant, fixed_by_agreement=False)
        part = _the_part(payments_config, deal_state)
        assert (part["rate"]["periodsEarned"], int(part["held"])) == ("1", PERIOD_GROSS), part
        assert part.get("stop") is None, part
        deal_state.delivery_end_at = instant
        log.info("[d07] Transaction %s at %s: the first period's %s held",
                 deal_state.settlement_id, instant, PERIOD_GROSS)


class RateDispute12_PayerReturned:
    def test_d12_the_payer_paid_only_what_the_ruling_left_the_payee(
        self, payments_config, deal_state: RateDisputeState,
    ):
        """The payer's available balance is what ``Purchase01`` read less what
        the part kept for the payee, its held and released amounts: the
        unstarted remainder and every reversed amount came back, while nothing
        else spends from the account."""
        require_state(deal_state, "_deal_ended", "payer_account", "payer_available_before",
                      "_teardown_job_completed")
        part = _the_part(payments_config, deal_state)
        kept = int(part["held"]) + int(part["released"])
        before = deal_state.payer_available_before
        after = payer_available(payments_config, deal_state.payer_account)
        asset = part["asset"]
        assert after == {**before, asset: before.get(asset, 0) - kept}, (
            f"payer {deal_state.payer_account}'s available balance is {after}; it was {before} "
            f"before the purchase, and the part kept {kept} {asset}"
        )
        deal_state._payer_charged = True
        log.info("[d12] Payer %s available %s; the part kept %s %s, reversed %s",
                 deal_state.payer_account, after, kept, asset, part["reversed"])


class RateDispute13_DealEnded:
    def test_d13_the_sellers_list_shows_the_deal_ended(
        self, storefront_admin_client, lane_double_rules: LaneDoubleRules,
        deal_driver: RecurringPurchaseDriver, deal_state: RateDisputeState,
    ):
        """With the case closed and the release proven, one servicing step
        reads the deal's authorities, and the seller's list, read as the
        storefront's administrator through the typed seller client, shows it
        ``ended``: no outstanding code, its part stopped, no open case and no
        open extension. The mediation double holds the row's one case on the
        transaction and no other."""
        require_state(deal_state, "negotiation_id", "case_ref", "_payer_charged",
                      "_teardown_job_completed")
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        deal = seller_deal(storefront_admin_client, deal_state.negotiation_id)
        assert (deal.state, deal.ending) == ("ended", []), (
            f"the seller's list shows {deal.negotiation_id} {deal.state} with "
            f"{deal.ending_reasons}: {deal}"
        )
        assert deal.parts and all(part.final_stop is not None for part in deal.parts), deal.parts
        assert (deal.open_cases, deal.has_open_extension) == ([], False), deal
        cases = lane_double_rules.controls["mediation"].cases(deal_state.settlement_id).cases
        assert [case.case_ref for case in cases] == [deal_state.case_ref], cases
        log.info("[d13] The seller's list shows Agreement %s ended, case %s closed",
                 deal.negotiation_id, deal_state.case_ref)


# ===========================================================================
# The seller's filing
# ===========================================================================

class SellerFiling08_MechanicalRulingInstalled:
    def test_s08_a_gated_mechanical_ruling_on_the_sellers_filing_is_installed(
        self, lane_double_rules: LaneDoubleRules, deal_state: RateDisputeState,
    ):
        """A rule on the deal's filing, held at its gate before any effect,
        ruling as the dispute authority documents a mechanical ruling of a
        payee's ``delivery_end``: basis ``payee_filed``, a delivery end, a stop
        at that end returning its period, and the Agreement's premature-stop
        penalty, closing the case. The ruling carries no reverse of its own: the
        stop, applied once its time has passed, reverses what the part earned
        since the end, the period ``SellerFiling10`` lets it earn before the
        ruling applies.
        """
        require_state(deal_state, "delivery_end_at", "agreement", "settlement_id",
                      "reserved_through")
        penalty = premature_stop_penalty(deal_state.agreement)
        view = lane_double_rules.install("mediation", Rule(
            rule_id=SELLER_FILING_RULE,
            match={"operation": "file", "transaction": deal_state.settlement_id,
                   "filer": "payee"},
            ruling=Ruling(basis="payee_filed", delivery_end=True, close=True, effects=[
                {"kind": "stop", "part": 0, "at": deal_state.delivery_end_at,
                 "partialPeriod": "returned"},
                {"kind": "penalty", "amount": str(penalty)},
            ]),
            pause_before_effects=True,
        ))
        assert (view.matched, view.waiting) == (0, 0), view
        deal_state.penalty = penalty
        log.info("[s08] Gated mechanical ruling %s installed for transaction %s: penalty %s",
                 SELLER_FILING_RULE, deal_state.settlement_id, penalty)


class SellerFiling09_StorefrontFilesAsPayee:
    def test_s09_the_administrators_end_records_the_end_and_files_as_the_payee(
        self, storefront_admin_client, payments_config, lane_double_rules: LaneDoubleRules,
        deal_state: RateDisputeState,
    ):
        """The storefront's administrator ends the delivery as a failure: the
        storefront records the operator's end at the lane instant, files
        ``delivery_end`` as the payee and begins the teardown, held at its gate.
        The mediation double accepts the filing, holding the part by an
        extension, and its ruling waits at the gate; payments has stopped
        nothing."""
        require_state(deal_state, "penalty", "delivery_end_at", "negotiation_id",
                      "settlement_id")
        deal_state._deal_ending = True
        ended_at, case_ref = filed_as_payee(
            end_delivery_as_a_failure(storefront_admin_client, deal_state))
        assert ended_at == deal_state.delivery_end_at, (ended_at, deal_state.delivery_end_at)
        case = _the_case(lane_double_rules, deal_state.settlement_id)
        assert (case.case_ref, case.state, case.filer) == (case_ref, "applying", "payee"), case
        view = lane_double_rules.view("mediation", SELLER_FILING_RULE)
        assert (view.matched, view.waiting) == (1, 1), view
        part = _the_part(payments_config, deal_state)
        assert part.get("stop") is None and len(part["extensions"]) == 1, part
        deal_state.case_ref = case.case_ref
        log.info("[s09] Operator end of Agreement %s at %s filed as case %s; its ruling waits",
                 deal_state.negotiation_id, deal_state.delivery_end_at, case.case_ref)


class SellerFiling10_RulingApplied:
    def test_s10_the_mechanical_ruling_applies_after_the_part_earned_past_the_end(
        self, payments_config, mediation_target, lane_time, lane_double_rules: LaneDoubleRules,
        deal_state: RateDisputeState,
    ):
        """Lane time moves a period on, past the second period's end, which the
        part earns after the delivery end; then the ruling resumes. The double
        applies every effect at that instant — the stop, whose time has passed,
        is a stop now followed by the reversal of that period, and the penalty
        reverses what the part then holds — lifts the case's extension and
        closes the case. The authority's record and the payments snapshot are
        read and asserted through ``assert_payee_filing_ruled``. No servicing
        step runs while the ruling waits."""
        require_state(deal_state, "case_ref", "delivery_end_at", "reserved_through", "penalty",
                      "agreement", "negotiation_id")
        ruled_at = deal_state.delivery_end_at + PERIOD_SECONDS
        assert ruled_at < deal_state.reserved_through, (ruled_at, deal_state.reserved_through)
        reach_lane_instant(lane_time, ruled_at, fixed_by_agreement=False)
        part = _the_part(payments_config, deal_state)
        assert (part["rate"]["periodsEarned"], part.get("stop")) == ("2", None), part
        view = lane_double_rules.resume(SELLER_FILING_RULE)
        assert view.waiting == 0, view
        assert _the_case(lane_double_rules, deal_state.settlement_id).state == "closed"
        record, snapshot = _producer_output(payments_config, mediation_target, deal_state)
        assert_payee_filing_ruled(
            record, snapshot, case_ref=deal_state.case_ref,
            payee=str(payment_setting("SELLER_ACCOUNT")), claimed_end=deal_state.delivery_end_at,
            authority=mediation_target.account, penalty=deal_state.penalty,
            period_price=PERIOD_GROSS, period_seconds=PERIOD_SECONDS,
        )
        deal_state._ruling_applied = True
        log.info("[s10] Case %s ruled at %s: stopped, reversed %s, case closed",
                 deal_state.case_ref, ruled_at, snapshot["parts"][0]["reversed"])


class SellerFiling11_StorefrontRecordsTheRuling:
    def test_s11_the_storefront_records_the_authoritys_stop_with_no_further_filing(
        self, provisioning_client, storefront_admin_client, deal_driver: RecurringPurchaseDriver,
        deal_state: RateDisputeState,
    ):
        """One servicing step reads the ruling: the ruled delivery end, at the
        operator's end, is the recorded end, the authority's stop is the part's
        final stop, and the one filing is the operator end's own, accepted, with
        none for the authority's stop. The operator's end began the teardown at
        the site, which one convergence advance dispatches (``begin_teardown``)."""
        require_state(deal_state, "_ruling_applied", "delivery_end_at", "negotiation_id",
                      "deal_lease", "reserved_resource_id")
        assert_lease_watchdog_held(provisioning_client)
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        _ruling_recorded(deal_driver, deal_state, filings=["accepted"])
        deal_state.teardown_fulfillment_id = begin_teardown(
            provisioning_client, storefront_admin_client, deal_driver, deal_state)
        deal_state._deal_ended = True
        log.info("[s11] Agreement %s's ruled end recorded; fulfillment %s tearing down",
                 deal_state.negotiation_id, deal_state.teardown_fulfillment_id)


# ===========================================================================
# The buyer's contested case
# ===========================================================================

class ContestedCase08_BuyerFiles:
    def test_c08_the_buyers_filing_is_held_and_unruled(
        self, payments_config, mediation_target, lane_double_rules: LaneDoubleRules,
        buyer_evidence: Path, deal_state: RateDisputeState,
    ):
        """The buyer files ``delivery_end`` through the mediation kit's dispute
        adapter, as its lifecycle would, claiming the end at the lane instant.
        With no rule installed the double accepts the filing, holds the part by
        an extension and rules nothing; the case stays open."""
        require_state(deal_state, "delivery_end_at", "negotiation_id", "settlement_id",
                      "agreement")
        case_ref = file_the_buyers_claim(mediation_target, buyer_evidence, deal_state)
        case = _the_case(lane_double_rules, deal_state.settlement_id)
        assert (case.case_ref, case.state, case.filer) == (case_ref, "open", "payer"), case
        deal_state.case_ref = case.case_ref
        log.info("[c08] The buyer filed case %s on Agreement %s", case.case_ref,
                 deal_state.negotiation_id)


class ContestedCase09_StorefrontContests:
    def test_c09_a_servicing_step_contests_the_case_as_respondent(
        self, storefront_admin_client, deal_driver: RecurringPurchaseDriver,
        deal_state: RateDisputeState,
    ):
        """The storefront's respondent discovery answers the buyer's case on
        the record, one append by the seller's account, which contests the
        claim; delivery stays active, no end recorded."""
        require_state(deal_state, "case_ref", "negotiation_id")
        contest_as_respondent(storefront_admin_client, deal_driver, deal_state)
        log.info("[c09] The storefront contested case %s", deal_state.case_ref)


class ContestedCase10_OperatorRules:
    def test_c10_an_operators_stop_and_reverse_close_the_case(
        self, payments_config, mediation_target, lane_double_rules: LaneDoubleRules,
        deal_state: RateDisputeState,
    ):
        """An operator decision through the typed control client rules the
        case: a delivery end, a stop at the claimed end returning its period,
        and a reverse of the held first period, closing the case. The claimed
        end is the lane instant no stage has moved since, so the stop's time has
        not passed and it reverses nothing of its own; the reverse is the
        operator's. The double applies both at once and lifts the case's
        extension. The authority's record and the payments snapshot are read and
        asserted through ``assert_contested_case_ruled``."""
        require_state(deal_state, "case_ref", "delivery_end_at", "agreement", "negotiation_id")
        deal_state._deal_ending = True
        case = lane_double_rules.controls["mediation"].decide(deal_state.case_ref, Ruling(
            basis="operator", delivery_end=True, close=True, effects=[
                {"kind": "stop", "part": 0, "at": deal_state.delivery_end_at,
                 "partialPeriod": "returned"},
                {"kind": "reverse", "part": 0, "amount": str(PERIOD_GROSS)},
            ],
        ))
        assert case.state == "closed", case
        record, snapshot = _producer_output(payments_config, mediation_target, deal_state)
        assert_contested_case_ruled(
            record, snapshot, case_ref=deal_state.case_ref, payer=str(deal_state.payer_account),
            payee=str(payment_setting("SELLER_ACCOUNT")), claimed_end=deal_state.delivery_end_at,
            authority=mediation_target.account, period_price=PERIOD_GROSS,
            period_seconds=PERIOD_SECONDS, ruled_end=deal_state.delivery_end_at,
            reverse_amount=PERIOD_GROSS,
        )
        deal_state._ruling_applied = True
        log.info("[c10] The operator ruled case %s: stopped, reversed %s, case closed",
                 deal_state.case_ref, PERIOD_GROSS)


class ContestedCase11_StorefrontRecordsTheRuling:
    def test_c11_the_storefront_records_the_ruled_end_with_no_filing(
        self, provisioning_client, storefront_admin_client, deal_driver: RecurringPurchaseDriver,
        deal_state: RateDisputeState,
    ):
        """One servicing step reads the ruling: the ruled delivery end is the
        recorded end, the authority's stop is the part's final stop, and nothing
        is filed for either; the end is carried out at the site, and one
        convergence advance dispatches the teardown (``begin_teardown``)."""
        require_state(deal_state, "_ruling_applied", "delivery_end_at", "negotiation_id",
                      "deal_lease", "reserved_resource_id")
        assert_lease_watchdog_held(provisioning_client)
        advance_storefront(storefront_admin_client, deal_driver.servicing_loop)
        _ruling_recorded(deal_driver, deal_state, filings=[])
        deal_state.teardown_fulfillment_id = begin_teardown(
            provisioning_client, storefront_admin_client, deal_driver, deal_state)
        deal_state._deal_ended = True
        log.info("[c11] Agreement %s's ruled end recorded; fulfillment %s tearing down",
                 deal_state.negotiation_id, deal_state.teardown_fulfillment_id)
