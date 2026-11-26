"""Compute lease, watchdog, retry, and force-release orchestration."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, Protocol
from datetime import datetime, timedelta, timezone

import injected_time
from market_site.authority import SiteAuthorityPort

from .operator_events import lease_release_failed_draft
from .release import (
    BoundJobReader,
    ReleaseAction,
    ReleaseDecision,
    ReleaseProgress,
    ReleaseStatus,
    TeardownRefused,
)

logger = logging.getLogger(__name__)

ParseUtc = Callable[[Any], datetime | None]
DeliverEvents = Callable[[], Awaitable[Any]]


class LeaseLifecycleError(Exception):
    """Base class for lease lifecycle command errors."""


class LeaseNotFoundError(LeaseLifecycleError):
    """Raised when a lease/reservation id does not exist."""


class InvalidLeaseStateError(LeaseLifecycleError):
    """Raised when a lifecycle command is invalid for the current state."""

    def __init__(self, message: str, *, state: str | None = None) -> None:
        super().__init__(message)
        self.state = state


def parse_utc(value: Any) -> datetime | None:
    """Parse common UTC datetime values used in reservation records."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _datetime_value(value: Any) -> str | None:
    if value is None:
        return None
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _handle_read(reservation: dict[str, Any]) -> str | None:
    """The release handle a reservation carried when it was read, if releasing."""
    if str(reservation.get("state")) != "releasing":
        return None
    handle = reservation.get("release_job_id")
    return None if handle is None else str(handle)


class ReleaseExecutorPort(Protocol):
    """Decides a reservation's release and begins or adopts its teardown."""

    async def submit_release(self, reservation: dict[str, Any]) -> ReleaseDecision: ...

    async def begin_teardown(self, fulfillment_id: str) -> str:
        """Raises ``TeardownRefused`` for a permanent refusal; any other error
        is transient."""
        ...


class ReleaseStatusPort(Protocol):
    """Reads a releasing lease's progress by its release handle."""

    def get_status(self, fulfillment_id: str) -> ReleaseStatus: ...


class LeaseLifecycleService:
    """Lease lifecycle state machine over site reservations, for every mode.

    The lifecycle owns ``releasing``, the terminal release states, and the final
    capacity return. What a release does follows the reservation's fulfillment
    aggregate (``release.py``): it begins or adopts teardown, frees capacity
    through the site's guarded release when nothing was delivered, waits while
    a create is in flight, or leaves the lease for an operator. A release waiting on an in-flight create
    is ``releasing`` with the fulfillment as its release handle, so it survives
    a restart and a second request finds it.

    Every transition into ``release_failed`` carries a prepared
    ``provisioning.lease_release_failed`` event, which the site records in that
    transition's transaction and drops with a refused one. It names the
    reservation's latest teardown job and that job's failure class, read from
    ``jobs`` when the composition gives the job authority's read.

    The site records a lease's end and its capacity's release as events, in the
    transitions' own transactions, and the storefront peer's consumers deliver
    them: the signed lease-end report and the capacity-released callback. A
    command or watchdog cycle that made a transition calls ``deliver_events``
    before it returns, so what it recorded leaves for the storefront within it;
    a delivery that fails is retried by the event delivery worker, never here.
    """

    TERMINAL_SUCCESS_STATES = {"released", "force_released"}
    TERMINAL_FAILURE_STATES = {"release_failed", "unmanaged"}

    def __init__(
        self,
        settings: Any,
        site_authority: SiteAuthorityPort,
        *,
        release_executor: ReleaseExecutorPort,
        release_status: ReleaseStatusPort,
        parse_utc_value: ParseUtc = parse_utc,
        deliver_events: DeliverEvents | None = None,
        jobs: BoundJobReader | None = None,
    ) -> None:
        self._settings = settings
        self._jobs = jobs
        self._deliver_events_now = deliver_events
        self._site_authority = site_authority
        self._release_executor = release_executor
        self._release_status = release_status
        self._parse_utc = parse_utc_value
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()
        # Timer cycles past the gate and not yet finished. A pause stops new
        # ones at the gate; one already running finishes first.
        self._timer_cycles_in_flight = 0

    def pause(self) -> None:
        self._paused = True
        self._resume_event.clear()
        logger.info("[LEASE_LIFECYCLE] Watchdog paused — timer cycles will block")

    def resume(self) -> None:
        self._paused = False
        self._resume_event.set()
        logger.info("[LEASE_LIFECYCLE] Watchdog resumed")

    @property
    def is_paused(self) -> bool:
        return not self._resume_event.is_set()

    @property
    def is_at_gate(self) -> bool:
        """Paused with no timer cycle running, so none can run until resumed.

        A timer cycle that passed the gate before the pause keeps running to
        its end; until it does the watchdog is paused but not yet held, and a
        caller holding it waits for this. An explicit ``force_check_leases``
        is the caller's own and does not count.
        """
        return self.is_paused and self._timer_cycles_in_flight == 0

    def get_lease(self, lease_id: str) -> dict[str, Any]:
        reservation = self._site_authority.get_reservation(lease_id)
        if reservation is None:
            raise LeaseNotFoundError(f"Lease '{lease_id}' not found")
        return reservation

    async def terminate_lease(self, lease_id: str, body: Any | None = None, *, caller: dict | None = None) -> dict[str, Any]:
        """Release a leased reservation now, as its expiry would.

        A lease already releasing or released is returned as it is; one an
        operator holds (``release_failed``, ``unmanaged``) needs repair first.
        """
        reservation = self.get_lease(lease_id)
        state = str(reservation.get("state"))
        if state in self.TERMINAL_SUCCESS_STATES or state == "releasing":
            return reservation
        if state in {"release_failed", "unmanaged"}:
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; admin repair is required.",
                state=state,
            )
        if state != "leased":
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; only leased reservations can be terminated.",
                state=state,
            )
        await self._request_release(reservation, end_context={
            "cause": "termination", "reason": getattr(body, "reason", None), "caller": caller,
            "effective_at": injected_time.now(),
        })
        await self._deliver_events()
        return self.get_lease(lease_id)

    def release_oversight(self, lease_id: str, body: Any) -> dict[str, Any]:
        reservation = self.get_lease(lease_id)
        state = str(reservation.get("state"))
        if state == "unmanaged":
            return reservation
        if state != "leased":
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; only leased reservations can release oversight.",
                state=state,
            )
        handed = self._site_authority.record_unmanaged(
            lease_id,
            reason="oversight_released",
            message=body.reason,
        )
        if handed is not None:
            return handed
        # The lease changed between the read and the hand-over (the lifecycle
        # began releasing it, say); the site refused and wrote nothing.
        current = self.get_lease(lease_id)
        state = str(current.get("state"))
        if state == "unmanaged":
            return current
        raise InvalidLeaseStateError(
            f"Lease '{lease_id}' is {state}; only leased reservations can release oversight.",
            state=state,
        )

    async def retry_release(self, lease_id: str, body: Any | None = None) -> dict[str, Any]:
        """Ask the fulfillment again: adopt its teardown, or free what it proves free."""
        reservation = self.get_lease(lease_id)
        state = str(reservation.get("state"))
        if state != "release_failed":
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; only release_failed leases can retry release.",
                state=state,
            )
        await self._request_release(reservation)
        await self._deliver_events()
        return self.get_lease(lease_id)

    async def force_release(self, lease_id: str, body: Any, *, caller: dict | None = None) -> dict[str, Any]:
        reservation = self.get_lease(lease_id)
        state = str(reservation.get("state"))
        if state in self.TERMINAL_SUCCESS_STATES:
            return reservation
        allowed = {"leased", "releasing", "release_failed", "unmanaged"}
        if state not in allowed:
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; force-release is only valid for {sorted(allowed)}.",
                state=state,
            )
        message = body.reason
        if body.evidence:
            message = f"{body.reason} Evidence: {body.evidence}"
        released = self._site_authority.record_release_success(
            lease_id,
            forced=True,
            reason="admin_force_release",
            end_context={"cause": "force_release", "reason": message, "caller": caller},
            message=message,
        )
        if released is None:
            raise LeaseNotFoundError(f"Lease '{lease_id}' not found or is not held.")
        await self._deliver_events()
        return released

    async def check_leases(self) -> dict:
        """The timer's cycle: blocks at the gate while paused.

        The gate is read again after each wake: a resume and a pause in quick
        succession wake the waiter with the watchdog paused again, and a pause
        that answered "at the gate" must hold that cycle back. Nothing awaits
        between the last read and the count, so no pause can read the gate in
        between.
        """
        while not self._resume_event.is_set():
            logger.debug("[LEASE_LIFECYCLE] Cycle blocked — watchdog is paused")
            await self._resume_event.wait()
        self._timer_cycles_in_flight += 1
        try:
            return await self._run_cycle()
        finally:
            self._timer_cycles_in_flight -= 1

    async def force_check_leases(self) -> dict:
        return await self._run_cycle()

    async def _run_cycle(self) -> dict:
        now = injected_time.now_datetime()
        grace_seconds = int(
            getattr(self._settings, "lease_watchdog_grace_period_seconds", 3600)
        )

        checked = 0
        released = 0
        release_failed = 0
        skipped = 0

        for reservation in self._site_authority.list_time_bounded_reservations_due(now):
            try:
                outcome = await self._request_release(reservation)
            except Exception as exc:
                logger.exception(
                    "[LEASE_LIFECYCLE] Failed to begin release for reservation %s: %s",
                    reservation.get("capacity_reservation_id"), exc,
                )
                if (
                    self._mark_release_failed(
                        reservation,
                        reason="release_submit_error",
                        message=str(exc),
                        expected_handle=_handle_read(reservation),
                    )
                    == "release_failed"
                ):
                    release_failed += 1
                else:
                    skipped += 1
                continue
            if outcome == "releasing":
                checked += 1
            elif outcome == "released":
                released += 1
            elif outcome == "release_failed":
                release_failed += 1
            else:
                skipped += 1

        for reservation in self._site_authority.list_reservations(state="releasing"):
            try:
                outcome = await self._process_releasing_reservation(
                    reservation, now, grace_seconds,
                )
                if outcome == "released":
                    released += 1
                elif outcome == "release_failed":
                    release_failed += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.exception(
                    "[LEASE_LIFECYCLE] Unhandled error processing releasing reservation %s: %s",
                    reservation.get("capacity_reservation_id"), exc,
                )
                skipped += 1

        if checked or released or release_failed:
            await self._deliver_events()
            logger.info(
                "[LEASE_LIFECYCLE] Cycle: checked=%d released=%d release_failed=%d skipped=%d",
                checked, released, release_failed, skipped,
            )
        return {
            "checked": checked,
            "released": released,
            "release_failed": release_failed,
            "skipped": skipped,
        }

    async def _request_release(self, reservation: dict[str, Any], *, end_context: dict | None = None) -> str:
        """Act on the fulfillment's decision; return the lease's resulting state.

        A direct release the site's guard refuses means the aggregate moved
        between the decision and the release (a dispatch won a race), so the
        decision is taken once more and followed; refused again, nothing proves
        the capacity free, and an operator must verify.
        """
        capacity_reservation_id = reservation["capacity_reservation_id"]
        if end_context is None:
            deadline = self._parse_utc(reservation.get("lease_end_utc"))
            now = injected_time.now_datetime()
            end_context = ({
                "cause": "expiry", "effective_at": int(deadline.timestamp()),
                "claimed_deadline": int(deadline.timestamp()), "deadline_phase": "lease",
            } if deadline is not None and deadline <= now else {"cause": "release"})
        decision = await self._release_executor.submit_release(reservation)
        if decision.action is ReleaseAction.FREE:
            if await self._finish_release(reservation, end_context=end_context):
                return "released"
            decision = await self._release_executor.submit_release(reservation)
            if decision.action is ReleaseAction.FREE:
                if await self._finish_release(reservation, end_context=end_context):
                    return "released"
                return self._mark_release_failed(
                    reservation,
                    reason="release_unproven", end_context=end_context,
                    message=(
                        "nothing is left to tear down, but the reservation's "
                        "provenance does not prove that nothing was dispatched"
                    ),
                    expected_handle=_handle_read(reservation),
                )
        if decision.action in (ReleaseAction.TEARDOWN, ReleaseAction.CREATE_IN_FLIGHT):
            # Recorded first: a crash before teardown begins leaves a lease the
            # releasing pass resumes, never a teardown the lease knows nothing of.
            began = self._site_authority.begin_release(
                capacity_reservation_id,
                release_job_id=str(decision.fulfillment_id), end_context=end_context,
            )
            if began is None:
                return self._yield_to_current_state(capacity_reservation_id, "begin releasing")
            logger.info(
                "[LEASE_LIFECYCLE] Reservation %s releasing under fulfillment %s (%s)",
                capacity_reservation_id,
                decision.fulfillment_id,
                decision.action.value,
            )
            if decision.action is ReleaseAction.TEARDOWN:
                return await self._begin_recorded_teardown(
                    reservation, str(decision.fulfillment_id), end_context=end_context,
                )
            return "releasing"
        return self._mark_release_failed(
            reservation,
            reason=decision.reason or "release_unproven", end_context=end_context,
            message=decision.message,
            expected_handle=_handle_read(reservation),
        )

    async def _begin_recorded_teardown(
        self, reservation: dict[str, Any], fulfillment_id: str, *, end_context: dict | None = None,
    ) -> str:
        """Begin the teardown of a release already recorded as ``releasing``.

        A refusal is permanent for the aggregate as it stands, so the release is
        failed under ``fulfillment_id``, the handle just recorded: the
        reservation was read before that write, so its own handle is not this
        release's. Any other failure is not the release's failure: the release
        is durable, and the releasing pass begins the teardown on a later cycle
        when the aggregate is still ready for it.
        """
        capacity_reservation_id = reservation["capacity_reservation_id"]
        try:
            await self._release_executor.begin_teardown(fulfillment_id)
        except TeardownRefused as refused:
            return self._mark_release_failed(
                reservation,
                reason=refused.reason,
                message=refused.message,
                expected_handle=fulfillment_id,
                end_context=end_context,
            )
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Teardown of fulfillment %s for reservation %s "
                "did not begin; the releasing pass retries it: %s",
                fulfillment_id,
                capacity_reservation_id,
                exc,
            )
        return "releasing"

    async def _process_releasing_reservation(
        self, reservation: dict[str, Any], now: datetime, grace_seconds: int
    ) -> str:
        fulfillment_id = reservation.get("release_job_id")
        if not fulfillment_id:
            return self._mark_release_failed(
                reservation,
                reason="teardown_failed",
                message="the releasing reservation records no release handle",
                expected_handle=None,
            )

        try:
            status = self._release_status.get_status(str(fulfillment_id))
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Could not read fulfillment %s for reservation %s: %s",
                fulfillment_id, reservation["capacity_reservation_id"], exc,
            )
            status = None

        if status is not None:
            if status.progress is ReleaseProgress.TORN_DOWN:
                if not await self._finish_release(reservation):
                    return "skipped"
                return "released"
            if status.progress is ReleaseProgress.FAILED:
                return self._mark_release_failed(
                    reservation,
                    reason=status.reason or "teardown_failed",
                    message=status.error,
                    expected_handle=str(fulfillment_id),
                )
            if status.progress is ReleaseProgress.READY_FOR_TEARDOWN:
                try:
                    await self._release_executor.begin_teardown(str(fulfillment_id))
                except TeardownRefused as refused:
                    return self._mark_release_failed(
                        reservation,
                        reason=refused.reason,
                        message=refused.message,
                        expected_handle=str(fulfillment_id),
                    )
                except Exception as exc:
                    # A transient failure to begin is retried on the next
                    # cycle, but only until the grace period passes: a begin
                    # that keeps failing is a stuck release like any other.
                    logger.warning(
                        "[LEASE_LIFECYCLE] Teardown of fulfillment %s for reservation %s "
                        "did not begin; the releasing pass retries it within the grace: %s",
                        fulfillment_id,
                        reservation["capacity_reservation_id"],
                        exc,
                    )
                else:
                    return "skipped"
            if status.progress is ReleaseProgress.CREATE_IN_FLIGHT:
                # Waiting on a create is not a stalled teardown: the grace
                # period starts counting only once there is a teardown to wait on.
                return "skipped"

        # A stalled teardown is timed from when this release began, not from
        # the lease's end: a lease terminated long before its end would
        # otherwise wait that long, and one that ended long ago would time out
        # as its teardown began. A reservation that entered ``releasing``
        # before the start was recorded is timed from its end.
        began = (
            self._parse_utc(reservation.get("release_requested_at"))
            or self._parse_utc(reservation.get("lease_end_utc"))
            or now
        )
        if now < began + timedelta(seconds=grace_seconds):
            return "skipped"
        return self._mark_release_failed(
            reservation,
            reason="teardown_timeout",
            message="teardown did not complete before the watchdog grace period elapsed",
            expected_handle=str(fulfillment_id),
        )

    def _mark_release_failed(
        self,
        reservation: dict[str, Any],
        *,
        reason: str,
        message: str | None,
        expected_handle: str | None,
        end_context: dict | None = None,
    ) -> str:
        """Record the release as failed, unless the reservation moved on.

        A releasing reservation is failed only under ``expected_handle``, the
        release the failure was observed for, so a failure observed for one
        release attempt cannot land on another; ``None`` names no release, for
        a reservation read before any. Each caller names the handle because
        only it knows which release it observed. The site refuses a failure for
        a reservation an operator took over or force-released, or that was
        released; the lifecycle then leaves it as it is.
        """
        capacity_reservation_id = reservation["capacity_reservation_id"]
        teardown_job_id, failure_class = self._latest_teardown(capacity_reservation_id)
        recorded = self._site_authority.record_release_failure(
            capacity_reservation_id,
            reason=reason,
            message=message,
            release_job_id=expected_handle,
            end_context={**(end_context or {}), "cause": "release_failed", "reason": message or reason},
            event=lease_release_failed_draft(
                capacity_reservation_id=capacity_reservation_id,
                reason=reason,
                message=message,
                release_handle=expected_handle,
                offering_mode=_optional_str(reservation.get("offering_mode")),
                teardown_job_id=teardown_job_id,
                failure_class=failure_class,
            ),
        )
        if recorded is None:
            return self._yield_to_current_state(capacity_reservation_id, "record a failure")
        logger.error(
            "[LEASE_LIFECYCLE] Release failed for reservation %s: %s %s",
            capacity_reservation_id, reason, message or "",
        )
        return "release_failed"

    def _latest_teardown(self, capacity_reservation_id: str) -> tuple[str | None, str | None]:
        """The reservation's latest teardown job and its failure class, if any."""
        if self._jobs is None:
            return None, None
        jobs = self._jobs.bound_jobs(capacity_reservation_id, "teardown")
        if not jobs:
            return None, None
        return jobs[-1].job_id, jobs[-1].failure_class

    def _yield_to_current_state(self, capacity_reservation_id: str, write: str) -> str:
        """Honour a state another actor recorded since this cycle read the lease."""
        current = self._site_authority.get_reservation(capacity_reservation_id) or {}
        logger.info(
            "[LEASE_LIFECYCLE] Reservation %s is now %s; the site refused to %s for "
            "a stale read, and the lifecycle leaves it as it is",
            capacity_reservation_id,
            current.get("state", "absent"),
            write,
        )
        return "skipped"

    async def _finish_release(self, reservation: dict[str, Any], *, end_context: dict | None = None) -> bool:
        capacity_reservation_id = reservation["capacity_reservation_id"]
        released = self._site_authority.record_release_success(
            capacity_reservation_id, end_context=end_context,
        )
        if released is None:
            return False
        logger.info(
            "[LEASE_LIFECYCLE] Reservation %s released (resource=%s escrow=%s)",
            capacity_reservation_id,
            reservation.get("resource_id"),
            reservation.get("escrow_uid"),
        )
        return True

    async def _deliver_events(self) -> None:
        """Deliver what this command's transitions recorded for the storefront.

        The transitions are committed: a delivery that fails here is left to
        the event delivery worker's retry and never fails the command.
        """
        if self._deliver_events_now is None:
            return
        try:
            await self._deliver_events_now()
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Could not deliver the storefront's events now; "
                "the event delivery worker retries them: %s",
                exc,
            )
