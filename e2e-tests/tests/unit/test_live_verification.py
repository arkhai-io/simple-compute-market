"""A live verification run's settings, provenance and per-period terms.

The ``LIVE`` settings parse and default to the lanes' values, refuse a value
that is no number of seconds and the terms the harness itself checks (a term
past the listing's hour, a period past the term, a notice not inside it), and a
run stating no provenance is a blocked skip naming
the setting. A recurring option's terms at a run's period are what the lanes'
are at theirs, and a live purchase asks for the run's term. Every value below is
a development fixture, never used on any network.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from tests.e2e.roles.helpers.compute_deal_stages import DURATION_HOURS
from tests.e2e.roles.helpers.live_verification import (
    LiveSettings,
    live_provenance,
    live_settings,
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
