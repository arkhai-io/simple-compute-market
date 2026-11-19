"""A live verification run's settings, provenance and per-period terms.

The ``LIVE`` settings parse and default to the lanes' values, refuse a value
that is no number of seconds and the terms the harness itself checks (a term
past the listing's hour, a period past the term, a notice not inside it), and a
run stating no provenance is a blocked skip naming the setting, the mediation
authority's revision among them for a scenario filing a case. The dispute
authority's record is polled until a case is closed, failing at the bound, or,
where only a topology's ruling policy rules it, skipping naming that
requirement when nothing ruled it; the buyer's contested case module then leaves
only its ruling unproven, its filing and contest standing. A recurring option's
terms at a run's period are what the lanes' are at theirs, and a live purchase
asks for the run's term. Every value below is a development fixture, never used
on any network.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta
from typing import Any

import pytest

from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS
from tests.e2e.roles.helpers.live_verification import (
    LiveSettings,
    await_case_closed,
    live_provenance,
    live_settings,
)
from tests.e2e.roles.helpers.qualification import (
    StageResult,
    declared_stages,
    observation_outcomes,
    stage_observations,
)
from tests.e2e.roles.helpers.rate_servicing_stages import SPOT_NOTICE_SECONDS
from tests.e2e.roles.helpers.recurring_purchase_stages import (
    LANE_RATE_TERMS,
    PERIOD,
    PERIOD_GROSS,
    PERIOD_SECONDS,
    RESERVE_AHEAD_SECONDS,
    RateTerms,
    recurring_settlement,
)
from tests.e2e.roles.scenarios.vms.live import test_buyer_contested_case as contested_case
from tests.e2e.roles.scenarios.vms.live.stages import (
    BUYERS_FILING,
    POLICY_RULING,
    RULING_POLICY_REQUIREMENT,
    STOREFRONTS_CONTEST,
    LiveRateState,
)
from tests.e2e.roles.scenarios.vms.rate_dispute.stages import RateDisputeState
from tests.e2e.roles.scenarios.vms.purchase_driver import VmLiveRatePurchaseDriver

Failed = pytest.fail.Exception
Skipped = pytest.skip.Exception


def _reader(**values: Any):
    def read(path: str) -> Any:
        section, _, name = path.partition(".")
        assert section == "LIVE", path
        return values.get(name)
    return read


def test_the_settings_default_to_the_lanes_terms() -> None:
    read = live_settings(setting=_reader())

    assert read == LiveSettings(period_seconds=PERIOD_SECONDS,
                                payee_notice_seconds=SPOT_NOTICE_SECONDS,
                                maximum_term_seconds=DURATION_HOURS * 3600,
                                poll_bound_seconds=120)
    assert read.rate_terms == LANE_RATE_TERMS
    assert read.reach_bound == timedelta(hours=DURATION_HOURS)


def test_the_settings_read_a_runs_short_terms_given_as_numbers_or_text() -> None:
    read = live_settings(setting=_reader(PERIOD_SECONDS=60, PAYEE_NOTICE_SECONDS="30",
                                         MAXIMUM_TERM_SECONDS=" 600 ", POLL_BOUND_SECONDS=45))

    assert read == LiveSettings(60, 30, 600, 45)
    assert read.poll_bound == timedelta(seconds=45)


@pytest.mark.parametrize("value", [0, -60, "1.5", "a minute", True])
def test_a_value_that_is_no_positive_whole_number_of_seconds_fails_naming_it(value) -> None:
    with pytest.raises(Failed, match="LIVE.PERIOD_SECONDS must be a positive whole number"):
        live_settings(setting=_reader(PERIOD_SECONDS=value))


@pytest.mark.parametrize(("values", "named"), [
    ({"MAXIMUM_TERM_SECONDS": DURATION_HOURS * 3600 + 1}, "LIVE.MAXIMUM_TERM_SECONDS"),
    ({"PERIOD_SECONDS": 601, "MAXIMUM_TERM_SECONDS": 600}, "LIVE.PERIOD_SECONDS"),
    ({"PERIOD_SECONDS": 60, "PAYEE_NOTICE_SECONDS": 600, "MAXIMUM_TERM_SECONDS": 600},
     "LIVE.PAYEE_NOTICE_SECONDS"),
])
def test_a_term_past_the_listing_a_period_past_the_term_or_a_notice_outside_it_fails(
        values, named) -> None:
    with pytest.raises(Failed, match=named):
        live_settings(setting=_reader(**values))


def test_the_provenance_is_read_whole() -> None:
    provenance = live_provenance(setting=_reader(
        SOURCE_REVISION="0123abc", TARGET_ALIAS="staging-a", PAYMENTS_REVISION="payments-7"))

    assert (provenance.source_revision, provenance.target_alias,
            provenance.payments_revision) == ("0123abc", "staging-a", "payments-7")


def test_a_run_stating_no_provenance_is_a_blocked_skip_naming_each_missing_setting() -> None:
    with pytest.raises(Skipped, match="states no LIVE.SOURCE_REVISION, LIVE.PAYMENTS_REVISION"):
        live_provenance(setting=_reader(TARGET_ALIAS="staging-a"))


def test_a_scenario_filing_a_case_labels_its_evidence_with_the_mediation_revision() -> None:
    provenance = live_provenance(mediation=True, setting=_reader(
        SOURCE_REVISION="0123abc", TARGET_ALIAS="staging-a", PAYMENTS_REVISION="payments-7",
        MEDIATION_REVISION="mediation-3"))

    assert provenance.mediation_revision == "mediation-3"
    assert live_provenance(setting=_reader(
        SOURCE_REVISION="0123abc", TARGET_ALIAS="staging-a", PAYMENTS_REVISION="payments-7",
        MEDIATION_REVISION="mediation-3")).mediation_revision is None


def test_a_scenario_filing_a_case_with_no_mediation_revision_is_a_blocked_skip() -> None:
    with pytest.raises(Skipped, match="states no LIVE.MEDIATION_REVISION"):
        live_provenance(mediation=True, setting=_reader(
            SOURCE_REVISION="0123abc", TARGET_ALIAS="staging-a", PAYMENTS_REVISION="payments-7"))


# ---------------------------------------------------------------------------
# Polling the dispute authority's record until the case is closed
# ---------------------------------------------------------------------------

class _Clock:
    """A monotonic clock a fake sleep moves."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _entry(kind: str, case_ref: str = "case-1") -> dict[str, Any]:
    return {"case_ref": case_ref, "kind": kind}


def _reads(*records: list[dict[str, Any]]):
    """A read returning each record in turn, then the last one for good."""
    remaining = list(records)

    def read() -> list[dict[str, Any]]:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]
    return read


def _await(read, *, ruling_requirement: str | None = None) -> list[dict[str, Any]]:
    clock = _Clock()
    return await_case_closed(read, case_ref="case-1", bound=timedelta(seconds=10),
                             ruling_requirement=ruling_requirement,
                             interval=timedelta(seconds=2), clock=clock, sleep=clock.sleep)


def test_the_record_is_polled_until_the_case_is_closed() -> None:
    filed = [_entry("filed")]
    closed = [*filed, _entry("ruled"), _entry("closed")]

    assert _await(_reads(filed, filed, closed)) == closed


def test_a_case_the_authority_never_closes_fails_at_the_bound_naming_it() -> None:
    raised = _raised(_reads([_entry("filed")]))

    assert isinstance(raised, AssertionError)
    assert "case case-1 closed did not appear within 0:00:10" in str(raised)


def test_a_case_no_policy_ruled_is_a_blocked_skip_naming_the_requirement() -> None:
    record = [_entry("filed"), _entry("appended"), _entry("ruled", "case-2")]

    with pytest.raises(Skipped, match=(
            "blocked: case case-1 was not ruled within 0:00:10, and the topology applies "
            "no ruling policy")):
        _await(_reads(record), ruling_requirement="the topology applies no ruling policy")


def _raised(read, *, ruling_requirement: str | None = None) -> BaseException:
    """What ``await_case_closed`` raises, caught whether it fails or skips, so
    that a wrong skip fails this test instead of being reported as a skipped
    test."""
    try:
        _await(read, ruling_requirement=ruling_requirement)
    except (AssertionError, Skipped) as raised:
        return raised
    raise AssertionError("await_case_closed neither failed nor skipped")


def test_a_case_ruled_and_still_open_at_the_bound_fails_though_a_policy_rules_it() -> None:
    raised = _raised(_reads([_entry("filed"), _entry("ruled")]),
                     ruling_requirement="the topology applies no ruling policy")

    assert isinstance(raised, AssertionError)
    assert "case case-1 closed did not appear" in str(raised)


def test_a_read_failing_before_the_bound_fails_though_a_policy_rules_the_case() -> None:
    """Only the bound passing is the policy requirement's: a failure of the
    read itself, such as a record entry refused, fails the stage."""
    def refused() -> list[dict[str, Any]]:
        raise AssertionError("the accepted Agreement names no dispute authority")

    raised = _raised(refused, ruling_requirement="the topology applies no ruling policy")

    assert isinstance(raised, AssertionError)
    assert "names no dispute authority" in str(raised)


# ---------------------------------------------------------------------------
# The buyer's contested case's observations
# ---------------------------------------------------------------------------

def _contested_outcomes(outcome_of) -> dict[str, Any]:
    """The contested case module's observations' outcomes, each stage declared
    in the module given the outcome and reason ``outcome_of`` names for it."""
    results = [StageResult(cls.__name__, frozenset(stage_observations(contested_case, cls)),
                           *outcome_of(cls.__name__))
               for cls, _ in declared_stages(contested_case)]
    return {outcome.observation: outcome
            for outcome in observation_outcomes(contested_case.OBSERVATIONS, results)}


def test_a_topology_applying_no_ruling_policy_leaves_only_the_ruling_unproven() -> None:
    """The skip the record poll raises for a contested case no policy ruled,
    as the ruling stage polls it, is the reason the module's ruling is
    unproven by, its filing and contest made."""
    skipped = _raised(_reads([_entry("filed"), _entry("appended")]),
                      ruling_requirement=RULING_POLICY_REQUIREMENT)
    assert isinstance(skipped, Skipped)
    reason = str(skipped)

    outcomes = _contested_outcomes(lambda stage: (
        ("skipped", reason) if stage == "TestLiveContestedCase10_PolicyRuling" else ("passed", "")))

    assert contested_case.OBSERVATIONS == (BUYERS_FILING, STOREFRONTS_CONTEST, POLICY_RULING)
    assert {name: outcome.outcome for name, outcome in outcomes.items()} == {
        BUYERS_FILING: "made", STOREFRONTS_CONTEST: "made", POLICY_RULING: "unproven"}
    assert outcomes[POLICY_RULING].reasons == (reason,)
    assert reason == (f"blocked: case case-1 was not ruled within 0:00:10, and "
                      f"{RULING_POLICY_REQUIREMENT}")


def test_a_failed_contest_fails_the_contest_and_the_ruling_and_the_filing_stands() -> None:
    outcomes = _contested_outcomes(lambda stage: (
        ("failed", "") if stage == "TestLiveContestedCase09_StorefrontContests"
        else ("passed", "")))

    assert {name: outcome.outcome for name, outcome in outcomes.items()} == {
        BUYERS_FILING: "made", STOREFRONTS_CONTEST: "failed", POLICY_RULING: "failed"}


def test_a_live_modules_state_carries_a_rate_dispute_rows_fields() -> None:
    """The live dispute stages hand each other what the lane twin's do, on the
    one state every live module builds."""
    names = {field.name for field in dataclasses.fields(LiveRateState)}

    assert {field.name for field in dataclasses.fields(RateDisputeState)} <= names
    assert {"_live_labelled", "_first_period_held", "_case_contested"} <= names


def test_a_failed_shared_stage_fails_every_observation() -> None:
    outcomes = _contested_outcomes(lambda stage: (
        ("failed", "") if stage == "TestRecurring04_MandateApproved" else ("passed", "")))

    assert {outcome.outcome for outcome in outcomes.values()} == {"failed"}


def test_the_lanes_terms_are_the_lanes_constants() -> None:
    assert (LANE_RATE_TERMS.period, LANE_RATE_TERMS.period_gross,
            LANE_RATE_TERMS.reserve_ahead_seconds) == (PERIOD, PERIOD_GROSS, RESERVE_AHEAD_SECONDS)


@pytest.mark.parametrize(("seconds", "period", "gross"), [
    (60, "PT1M", 16_666), (90, "PT90S", 25_000), (3600, "PT1H", 1_000_000),
])
def test_a_runs_period_is_written_in_its_largest_whole_unit_and_priced_at_the_hourly_rate(
    seconds, period, gross,
) -> None:
    terms = RateTerms(seconds)

    assert (terms.period, terms.period_gross, terms.reserve_ahead_seconds) == (
        period, gross, seconds)


def test_a_recurring_clause_states_its_terms_period_and_reserve_ahead() -> None:
    clause = recurring_settlement(seller_account="00000000-0000-4000-8000-0000000000b2",
                                  delivery_deadline_seconds=300, terms=RateTerms(60))

    assert clause["recurring"] == {"period": "PT1M", "reserve_ahead_seconds": 60}


def test_a_live_purchase_asks_for_the_runs_term_in_seconds() -> None:
    driver = VmLiveRatePurchaseDriver.__new__(VmLiveRatePurchaseDriver)
    driver.term_seconds = 600
    driver.gpu_model = "RTX 3090 Ti"
    driver.buyer_config = {"ssh_public_key": "ssh-ed25519 AAAA test@e2e"}

    arguments = driver.buy_arguments("listing", "option")

    at = arguments.index("--duration-seconds")
    assert arguments[at + 1] == "600"
    assert "--duration-hours" not in arguments
