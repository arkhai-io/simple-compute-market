"""Compute lease, watchdog, retry, and force-release orchestration."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol
from datetime import datetime, timedelta, timezone

from market_site.authority import SiteAuthorityPort

from .release import ReleaseAction, ReleaseDecision, ReleaseProgress, ReleaseStatus

logger = logging.getLogger(__name__)

CapacityReleasedNotifier = Callable[[dict[str, Any]], Awaitable[bool] | bool]
ParseUtc = Callable[[Any], datetime | None]


class CapacityReleaseOutboxPort(Protocol):
    """Durable delivery state for terminal capacity-release callbacks."""

    def reserve(self, capacity_reservation_id: str) -> None: ...

    def pending(self) -> Iterable[str]: ...

    def mark_delivered(self, capacity_reservation_id: str) -> None: ...

    def record_failure(
        self,
        capacity_reservation_id: str,
        error: str,
    ) -> None: ...


class InMemoryCapacityReleaseOutbox:
    """Process-local implementation for isolated lifecycle consumers/tests."""

    def __init__(self) -> None:
        self._pending: set[str] = set()

    def reserve(self, capacity_reservation_id: str) -> None:
        self._pending.add(capacity_reservation_id)

    def pending(self) -> tuple[str, ...]:
        return tuple(sorted(self._pending))

    def mark_delivered(self, capacity_reservation_id: str) -> None:
        self._pending.discard(capacity_reservation_id)

    def record_failure(
        self,
        capacity_reservation_id: str,
        error: str,
    ) -> None:
        return None

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


class ReleaseExecutorPort(Protocol):
    """Decides a reservation's release and begins or adopts its teardown."""

    async def submit_release(self, reservation: dict[str, Any]) -> ReleaseDecision: ...

    async def begin_teardown(self, fulfillment_id: str) -> str: ...


class ReleaseStatusPort(Protocol):
    """Reads a releasing lease's progress by its release handle."""

    def get_status(self, fulfillment_id: str) -> ReleaseStatus: ...


class LeaseLifecycleService:
    """Lease lifecycle state machine over site reservations, for every mode.

    The lifecycle owns ``releasing``, the terminal release states, the final
    capacity return, and the capacity-released notification. What a release
    does follows the reservation's fulfillment aggregate (``release.py``): it
    begins or adopts teardown, frees capacity through the site's guarded
    release when nothing was delivered, waits while a create is in flight, or
    leaves the lease for an operator. A release waiting on an in-flight create
    is ``releasing`` with the fulfillment as its release handle, so it survives
    a restart and a second request finds it.
    """

    TERMINAL_SUCCESS_STATES = {"released", "force_released"}
    TERMINAL_FAILURE_STATES = {"release_failed", "unmanaged", "provisioning_failed"}

    def __init__(
        self,
        settings: Any,
        site_authority: SiteAuthorityPort,
        *,
        release_executor: ReleaseExecutorPort,
        release_status: ReleaseStatusPort,
        capacity_released_notifier: CapacityReleasedNotifier | None = None,
        capacity_release_outbox: CapacityReleaseOutboxPort | None = None,
        parse_utc_value: ParseUtc = parse_utc,
    ) -> None:
        self._settings = settings
        self._site_authority = site_authority
        self._release_executor = release_executor
        self._release_status = release_status
        self._capacity_released_notifier = capacity_released_notifier
        self._capacity_release_outbox = (
            capacity_release_outbox or InMemoryCapacityReleaseOutbox()
        )
        self._parse_utc = parse_utc_value
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()

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

    def get_lease(self, lease_id: str) -> dict[str, Any]:
        reservation = self._site_authority.get_reservation(lease_id)
        if reservation is None:
            raise LeaseNotFoundError(f"Lease '{lease_id}' not found")
        return reservation

    async def terminate_lease(self, lease_id: str, body: Any | None = None) -> dict[str, Any]:
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
        await self._request_release(reservation)
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
        return self._site_authority.record_unmanaged(
            lease_id,
            reason="oversight_released",
            message=body.reason,
        ) or self.get_lease(lease_id)

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
        return self.get_lease(lease_id)

    async def force_release(self, lease_id: str, body: Any) -> dict[str, Any]:
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
        self._capacity_release_outbox.reserve(lease_id)
        released = self._site_authority.record_release_success(
            lease_id,
            forced=True,
            reason="admin_force_release",
            message=message,
        )
        if released is None:
            raise LeaseNotFoundError(f"Lease '{lease_id}' not found or is not held.")
        await self._deliver_capacity_release(lease_id)
        return released

    async def check_leases(self) -> dict:
        if not self._resume_event.is_set():
            logger.debug("[LEASE_LIFECYCLE] Cycle blocked — watchdog is paused")
            await self._resume_event.wait()
        return await self._run_cycle()

    async def force_check_leases(self) -> dict:
        return await self._run_cycle()

    async def _run_cycle(self) -> dict:
        await self._drain_capacity_release_outbox()
        now = datetime.now(timezone.utc)
        grace_seconds = int(
            getattr(self._settings, "lease_watchdog_grace_period_seconds", 300)
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
                self._mark_release_failed(
                    reservation,
                    reason="release_submit_error",
                    message=str(exc),
                )
                release_failed += 1
                continue
            if outcome == "releasing":
                checked += 1
            elif outcome == "released":
                released += 1
            else:
                release_failed += 1

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

    async def _request_release(self, reservation: dict[str, Any]) -> str:
        """Act on the fulfillment's decision; return the lease's resulting state.

        A direct release the site's guard refuses means the aggregate moved
        between the decision and the release (a dispatch won a race), so the
        decision is taken once more and followed; refused again, nothing proves
        the capacity free, and an operator must verify.
        """
        capacity_reservation_id = reservation["capacity_reservation_id"]
        decision = await self._release_executor.submit_release(reservation)
        if decision.action is ReleaseAction.FREE:
            if await self._finish_release(reservation):
                return "released"
            decision = await self._release_executor.submit_release(reservation)
            if decision.action is ReleaseAction.FREE:
                if await self._finish_release(reservation):
                    return "released"
                self._mark_release_failed(
                    reservation,
                    reason="release_unproven",
                    message=(
                        "nothing is left to tear down, but the reservation's "
                        "provenance does not prove that nothing was dispatched"
                    ),
                )
                return "release_failed"
        if decision.action in (ReleaseAction.TEARDOWN, ReleaseAction.CREATE_IN_FLIGHT):
            self._site_authority.begin_release(
                capacity_reservation_id,
                release_job_id=str(decision.fulfillment_id),
            )
            logger.info(
                "[LEASE_LIFECYCLE] Reservation %s releasing under fulfillment %s (%s)",
                capacity_reservation_id,
                decision.fulfillment_id,
                decision.action.value,
            )
            return "releasing"
        self._mark_release_failed(
            reservation,
            reason=decision.reason or "release_unproven",
            message=decision.message,
        )
        return "release_failed"

    async def _process_releasing_reservation(
        self, reservation: dict[str, Any], now: datetime, grace_seconds: int
    ) -> str:
        fulfillment_id = reservation.get("release_job_id")
        if not fulfillment_id:
            self._mark_release_failed(
                reservation,
                reason="teardown_failed",
                message="the releasing reservation records no release handle",
            )
            return "release_failed"

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
                self._mark_release_failed(
                    reservation,
                    reason=status.reason or "teardown_failed",
                    message=status.error,
                )
                return "release_failed"
            if status.progress is ReleaseProgress.READY_FOR_TEARDOWN:
                await self._release_executor.begin_teardown(str(fulfillment_id))
                return "skipped"
            if status.progress is ReleaseProgress.CREATE_IN_FLIGHT:
                # Waiting on a create is not a stalled teardown: the grace
                # period starts counting only once there is a teardown to wait on.
                return "skipped"

        lease_end = self._parse_utc(reservation.get("lease_end_utc")) or now
        if now < lease_end + timedelta(seconds=grace_seconds):
            return "skipped"
        self._mark_release_failed(
            reservation,
            reason="teardown_timeout",
            message="teardown did not complete before the watchdog grace period elapsed",
        )
        return "release_failed"

    def _mark_release_failed(
        self, reservation: dict[str, Any], *, reason: str, message: str | None,
    ) -> None:
        logger.error(
            "[LEASE_LIFECYCLE] Release failed for reservation %s: %s %s",
            reservation.get("capacity_reservation_id"), reason, message or "",
        )
        self._site_authority.record_release_failure(
            reservation["capacity_reservation_id"],
            reason=reason,
            message=message,
        )

    async def _finish_release(self, reservation: dict[str, Any]) -> bool:
        capacity_reservation_id = reservation["capacity_reservation_id"]
        self._capacity_release_outbox.reserve(capacity_reservation_id)
        released = self._site_authority.record_release_success(
            capacity_reservation_id,
        )
        if released is None:
            return False
        logger.info(
            "[LEASE_LIFECYCLE] Reservation %s released (resource=%s escrow=%s)",
            capacity_reservation_id,
            reservation.get("resource_id"),
            reservation.get("escrow_uid"),
        )
        await self._deliver_capacity_release(capacity_reservation_id)
        return True

    async def _drain_capacity_release_outbox(self) -> None:
        for capacity_reservation_id in self._capacity_release_outbox.pending():
            await self._deliver_capacity_release(capacity_reservation_id)

    async def _deliver_capacity_release(
        self,
        capacity_reservation_id: str,
    ) -> bool:
        reservation = self._site_authority.get_reservation(
            capacity_reservation_id
        )
        if reservation is None or str(reservation.get("state")) not in (
            self.TERMINAL_SUCCESS_STATES
        ):
            return False
        delivered = await self._notify_storefront_capacity_released(reservation)
        if delivered:
            self._capacity_release_outbox.mark_delivered(
                capacity_reservation_id
            )
            return True
        self._capacity_release_outbox.record_failure(
            capacity_reservation_id,
            "signed storefront acknowledgement was not received",
        )
        return False

    async def _notify_storefront_capacity_released(self, reservation: dict[str, Any]) -> bool:
        if self._capacity_released_notifier is None:
            logger.warning(
                "[LEASE_LIFECYCLE] capacity release notifier not configured — skipping capacity-released event for reservation %s",
                reservation.get("capacity_reservation_id"),
            )
            return False
        try:
            result = self._capacity_released_notifier(reservation)
            if inspect.isawaitable(result):
                result = await result
            return bool(result)
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Could not deliver capacity-released event for reservation %s: %s",
                reservation.get("capacity_reservation_id"), exc,
            )
            return False
