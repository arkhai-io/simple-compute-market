"""The lease lifecycle over fake ports: what it does with each release decision.

The release executor's decision (teardown, free, create in flight, unreleasable)
and the status port's progress are scripted, and the site authority's guard is
a switch, so each path is driven without a database. The decisions themselves,
by aggregate state, are ``test_release.py``'s.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from compute_provisioning.lease_lifecycle import (
    InvalidLeaseStateError,
    LeaseLifecycleService,
)
from compute_provisioning.release import (
    ReleaseAction,
    ReleaseDecision,
    ReleaseProgress,
    ReleaseStatus,
)

_PAST = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
_FUTURE = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()


class FakeSiteAuthority:
    """A site whose release guard is a switch: ``permit_release``."""

    def __init__(self, *, state="leased", lease_end=_PAST):
        self.reservations = {
            "alloc-1": {
                "capacity_reservation_id": "alloc-1",
                "offering_mode": "bare_metal",
                "state": state,
                "lease_end_utc": lease_end,
            }
        }
        self.permit_release = True
        self.due = []

    def get_reservation(self, capacity_reservation_id):
        return self.reservations.get(capacity_reservation_id)

    def list_reservations(self, *, state=None):
        return [r for r in self.reservations.values() if state is None or r["state"] == state]

    def list_time_bounded_reservations_due(self, now):
        return self.due

    def begin_release(self, capacity_reservation_id, *, release_job_id):
        reservation = self.reservations[capacity_reservation_id]
        reservation.update(state="releasing", release_job_id=release_job_id)
        return reservation

    def record_release_failure(self, capacity_reservation_id, *, reason, message=None):
        reservation = self.reservations[capacity_reservation_id]
        reservation.update(state="release_failed", failure_reason=reason, failure_message=message)
        return reservation

    def record_release_success(self, capacity_reservation_id, *, forced=False, reason=None, message=None):
        if not forced and not self.permit_release:
            return None
        reservation = self.reservations[capacity_reservation_id]
        reservation.update(state="force_released" if forced else "released", failure_reason=reason)
        return reservation

    def record_unmanaged(self, capacity_reservation_id, *, reason, message=None):
        reservation = self.reservations[capacity_reservation_id]
        reservation.update(state="unmanaged", failure_reason=reason)
        return reservation


class ScriptedExecutor:
    """Returns its decisions in turn, repeating the last; records teardowns begun."""

    def __init__(self, *decisions: ReleaseDecision):
        self.decisions = list(decisions)
        self.asked = 0
        self.teardowns: list[str] = []

    async def submit_release(self, reservation):
        decision = self.decisions[min(self.asked, len(self.decisions) - 1)]
        self.asked += 1
        return decision

    async def begin_teardown(self, fulfillment_id):
        self.teardowns.append(fulfillment_id)
        return fulfillment_id


class ScriptedStatus:
    def __init__(self, status: ReleaseStatus | None = None):
        self.status = status or ReleaseStatus(ReleaseProgress.TEARING_DOWN)

    def get_status(self, fulfillment_id):
        return self.status


class RecordingNotifier:
    def __init__(self):
        self.released: list[str] = []

    def __call__(self, reservation):
        self.released.append(reservation["capacity_reservation_id"])
        return True


def _lifecycle(site, executor, status=None, notifier=None, grace=300):
    return LeaseLifecycleService(
        SimpleNamespace(lease_watchdog_grace_period_seconds=grace),
        site,
        release_executor=executor,
        release_status=status or ScriptedStatus(),
        capacity_released_notifier=notifier,
    )


def _decision(action: ReleaseAction, fulfillment_id: str | None = "f-1", **fields):
    return ReleaseDecision(action, fulfillment_id=fulfillment_id, **fields)


@pytest.mark.asyncio
async def test_terminate_begins_teardown_and_keeps_capacity_held():
    site = FakeSiteAuthority(lease_end=_FUTURE)
    lifecycle = _lifecycle(site, ScriptedExecutor(_decision(ReleaseAction.TEARDOWN)))

    lease = await lifecycle.terminate_lease("alloc-1")

    assert (lease["state"], lease["release_job_id"]) == ("releasing", "f-1")


@pytest.mark.asyncio
async def test_a_lease_nothing_was_delivered_against_is_released_directly_and_notified():
    site = FakeSiteAuthority()
    notifier = RecordingNotifier()
    lifecycle = _lifecycle(site, ScriptedExecutor(_decision(ReleaseAction.FREE)), notifier=notifier)
    site.due = [site.reservations["alloc-1"]]

    result = await lifecycle.check_leases()

    assert result["released"] == 1
    assert site.reservations["alloc-1"]["state"] == "released"
    assert notifier.released == ["alloc-1"]


@pytest.mark.asyncio
async def test_a_refused_direct_release_follows_the_aggregate_s_new_state():
    """The guard refuses because a dispatch won the race; asked again, the
    executor sees the create in flight, and the lease waits for it."""
    site = FakeSiteAuthority()
    site.permit_release = False
    executor = ScriptedExecutor(
        _decision(ReleaseAction.FREE), _decision(ReleaseAction.CREATE_IN_FLIGHT)
    )
    lifecycle = _lifecycle(site, executor)

    await lifecycle.terminate_lease("alloc-1")

    assert executor.asked == 2
    assert (site.reservations["alloc-1"]["state"], site.reservations["alloc-1"]["release_job_id"]) == (
        "releasing",
        "f-1",
    )


@pytest.mark.asyncio
async def test_a_direct_release_refused_twice_is_left_for_an_operator():
    site = FakeSiteAuthority()
    site.permit_release = False
    lifecycle = _lifecycle(site, ScriptedExecutor(_decision(ReleaseAction.FREE)))

    await lifecycle.terminate_lease("alloc-1")

    reservation = site.reservations["alloc-1"]
    assert (reservation["state"], reservation["failure_reason"]) == (
        "release_failed",
        "release_unproven",
    )


@pytest.mark.asyncio
async def test_an_unreleasable_lease_records_the_fulfillment_s_reason():
    site = FakeSiteAuthority()
    lifecycle = _lifecycle(
        site,
        ScriptedExecutor(
            _decision(ReleaseAction.UNRELEASABLE, reason="fulfillment_failed", message="boom")
        ),
    )

    await lifecycle.terminate_lease("alloc-1")

    reservation = site.reservations["alloc-1"]
    assert (reservation["state"], reservation["failure_reason"], reservation["failure_message"]) == (
        "release_failed",
        "fulfillment_failed",
        "boom",
    )


@pytest.mark.asyncio
async def test_a_release_waiting_on_a_create_survives_a_restarted_lifecycle():
    """The wait is the reservation's ``releasing`` state and its handle, both
    durable: a new lifecycle over the same site resumes it, and begins
    teardown once the create settles."""
    site = FakeSiteAuthority()
    await _lifecycle(
        site, ScriptedExecutor(_decision(ReleaseAction.CREATE_IN_FLIGHT))
    ).terminate_lease("alloc-1")

    status = ScriptedStatus(ReleaseStatus(ReleaseProgress.CREATE_IN_FLIGHT))
    executor = ScriptedExecutor(_decision(ReleaseAction.TEARDOWN))
    restarted = _lifecycle(site, executor, status, grace=0)

    waiting = await restarted.check_leases()
    status.status = ReleaseStatus(ReleaseProgress.READY_FOR_TEARDOWN)
    began = await restarted.check_leases()

    assert waiting["release_failed"] == 0
    assert began["release_failed"] == 0
    assert executor.teardowns == ["f-1"]
    assert site.reservations["alloc-1"]["state"] == "releasing"


@pytest.mark.asyncio
async def test_no_grace_timeout_runs_while_the_create_is_in_flight():
    site = FakeSiteAuthority(state="releasing")
    site.reservations["alloc-1"]["release_job_id"] = "f-1"
    status = ScriptedStatus(ReleaseStatus(ReleaseProgress.CREATE_IN_FLIGHT))
    lifecycle = _lifecycle(site, ScriptedExecutor(_decision(ReleaseAction.TEARDOWN)), status, grace=0)

    await lifecycle.check_leases()

    assert site.reservations["alloc-1"]["state"] == "releasing"

    status.status = ReleaseStatus(ReleaseProgress.TEARING_DOWN)
    await lifecycle.check_leases()

    assert site.reservations["alloc-1"]["failure_reason"] == "teardown_timeout"


@pytest.mark.asyncio
async def test_a_torn_down_fulfillment_releases_the_lease():
    site = FakeSiteAuthority(state="releasing")
    site.reservations["alloc-1"]["release_job_id"] = "f-1"
    notifier = RecordingNotifier()
    lifecycle = _lifecycle(
        site,
        ScriptedExecutor(_decision(ReleaseAction.TEARDOWN)),
        ScriptedStatus(ReleaseStatus(ReleaseProgress.TORN_DOWN)),
        notifier,
    )

    result = await lifecycle.check_leases()

    assert result["released"] == 1
    assert notifier.released == ["alloc-1"]


@pytest.mark.asyncio
async def test_a_failed_teardown_waits_for_an_operator_whose_retry_adopts_it():
    """``teardown_failed`` ends the lease in ``release_failed`` while
    convergence keeps retrying; once the aggregate is torn down, the operator's
    retry-release adopts it and the capacity returns."""
    site = FakeSiteAuthority(state="releasing")
    site.reservations["alloc-1"]["release_job_id"] = "f-1"
    status = ScriptedStatus(
        ReleaseStatus(ReleaseProgress.FAILED, reason="teardown_failed", error="unreachable")
    )
    lifecycle = _lifecycle(site, ScriptedExecutor(_decision(ReleaseAction.FREE)), status)

    await lifecycle.check_leases()
    assert site.reservations["alloc-1"]["failure_reason"] == "teardown_failed"

    lease = await lifecycle.retry_release("alloc-1")

    assert lease["state"] == "released"


@pytest.mark.asyncio
async def test_terminate_refuses_a_lease_an_operator_must_repair():
    site = FakeSiteAuthority(state="release_failed")
    lifecycle = _lifecycle(site, ScriptedExecutor(_decision(ReleaseAction.TEARDOWN)))

    with pytest.raises(InvalidLeaseStateError):
        await lifecycle.terminate_lease("alloc-1")


@pytest.mark.asyncio
async def test_force_release_is_the_operator_s_override_whatever_the_guard_says():
    site = FakeSiteAuthority(state="release_failed")
    site.permit_release = False
    lifecycle = _lifecycle(site, ScriptedExecutor(_decision(ReleaseAction.TEARDOWN)))

    released = await lifecycle.force_release(
        "alloc-1", SimpleNamespace(reason="host verified empty", evidence="console")
    )

    assert released["state"] == "force_released"
