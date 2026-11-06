"""A progress row is read strictly; one that disagrees with itself is unreadable."""

import pytest

from compute_delivery import DeliveryOutcome, OutcomeKind, RecordedProgress, RepairReason
from compute_delivery.ports import DeliveryStep
from compute_delivery.progress import Progress, ProgressUnreadable, read_progress, recorded_identities


@pytest.mark.parametrize("recorded, expected", [
    (RecordedProgress("reserve"), Progress(DeliveryStep.RESERVE)),
    (RecordedProgress("commit", "res-1"), Progress(DeliveryStep.COMMIT, "res-1")),
    (RecordedProgress("dispatch", "res-1"), Progress(DeliveryStep.DISPATCH, "res-1")),
    (RecordedProgress("fulfillment", "res-1", "ful-1"), Progress(DeliveryStep.FULFILLMENT, "res-1", "ful-1")),
    (RecordedProgress("activated", "res-1", "ful-1", 5), Progress(DeliveryStep.ACTIVATED, "res-1", "ful-1", 5)),
])
def test_each_step_reads_with_the_records_it_names(recorded, expected):
    assert read_progress(recorded) == expected


@pytest.mark.parametrize("recorded", [
    {"step": "reserve"},
    RecordedProgress("activate", "res-1", "ful-1"),
    RecordedProgress("reserve", "res-1"),
    RecordedProgress("commit"),
    RecordedProgress("dispatch", "res-1", "ful-1"),
    RecordedProgress("fulfillment", "res-1"),
    RecordedProgress("activated", "res-1", "ful-1"),
    RecordedProgress("commit", ""),
    RecordedProgress("commit", 7),
    RecordedProgress("activated", "res-1", "ful-1", True),
    RecordedProgress("activated", "res-1", "ful-1", -1),
])
def test_an_unknown_step_or_a_row_disagreeing_with_itself_is_unreadable(recorded):
    with pytest.raises(ProgressUnreadable):
        read_progress(recorded)


def test_an_unreadable_row_still_reports_the_identities_it_names():
    assert recorded_identities(RecordedProgress("mystery", "res-1", 7)) == ("res-1", None)
    assert recorded_identities(None) == (None, None)


def test_outcomes_carry_what_their_kind_requires():
    with pytest.raises(ValueError):
        DeliveryOutcome(OutcomeKind.WAITING)
    with pytest.raises(ValueError):
        DeliveryOutcome(OutcomeKind.REPAIR_REQUIRED, reason=RepairReason.TIMING_INVALID)
    with pytest.raises(ValueError):
        DeliveryOutcome(OutcomeKind.ENDED)
    with pytest.raises(ValueError):
        DeliveryOutcome(OutcomeKind.PENDING, reason=RepairReason.TIMING_INVALID)


@pytest.mark.parametrize("kind, disposition", [
    (OutcomeKind.AVAILABLE, "fulfilled"),
    (OutcomeKind.CONVERGED, "fulfilled"),
    (OutcomeKind.PENDING, "deferred"),
    (OutcomeKind.ENDED, "failed"),
])
def test_a_hook_maps_outcomes_to_its_dispositions(kind, disposition):
    outcome = DeliveryOutcome(kind, evidence_ref="end" if kind is OutcomeKind.ENDED else None)
    assert outcome.hook_disposition == disposition
    assert DeliveryOutcome(OutcomeKind.WAITING, wake_at=1).hook_disposition == "deferred"
    assert DeliveryOutcome(
        OutcomeKind.REPAIR_REQUIRED, reason=RepairReason.SITE_UNANSWERED, evidence_ref="site",
    ).hook_disposition == "deferred"
