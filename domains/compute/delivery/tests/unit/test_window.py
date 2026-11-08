"""The Agreement window: derived from the servicing record only, checked against commits."""

import pytest
from market_deal_servicing import DeliveryRecord
from market_identity import Ed25519Signer

from compute_delivery.window import (
    AgreementWindow,
    TimingInvalid,
    agreement_window,
    require_committed_window,
    utc_seconds,
    utc_text,
)

# Public deterministic development seed; never use on a public network.
SELLER = Ed25519Signer(bytes([2]) * 32).identity
START = 1_800_000_000


def record(start: int, end: int) -> DeliveryRecord:
    return DeliveryRecord(
        negotiation_id="deal", seller=SELLER, commitment_ref="commitment", start_at=start, term_end=end,
    )


def test_window_is_the_records_start_and_term_end():
    window = agreement_window(record(START, START + 7200))
    assert window == AgreementWindow(START, START + 7200)
    assert window.duration_seconds == 7200
    assert utc_seconds(window.start_utc) == START and utc_seconds(window.end_utc) == START + 7200


def test_an_empty_term_has_no_window():
    with pytest.raises(TimingInvalid):
        agreement_window(record(START, START))


@pytest.mark.parametrize("value", [None, "", "noon", "2027-01-15T08:00:00", 1800000000])
def test_unreadable_site_timestamps_are_timing_errors(value):
    with pytest.raises(TimingInvalid):
        utc_seconds(value)


def test_site_timestamps_read_in_whole_seconds_with_any_offset_spelling():
    assert utc_seconds(utc_text(START)) == START
    assert utc_seconds("2027-01-15T08:00:00Z") == utc_seconds("2027-01-15T08:00:00+00:00")
    assert utc_seconds("2027-01-15T08:00:00.900000+00:00") == utc_seconds("2027-01-15T08:00:00+00:00")


def test_a_commit_keeps_the_agreement_start_and_an_end_no_later():
    window = AgreementWindow(START, START + 7200)
    exact = {"lease_start_utc": utc_text(START), "lease_end_utc": utc_text(START + 7200)}
    truncated = {"lease_start_utc": utc_text(START), "lease_end_utc": utc_text(START + 3600)}
    assert require_committed_window(window, exact) == START + 7200
    assert require_committed_window(window, truncated) == START + 3600


@pytest.mark.parametrize("committed", [
    {"lease_start_utc": utc_text(START + 1800), "lease_end_utc": utc_text(START + 7200)},
    {"lease_start_utc": utc_text(START), "lease_end_utc": utc_text(START + 9000)},
    {"lease_start_utc": None, "lease_end_utc": utc_text(START + 7200)},
])
def test_a_commit_under_other_timing_is_refused(committed):
    with pytest.raises(TimingInvalid):
        require_committed_window(AgreementWindow(START, START + 7200), committed)
