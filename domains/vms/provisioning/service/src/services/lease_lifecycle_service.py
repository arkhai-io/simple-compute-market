"""Lease lifecycle orchestration for site resource allocations.

The provisioning service interprets selected site allocations as time-bounded
leases.  The lower site resource service persists resource/allocation/event
state; this service owns lease lifecycle policy and VM-specific enforcement.

The concrete release operation is injected as a delegate.  VM provisioning uses
that delegate to submit ``vm_remove``.  This keeps the state machine close to a
future shared lease lifecycle layer where pod, bare-metal, or other provisioning
services can provide their own release delegate.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from models.jobs_model import AnsibleJobParams
from models.lease_model import (
    LeaseForceReleaseRequest,
    LeaseReleaseOversightRequest,
    LeaseRetryReleaseRequest,
    LeaseTerminateRequest,
    LeaseUpdate,
)
from services.site_resources_service import SiteResourcesService

logger = logging.getLogger(__name__)

ReleaseDelegate = Callable[[dict[str, Any]], Awaitable[str | None] | str | None]


class LeaseLifecycleError(Exception):
    """Base class for lease lifecycle command errors."""


class LeaseNotFoundError(LeaseLifecycleError):
    """Raised when a lease/allocation id does not exist."""


class InvalidLeaseStateError(LeaseLifecycleError):
    """Raised when a lifecycle command is invalid for the current state."""

    def __init__(self, message: str, *, state: str | None = None) -> None:
        super().__init__(message)
        self.state = state


class LeaseLifecycleService:
    """Lease lifecycle state machine over generic site allocations."""

    TERMINAL_SUCCESS_STATES = {"released", "force_released"}
    TERMINAL_FAILURE_STATES = {"release_failed", "unmanaged", "provisioning_failed"}

    def __init__(
        self,
        settings,
        site_resources_service: SiteResourcesService | None = None,
        *,
        capacity_ledger=None,
        job_service=None,
        job_queue_provider: Callable[[], Any] | None = None,
        release_delegate: ReleaseDelegate | None = None,
    ) -> None:
        self._settings = settings
        self._site_resources = site_resources_service or SiteResourcesService(capacity_ledger)
        self._job_svc = job_service
        self._job_queue_provider = job_queue_provider
        self._release_delegate = release_delegate or self._submit_vm_remove_for_allocation
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
        allocation = self._site_resources.get_allocation(lease_id)
        if allocation is None:
            raise LeaseNotFoundError(f"Lease '{lease_id}' not found")
        return allocation

    def get_lease_by_escrow(self, escrow_uid: str) -> dict[str, Any]:
        allocation = self._site_resources.get_allocation_by_escrow(escrow_uid)
        if allocation is None or not allocation.get("lease_end_utc"):
            raise LeaseNotFoundError(f"No lease found for escrow_uid={escrow_uid!r}")
        return allocation

    def list_leases(self) -> list[dict[str, Any]]:
        return [
            allocation
            for allocation in self._site_resources.list_allocations()
            if allocation.get("lease_end_utc")
        ]

    def register_lease(self, body) -> dict[str, Any]:
        attached = self._site_resources.attach_lease_allocation(
            allocation_id=body.allocation_id,
            escrow_uid=body.escrow_uid,
            vm_host=body.vm_host,
            vm_target=body.vm_target,
            lease_start_utc=(
                body.lease_start_utc.isoformat() if body.lease_start_utc else None
            ),
            lease_end_utc=body.lease_end_utc.isoformat(),
            create_job_id=body.create_job_id,
        )
        if attached is None and not body.allocation_id:
            attached = self._site_resources.attach_lease_allocation(
                escrow_uid=body.escrow_uid,
                vm_host=body.vm_host,
                vm_target=body.vm_target,
                lease_start_utc=(
                    body.lease_start_utc.isoformat() if body.lease_start_utc else None
                ),
                lease_end_utc=body.lease_end_utc.isoformat(),
                create_job_id=body.create_job_id,
            )
        if attached is None:
            raise LeaseNotFoundError(
                f"No live allocation for allocation_id={body.allocation_id!r} / "
                f"escrow_uid={body.escrow_uid!r}"
            )
        return attached

    def update_lease(self, lease_id: str, body: LeaseUpdate) -> dict[str, Any]:
        updated = self._site_resources.update_allocation_fields(
            lease_id,
            vm_host=body.vm_host,
            vm_target=body.vm_target,
            lease_start_utc=(
                body.lease_start_utc.isoformat() if body.lease_start_utc else None
            ),
            lease_end_utc=(
                body.lease_end_utc.isoformat() if body.lease_end_utc else None
            ),
            vm_remove_job_id=body.vm_remove_job_id,
            create_job_id=body.create_job_id,
        )
        if updated is None:
            raise LeaseNotFoundError(
                f"Lease '{lease_id}' not found or is already in a terminal state."
            )
        return updated

    async def terminate_lease(
        self, lease_id: str, body: LeaseTerminateRequest | None = None,
    ) -> dict[str, Any]:
        """Request teardown for a managed lease.

        Capacity remains held while the release delegate runs.  A later watchdog
        cycle releases capacity only after the delegated job succeeds.
        """
        allocation = self.get_lease(lease_id)
        state = str(allocation.get("state"))
        if state in self.TERMINAL_SUCCESS_STATES:
            return allocation
        if state == "releasing":
            return allocation
        if state in {"release_failed", "unmanaged"}:
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; admin repair is required.",
                state=state,
            )
        if state not in {"leased"}:
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; only leased allocations can be terminated.",
                state=state,
            )
        job_id = await self._run_release_delegate(allocation)
        if not job_id:
            raise InvalidLeaseStateError(
                f"Could not submit release job for lease '{lease_id}'.",
                state=state,
            )
        return self._site_resources.update_allocation_state(
            lease_id,
            state="releasing",
            vm_remove_job_id=job_id,
        ) or self.get_lease(lease_id)

    def release_oversight(
        self, lease_id: str, body: LeaseReleaseOversightRequest,
    ) -> dict[str, Any]:
        """Release lifecycle oversight without deleting the workload or capacity."""
        allocation = self.get_lease(lease_id)
        state = str(allocation.get("state"))
        if state == "unmanaged":
            return allocation
        if state != "leased":
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; only leased allocations can release oversight.",
                state=state,
            )
        return self._site_resources.update_allocation_state(
            lease_id,
            state="unmanaged",
            failure_reason="oversight_released",
            failure_message=body.reason,
        ) or self.get_lease(lease_id)

    async def retry_release(
        self, lease_id: str, body: LeaseRetryReleaseRequest | None = None,
    ) -> dict[str, Any]:
        """Retry teardown for an allocation in release_failed state."""
        allocation = self.get_lease(lease_id)
        state = str(allocation.get("state"))
        if state != "release_failed":
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; only release_failed leases can retry release.",
                state=state,
            )
        job_id = await self._run_release_delegate(allocation)
        if not job_id:
            raise InvalidLeaseStateError(
                f"Could not submit release retry job for lease '{lease_id}'.",
                state=state,
            )
        retry_reason = body.reason if body and body.reason else "release_retry_requested"
        return self._site_resources.update_allocation_state(
            lease_id,
            state="releasing",
            failure_reason=retry_reason,
            failure_message=f"release retry submitted with job {job_id}",
            vm_remove_job_id=job_id,
        ) or self.get_lease(lease_id)

    async def force_release(
        self, lease_id: str, body: LeaseForceReleaseRequest,
    ) -> dict[str, Any]:
        """Admin repair: release capacity without teardown proof."""
        allocation = self.get_lease(lease_id)
        state = str(allocation.get("state"))
        if state in self.TERMINAL_SUCCESS_STATES:
            return allocation
        allowed = {"leased", "releasing", "release_failed", "unmanaged"}
        if state not in allowed:
            raise InvalidLeaseStateError(
                f"Lease '{lease_id}' is {state}; force-release is only valid for {sorted(allowed)}.",
                state=state,
            )
        message = body.reason
        if body.evidence:
            message = f"{body.reason} Evidence: {body.evidence}"
        released = self._site_resources.release_allocation(
            lease_id,
            state="force_released",
            failure_reason="admin_force_release",
            failure_message=message,
        )
        if released is None:
            raise LeaseNotFoundError(f"Lease '{lease_id}' not found or is not held.")
        await self._notify_storefront_capacity_released(released)
        return released

    async def check_leases(self) -> dict:
        if not self._resume_event.is_set():
            logger.debug("[LEASE_LIFECYCLE] Cycle blocked — watchdog is paused")
            await self._resume_event.wait()
        return await self._run_cycle()

    async def force_check_leases(self) -> dict:
        return await self._run_cycle()

    async def _run_cycle(self) -> dict:
        now = datetime.now(timezone.utc)
        grace_seconds = int(
            getattr(self._settings, "lease_watchdog_grace_period_seconds", 300)
        )

        checked = 0
        released = 0
        release_failed = 0
        skipped = 0

        for allocation in self._site_resources.list_time_bounded_allocations_due(now):
            try:
                job_id = await self._run_release_delegate(allocation)
                if job_id is not None:
                    self._site_resources.update_allocation_state(
                        allocation["allocation_id"],
                        state="releasing",
                        vm_remove_job_id=job_id,
                    )
                    checked += 1
                    logger.info(
                        "[LEASE_LIFECYCLE] Submitted release job %s for allocation %s",
                        job_id,
                        allocation["allocation_id"],
                    )
                else:
                    skipped += 1
            except Exception as exc:
                logger.exception(
                    "[LEASE_LIFECYCLE] Failed to begin release for allocation %s: %s",
                    allocation.get("allocation_id"), exc,
                )
                skipped += 1

        for allocation in self._site_resources.list_allocations(state="releasing"):
            try:
                outcome = await self._process_releasing_allocation(
                    allocation, now, grace_seconds,
                )
                if outcome == "released":
                    released += 1
                elif outcome == "release_failed":
                    release_failed += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.exception(
                    "[LEASE_LIFECYCLE] Unhandled error processing releasing allocation %s: %s",
                    allocation.get("allocation_id"), exc,
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

    async def _run_release_delegate(self, allocation: dict[str, Any]) -> str | None:
        result = self._release_delegate(allocation)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _submit_vm_remove_for_allocation(self, allocation: dict[str, Any]) -> Optional[str]:
        return await self._submit_vm_remove_job(
            vm_host=allocation.get("vm_host"),
            vm_target=allocation.get("vm_target"),
        )

    async def _submit_vm_remove_job(self, *, vm_host, vm_target) -> Optional[str]:
        if self._job_svc is None:
            return "direct-release"
        if not vm_host or not vm_target:
            return None
        try:
            if self._job_queue_provider is not None:
                job_queue = self._job_queue_provider()
            else:
                import container as _container_module
                job_queue = _container_module.resolved_job_queue
            if job_queue is None:
                raise RuntimeError("job_queue not initialised")
            params = AnsibleJobParams(
                vm_host=vm_host,
                vm_action="vm_remove",
                vm_target=vm_target,
            )
            submit = await self._job_svc.submit(params, job_queue=job_queue)
            return submit.job_id
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Failed to submit vm_remove job for %s/%s: %s — will retry next cycle",
                vm_host, vm_target, exc,
            )
            return None

    async def _process_releasing_allocation(
        self, allocation: dict, now: datetime, grace_seconds: int
    ) -> str:
        from core_site.ledger import parse_utc as _parse_utc

        lease_end = _parse_utc(allocation.get("lease_end_utc")) or now
        past_grace = now >= lease_end + timedelta(seconds=grace_seconds)
        job_id = allocation.get("vm_remove_job_id")
        if job_id == "direct-release" and self._job_svc is None:
            if not await self._finish_release(allocation):
                return "skipped"
            return "released"

        if job_id and self._job_svc is not None:
            try:
                job = self._job_svc.get_job(job_id)
                if job.status == "succeeded":
                    if not await self._finish_release(allocation):
                        return "skipped"
                    return "released"
                if job.status in ("failed", "cancelled"):
                    self._mark_release_failed(
                        allocation,
                        reason=f"vm_remove_{job.status}",
                        message=getattr(job, "error", None) or f"vm_remove job {job.status}",
                    )
                    return "release_failed"
            except Exception as exc:
                logger.warning(
                    "[LEASE_LIFECYCLE] Could not poll vm_remove job %s for allocation %s: %s",
                    job_id, allocation["allocation_id"], exc,
                )

        if not past_grace:
            return "skipped"
        self._mark_release_failed(
            allocation,
            reason="vm_remove_timeout",
            message="vm_remove did not complete before watchdog grace period elapsed",
        )
        return "release_failed"

    def _mark_release_failed(
        self, allocation: dict[str, Any], *, reason: str, message: str | None,
    ) -> None:
        logger.error(
            "[LEASE_LIFECYCLE] Release failed for allocation %s: %s %s",
            allocation.get("allocation_id"), reason, message or "",
        )
        self._site_resources.update_allocation_state(
            allocation["allocation_id"],
            state="release_failed",
            failure_reason=reason,
            failure_message=message,
        )

    async def _finish_release(self, allocation: dict) -> bool:
        released = self._site_resources.release_allocation(
            allocation["allocation_id"], state="released",
        )
        if released is None:
            return False
        logger.info(
            "[LEASE_LIFECYCLE] Allocation %s released (resource=%s escrow=%s)",
            allocation["allocation_id"], allocation.get("resource_id"), allocation.get("escrow_uid"),
        )
        await self._notify_storefront_capacity_released(released)
        return True

    async def _notify_storefront_capacity_released(self, allocation: dict) -> bool:
        from storefront_client import StorefrontClient, StorefrontClientError

        storefront_url = str(getattr(self._settings, "storefront_url", "") or "").rstrip("/")
        storefront_admin_key = str(getattr(self._settings, "storefront_admin_key", "") or "")
        if not storefront_url:
            logger.warning(
                "[LEASE_LIFECYCLE] storefront_url not configured — skipping capacity-released event for allocation %s",
                allocation.get("allocation_id"),
            )
            return False
        try:
            async with StorefrontClient(
                base_url=storefront_url,
                admin_key=storefront_admin_key or None,
            ) as sf:
                await sf.notify_capacity_released(
                    str(allocation["allocation_id"]),
                    resource_id=allocation.get("resource_id"),
                    released_at=allocation.get("released_at"),
                )
            return True
        except StorefrontClientError as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] capacity-released event rejected by storefront for allocation %s: %s",
                allocation.get("allocation_id"), exc,
            )
            return False
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Could not deliver capacity-released event for allocation %s: %s",
                allocation.get("allocation_id"), exc,
            )
            return False
