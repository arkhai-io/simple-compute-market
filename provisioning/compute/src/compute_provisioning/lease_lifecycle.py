"""Compute lease, watchdog, retry, and force-release orchestration."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, Protocol
from datetime import datetime, timedelta, timezone

from market_site.authority import SiteAuthorityPort

from .release import ExecutorReleasePort, ReleaseJobPort

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


class LeaseLifecycleService:
    """Lease lifecycle state machine over generic site reservations."""

    TERMINAL_SUCCESS_STATES = {"released", "force_released"}
    TERMINAL_FAILURE_STATES = {"release_failed", "unmanaged", "provisioning_failed"}

    def __init__(
        self,
        settings: Any,
        site_authority: SiteAuthorityPort,
        *,
        executor_release: ExecutorReleasePort,
        release_jobs: ReleaseJobPort | None = None,
        capacity_released_notifier: CapacityReleasedNotifier | None = None,
        capacity_release_outbox: CapacityReleaseOutboxPort | None = None,
        parse_utc_value: ParseUtc = parse_utc,
    ) -> None:
        self._settings = settings
        self._site_authority = site_authority
        self._executor_release = executor_release
        self._release_jobs = release_jobs
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

    def get_lease_by_escrow(self, escrow_uid: str) -> dict[str, Any]:
        reservation = self._site_authority.get_reservation_by_escrow(escrow_uid)
        if reservation is None or not reservation.get("lease_end_utc"):
            raise LeaseNotFoundError(f"No lease found for escrow_uid={escrow_uid!r}")
        return reservation

    def list_leases(self) -> list[dict[str, Any]]:
        return [
            reservation
            for reservation in self._site_authority.list_reservations()
            if reservation.get("lease_end_utc")
        ]

    def register_lease(self, body: Any) -> dict[str, Any]:
        attached = self._site_authority.attach_lease_reservation(
            capacity_reservation_id=body.capacity_reservation_id,
            escrow_uid=body.escrow_uid,
            executor_kind=body.executor_kind,
            executor_target=body.executor_target,
            executor_ref=body.executor_ref,
            lease_start_utc=_datetime_value(body.lease_start_utc),
            lease_end_utc=_datetime_value(body.lease_end_utc),
            create_job_id=body.create_job_id,
        )
        if attached is None and not body.capacity_reservation_id:
            attached = self._site_authority.attach_lease_reservation(
                escrow_uid=body.escrow_uid,
                executor_kind=body.executor_kind,
                executor_target=body.executor_target,
                executor_ref=body.executor_ref,
                lease_start_utc=_datetime_value(body.lease_start_utc),
                lease_end_utc=_datetime_value(body.lease_end_utc),
                create_job_id=body.create_job_id,
            )
        if attached is None:
            raise LeaseNotFoundError(
                f"No live reservation for capacity_reservation_id={body.capacity_reservation_id!r} / "
                f"escrow_uid={body.escrow_uid!r}"
            )
        return attached

    def update_lease(self, lease_id: str, body: Any) -> dict[str, Any]:
        updated = self._site_authority.update_reservation_fields(
            lease_id,
            executor_kind=body.executor_kind,
            executor_target=body.executor_target,
            executor_ref=body.executor_ref,
            lease_start_utc=_datetime_value(body.lease_start_utc),
            lease_end_utc=_datetime_value(body.lease_end_utc),
            release_job_id=body.release_job_id,
            create_job_id=body.create_job_id,
        )
        if updated is None:
            raise LeaseNotFoundError(
                f"Lease '{lease_id}' not found or is already in a terminal state."
            )
        return updated

    async def terminate_lease(self, lease_id: str, body: Any | None = None) -> dict[str, Any]:
        reservation = self.get_lease(lease_id)
        state = str(reservation.get("state"))
        if state in self.TERMINAL_SUCCESS_STATES:
            return reservation
        if state == "releasing":
            return reservation
        if state in {"release_failed", "unmanaged"}:
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; admin repair is required.",
                state=state,
            )
        if state not in {"leased"}:
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; only leased reservations can be terminated.",
                state=state,
            )
        job_id = await self._run_release_delegate(reservation)
        if not job_id:
            raise InvalidLeaseStateError(
                f"Could not submit release job for lease '{lease_id}'.",
                state=state,
            )
        return self._site_authority.begin_release(
            lease_id,
            release_job_id=job_id,
        ) or self.get_lease(lease_id)

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
        reservation = self.get_lease(lease_id)
        state = str(reservation.get("state"))
        if state != "release_failed":
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; only release_failed leases can retry release.",
                state=state,
            )
        job_id = await self._run_release_delegate(reservation)
        if not job_id:
            raise InvalidLeaseStateError(
                f"Could not submit release retry job for lease '{lease_id}'.",
                state=state,
            )
        return self._site_authority.begin_release(
            lease_id,
            release_job_id=job_id,
        ) or self.get_lease(lease_id)

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
                job_id = await self._run_release_delegate(reservation)
                if job_id is not None:
                    self._site_authority.begin_release(
                        reservation["capacity_reservation_id"],
                        release_job_id=job_id,
                    )
                    checked += 1
                    logger.info(
                        "[LEASE_LIFECYCLE] Submitted release job %s for reservation %s",
                        job_id,
                        reservation["capacity_reservation_id"],
                    )
                else:
                    self._mark_release_failed(
                        reservation,
                        reason="release_submit_failed",
                        message="release delegate did not return a job id",
                    )
                    release_failed += 1
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

    async def _run_release_delegate(self, reservation: dict[str, Any]) -> str | None:
        return await self._executor_release.submit_release(reservation)

    async def _process_releasing_reservation(
        self, reservation: dict[str, Any], now: datetime, grace_seconds: int
    ) -> str:
        lease_end = self._parse_utc(reservation.get("lease_end_utc")) or now
        past_grace = now >= lease_end + timedelta(seconds=grace_seconds)
        job_id = reservation.get("release_job_id") or reservation.get("vm_remove_job_id")
        # "direct-release" means the executor's submit_release reported
        # nothing to poll -- e.g. no release delegate configured for that
        # executor kind. This is independent of whether release_jobs is
        # configured at all: a kind-routed dispatcher may hold a real port
        # for one executor kind while another kind still submits this
        # sentinel, and grace-period bookkeeping must not apply to a
        # release that was never dispatched as a pollable job.
        if job_id == "direct-release":
            if not await self._finish_release(reservation):
                return "skipped"
            return "released"

        if job_id and self._release_jobs is not None:
            try:
                job = self._release_jobs.get_job(
                    job_id, executor_kind=reservation.get("executor_kind")
                )
                if job.status == "succeeded":
                    if not await self._finish_release(reservation):
                        return "skipped"
                    return "released"
                if job.status in ("failed", "cancelled"):
                    self._mark_release_failed(
                        reservation,
                        reason=f"vm_remove_{job.status}",
                        message=getattr(job, "error", None) or f"vm_remove job {job.status}",
                    )
                    return "release_failed"
            except Exception as exc:
                logger.warning(
                    "[LEASE_LIFECYCLE] Could not poll vm_remove job %s for reservation %s: %s",
                    job_id, reservation["capacity_reservation_id"], exc,
                )

        if not past_grace:
            return "skipped"
        self._mark_release_failed(
            reservation,
            reason="vm_remove_timeout",
            message="vm_remove did not complete before watchdog grace period elapsed",
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
