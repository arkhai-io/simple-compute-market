"""The guard's rules, one test each, against whatever store the ``store`` fixture gives.

The unit suite runs them against the in-memory double; the integration suite runs
the same tests against the ``sqlite3`` store and the SQLAlchemy store over real
SQLite files.
"""

from __future__ import annotations

from request_replay import (
    Answered,
    ChangedReuse,
    Dispatch,
    Expired,
    InProgress,
    Outcome,
    OutcomeUnknown,
    Resolution,
)

from tests.support import OUTCOME, POLICY, START, ManualClock, RecordingFirst, TakenFirst, entry, guard

RERUN = Resolution.RERUN
RECORDED = Resolution.RECORDED
SKEW = POLICY.skew_seconds
LEASE = POLICY.lease_seconds
RETENTION = POLICY.retention_seconds


def test_a_first_use_is_dispatched_and_its_concurrent_retry_is_in_progress(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)

    for resolution in (RERUN, RECORDED):
        first = replay.admit(entry(resolution, request_id=f"r-{resolution.value}"))
        assert isinstance(first, Dispatch) and first.exact_retry is False
        assert replay.admit(entry(resolution, request_id=f"r-{resolution.value}")) == InProgress()


def test_a_reused_request_id_with_another_hash_is_changed_reuse(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RECORDED))
    assert isinstance(first, Dispatch)
    replay.complete(first.attempt, OUTCOME)

    assert replay.admit(entry(RECORDED, request_hash="hash-b")) == ChangedReuse()
    assert isinstance(replay.admit(entry(RERUN, request_id="r2")), Dispatch)
    assert replay.admit(entry(RERUN, request_id="r2", request_hash="hash-b")) == ChangedReuse()


def test_a_completed_rerun_request_runs_again_as_an_exact_retry_recording_nothing(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RERUN))
    assert isinstance(first, Dispatch)
    replay.complete(first.attempt, OUTCOME)

    row = store.get("scheme:caller-1", "request-1", now=clock())
    assert row is not None and row.outcome is None and row.lease_owner is None

    retry = replay.admit(entry(RERUN))
    assert isinstance(retry, Dispatch) and retry.exact_retry is True


def test_a_rerun_lease_left_by_a_crash_is_reclaimed_by_one_retry(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    assert isinstance(replay.admit(entry(RERUN)), Dispatch)

    clock.advance(LEASE - 1)
    assert replay.admit(entry(RERUN)) == InProgress()
    clock.advance(1)
    reclaimed = replay.admit(entry(RERUN))
    assert isinstance(reclaimed, Dispatch) and reclaimed.exact_retry is True
    assert replay.admit(entry(RERUN)) == InProgress()


def test_a_recorded_request_answers_its_exact_retry_with_the_recorded_response(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RECORDED))
    assert isinstance(first, Dispatch)
    replay.complete(first.attempt, OUTCOME)

    clock.advance(RETENTION - 1)
    assert replay.admit(entry(RECORDED)) == Answered(OUTCOME)


def test_a_recorded_attempt_is_never_dispatched_again_and_its_ended_lease_is_outcome_unknown(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    assert isinstance(replay.admit(entry(RECORDED)), Dispatch)

    clock.advance(LEASE - 1)
    assert replay.admit(entry(RECORDED)) == InProgress()
    clock.advance(1)
    assert replay.admit(entry(RECORDED)) == OutcomeUnknown()
    clock.advance(SKEW)
    assert replay.admit(entry(RECORDED)) == OutcomeUnknown()


def test_a_recorded_retry_older_than_the_retention_is_expired_even_with_its_row(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RECORDED))
    assert isinstance(first, Dispatch)
    replay.complete(first.attempt, OUTCOME)

    clock.advance(RETENTION + 1)
    assert store.get("scheme:caller-1", "request-1", now=clock()) is not None
    assert replay.admit(entry(RECORDED)) == Expired()


def test_a_recorded_request_with_an_origin_older_than_the_skew_and_no_row_is_expired(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)

    assert replay.admit(entry(RECORDED, origin=START - SKEW - 1)) == Expired()
    assert store.get("scheme:caller-1", "request-1", now=clock()) is None
    first_use = replay.admit(entry(RECORDED, origin=START - SKEW))
    assert isinstance(first_use, Dispatch) and first_use.exact_retry is False


def test_a_rerun_request_with_an_old_origin_and_no_row_is_dispatched(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)

    resent = replay.admit(entry(RERUN, origin=START - 6 * 3600))
    assert isinstance(resent, Dispatch) and resent.exact_retry is True


def test_each_row_expires_at_its_bound_from_the_origin(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    replay.admit(entry(RERUN, request_id="rerun"))
    replay.admit(entry(RECORDED, request_id="recorded"))

    assert store.get("scheme:caller-1", "rerun", now=clock()).expires_at == START + 2 * SKEW
    assert store.get("scheme:caller-1", "recorded", now=clock()).expires_at == START + RETENTION + SKEW


def test_a_row_whose_bound_has_passed_expires_at_its_lease_end(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)

    replay.admit(entry(RERUN, origin=START - 3600))

    assert store.get("scheme:caller-1", "request-1", now=clock()).expires_at == START + LEASE


def test_a_reclaimed_lease_raises_the_expiry(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    replay.admit(entry(RERUN, origin=START - 3600))

    clock.advance(LEASE)
    assert isinstance(replay.admit(entry(RERUN, origin=START - 3600)), Dispatch)

    assert store.get("scheme:caller-1", "request-1", now=clock()).expires_at == START + 2 * LEASE


def test_a_renewed_lease_is_extended_and_raises_the_expiry(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RERUN, origin=START - 3600))
    assert isinstance(first, Dispatch)

    assert first.attempt.lease_until == START + LEASE
    clock.advance(LEASE - 1)
    assert replay.renew(first.attempt) == START + 2 * LEASE - 1

    row = store.get("scheme:caller-1", "request-1", now=clock())
    assert row.lease_until == START + 2 * LEASE - 1
    assert row.expires_at == START + 2 * LEASE - 1


def test_an_ended_lease_is_not_renewed(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RECORDED))
    assert isinstance(first, Dispatch)

    clock.advance(LEASE)
    assert replay.renew(first.attempt) is None
    assert replay.admit(entry(RECORDED)) == OutcomeUnknown()


def test_an_expired_row_answers_nothing_and_a_reservation_replaces_it(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RERUN))
    assert isinstance(first, Dispatch)
    replay.complete(first.attempt, OUTCOME)

    clock.advance(2 * SKEW)
    assert store.get("scheme:caller-1", "request-1", now=clock()) is None
    changed = replay.admit(entry(RERUN, request_hash="hash-b", origin=clock()))
    assert isinstance(changed, Dispatch) and changed.exact_retry is False


def test_an_origin_ahead_of_the_clock_is_bounded_from_that_origin(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    ahead = START + 900

    assert isinstance(replay.admit(entry(RERUN, origin=ahead)), Dispatch)
    assert store.get("scheme:caller-1", "request-1", now=clock()).expires_at == ahead + 2 * SKEW


def test_the_sweep_deletes_only_expired_rows(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    replay.admit(entry(RERUN, request_id="short"))
    replay.admit(entry(RECORDED, request_id="long"))

    clock.advance(2 * SKEW)
    assert replay.sweep() == 1
    assert store.get("scheme:caller-1", "long", now=clock()) is not None
    assert replay.sweep() == 0


def test_completing_an_attempt_that_lost_its_row_changes_nothing(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RERUN))
    assert isinstance(first, Dispatch)
    clock.advance(LEASE)
    second = replay.admit(entry(RERUN))
    assert isinstance(second, Dispatch)

    replay.complete(first.attempt, OUTCOME)

    assert store.get("scheme:caller-1", "request-1", now=clock()).lease_owner == second.attempt.owner


def test_a_retry_after_the_lease_ends_concludes_the_attempt_keeping_its_owner(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RECORDED))
    assert isinstance(first, Dispatch)

    clock.advance(LEASE)
    assert replay.admit(entry(RECORDED)) == OutcomeUnknown()

    row = store.get("scheme:caller-1", "request-1", now=clock())
    assert (row.lease_until, row.lease_owner, row.outcome) == (None, first.attempt.owner, None)
    assert replay.admit(entry(RECORDED)) == OutcomeUnknown()


def test_a_concluded_attempts_late_outcome_is_recorded_and_answers_a_later_retry(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RECORDED))
    assert isinstance(first, Dispatch)
    clock.advance(LEASE)
    assert replay.admit(entry(RECORDED)) == OutcomeUnknown()

    replay.complete(first.attempt, OUTCOME)

    assert replay.admit(entry(RECORDED)) == Answered(OUTCOME)


def test_a_renewal_after_conclusion_revives_nothing(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RECORDED))
    assert isinstance(first, Dispatch)
    clock.advance(LEASE)
    assert replay.admit(entry(RECORDED)) == OutcomeUnknown()

    assert replay.renew(first.attempt) is None
    assert store.get("scheme:caller-1", "request-1", now=clock()).lease_until is None
    assert replay.admit(entry(RECORDED)) == OutcomeUnknown()


def test_an_outcome_recorded_before_the_concluding_write_is_answered(store) -> None:
    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RECORDED))
    assert isinstance(first, Dispatch)
    clock.advance(LEASE)

    racing = RecordingFirst(store, lambda: replay.complete(first.attempt, OUTCOME))

    assert guard(racing, clock).admit(entry(RECORDED)) == Answered(OUTCOME)
    assert racing.recorded


REPLACEMENT = Outcome(status=201, headers=(("content-type", "application/json"),), body=b'{"other":true}')


def _retry_meeting_a_replacement(store, *, record: bool):
    """An ended attempt's retry that reads its row on the last instant of its
    retention, then meets the row expired and its key taken by another request,
    recorded or still running, before its concluding write."""

    clock = ManualClock()
    replay = guard(store, clock)
    first = replay.admit(entry(RECORDED))
    assert isinstance(first, Dispatch)

    later = ManualClock(store.get("scheme:caller-1", "request-1", now=clock()).expires_at)
    other = guard(store, later)
    replacement = entry(RECORDED, request_hash="hash-b", origin=later())

    taken_row = []

    def take() -> None:
        taken = other.admit(replacement)
        assert isinstance(taken, Dispatch)
        if record:
            other.complete(taken.attempt, REPLACEMENT)
        taken_row.append(store.get("scheme:caller-1", "request-1", now=later()))

    clock.now = START + RETENTION
    admission = guard(TakenFirst(store, take), clock).admit(entry(RECORDED))
    return admission, taken_row[0], store.get("scheme:caller-1", "request-1", now=later())


def test_a_retry_whose_key_another_request_took_and_recorded_is_expired(store) -> None:
    admission, before, after = _retry_meeting_a_replacement(store, record=True)

    assert admission == Expired()
    assert after == before and after.request_hash == "hash-b" and after.outcome == REPLACEMENT


def test_a_retry_whose_key_another_request_holds_is_expired_leaving_its_lease(store) -> None:
    admission, before, after = _retry_meeting_a_replacement(store, record=False)

    assert admission == Expired()
    assert after == before and after.request_hash == "hash-b" and after.lease_until is not None


def test_the_concluding_write_leaves_another_requests_row_and_answers_none(store) -> None:
    clock = ManualClock()
    first = guard(store, clock).admit(entry(RECORDED))
    assert isinstance(first, Dispatch)
    later = ManualClock(store.get("scheme:caller-1", "request-1", now=clock()).expires_at)
    taken = guard(store, later).admit(entry(RECORDED, request_hash="hash-b", origin=later()))
    assert isinstance(taken, Dispatch)
    later.advance(LEASE)
    before = store.get("scheme:caller-1", "request-1", now=later())

    # At this instant the replacement's own lease has ended, so only the request's
    # identity keeps the write off it.
    assert store.conclude(entry(RECORDED), now=later()) is None
    assert store.get("scheme:caller-1", "request-1", now=later()) == before
