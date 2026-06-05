"""Lease lifecycle orchestration.

LeaseLifecycleService.check_leases() is the single entry point for all lease
lifecycle processing. It is called by:
  - LeaseWatchdog (on a timer)
  - POST /api/v1/system/check-leases (on demand, admin only)

Flow per watchdog cycle
-----------------------
1. Activate pending leases whose lease_start_utc has passed (list_pending_to_activate).
2. Find expired active leases (list_due — lease_end_utc < now, status=active).
3. For each expired lease:
   a. Submit a check Ansible job via job_service against vm_host.
   b. Call begin_releasing(lease_id, check_job_id) to record the job
      and transition status to 'releasing'.
4. For leases already in 'releasing' status (list_releasing — check job in progress):
   a. Poll check_job_id status via job_service.get_job().
   b. If succeeded: call _patch_storefront_resource() then mark_released().
   c. If failed/cancelled: treat as VM-unknown — fall through to grace check.
   d. If still running: leave in 'releasing' for the next cycle.
5. If storefront patch fails within grace period: skip (retry next cycle).
   If past grace period: mark_forced() regardless of check result.

The storefront_url and storefront_admin_key are read from global settings
(settings.toml: storefront_url, storefront_admin_key). One provisioning
service instance serves one storefront.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from db.models import LeaseStatus, VmLease
from services.lease_service import LeaseService

logger = logging.getLogger(__name__)


class LeaseLifecycleService:
    """Service layer for lease lifecycle transitions.

    Injected with LeaseService (DB access), job_service (Ansible job submission
    and polling), and settings. Does not own the asyncio timer — that belongs
    to LeaseWatchdog.
    """

    def __init__(self, lease_service: LeaseService, settings, job_service=None) -> None:
        self._lease_svc = lease_service
        self._settings = settings
        self._job_svc = job_service  # AnsibleJobService | None; None disables check jobs
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()  # not paused initially

    def pause(self) -> None:
        """Pause timer-driven watchdog cycles.

        Subsequent calls to check_leases() will block until resume() is called.
        force_check_leases() bypasses this flag entirely — it always runs.
        """
        self._paused = True
        self._resume_event.clear()
        logger.info("[LEASE_LIFECYCLE] Watchdog paused — timer cycles will block")

    def resume(self) -> None:
        """Resume timer-driven watchdog cycles."""
        self._paused = False
        self._resume_event.set()
        logger.info("[LEASE_LIFECYCLE] Watchdog resumed")

    async def check_leases(self) -> dict:
        """Process one lease lifecycle cycle, blocking if paused.

        Called by the LeaseWatchdog timer. Blocks at the pause gate so tests
        can suspend automatic advances. Use force_check_leases() to bypass
        the gate explicitly.
        """
        if not self._resume_event.is_set():
            logger.debug("[LEASE_LIFECYCLE] Cycle blocked — watchdog is paused")
            await self._resume_event.wait()
        return await self._run_cycle()

    async def force_check_leases(self) -> dict:
        """Run one lease lifecycle cycle immediately, ignoring the pause flag.

        Called by POST /api/v1/system/check-leases. Bypasses the pause gate
        so operators and tests can drive individual lifecycle advances while
        the watchdog timer is paused.
        """
        return await self._run_cycle()

    async def _run_cycle(self) -> dict:
        """Process all lease lifecycle transitions for one watchdog cycle.

        Returns a summary dict:
            {
                "activated": int,   # pending leases advanced to active
                "checked": int,     # expired leases for which check jobs were submitted
                "released": int,    # successfully patched to available
                "forced": int,      # force-patched after grace period
                "skipped": int,     # errors or transient states
            }
        """
        now = datetime.now(timezone.utc)
        grace_seconds = int(
            getattr(self._settings, "lease_watchdog_grace_period_seconds", 300)
        )

        # Step 1: advance pending leases whose start time has passed
        activated = 0
        for lease in self._lease_svc.list_pending_to_activate(now):
            try:
                self._lease_svc.advance_pending(lease.id)
                activated += 1
                logger.info(
                    "[LEASE_LIFECYCLE] Activated lease %s (resource=%s)",
                    lease.id, lease.resource_id,
                )
            except Exception as exc:
                logger.exception(
                    "[LEASE_LIFECYCLE] Failed to activate lease %s: %s", lease.id, exc
                )

        # Step 2: submit check jobs for newly expired active leases
        checked = 0
        direct_released = 0  # releases that happened synchronously (no job_svc)
        direct_skipped = 0   # direct-patch failures within grace period
        for lease in self._lease_svc.list_due(now):
            try:
                was_released = await self._begin_release(lease)
                if was_released:
                    direct_released += 1
                elif self._job_svc is None:
                    # No job_service and patch failed — count as skipped
                    direct_skipped += 1
                else:
                    checked += 1
            except Exception as exc:
                logger.exception(
                    "[LEASE_LIFECYCLE] Failed to begin release for lease %s: %s",
                    lease.id, exc,
                )
                direct_skipped += 1

        # Step 3: process leases already in 'releasing' state
        released = 0
        forced = 0
        skipped = 0
        for lease in self._lease_svc.list_releasing():
            try:
                result = await self._process_releasing_lease(lease, now, grace_seconds)
                if result == "released":
                    released += 1
                elif result == "forced":
                    forced += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.exception(
                    "[LEASE_LIFECYCLE] Unhandled error processing releasing lease %s: %s",
                    lease.id, exc,
                )
                skipped += 1

        if activated or checked or direct_released or released or forced:
            logger.info(
                "[LEASE_LIFECYCLE] Cycle: activated=%d checked=%d released=%d "
                "forced=%d skipped=%d",
                activated, checked, direct_released + released, forced,
                direct_skipped + skipped,
            )
        return {
            "activated": activated,
            "checked": checked,
            "released": direct_released + released,
            "forced": forced,
            "skipped": direct_skipped + skipped,
        }

    async def _begin_release(self, lease: VmLease) -> bool:
        """Submit a check Ansible job and transition lease to 'releasing'.

        Returns True if the lease was released synchronously (no job_service path),
        False if a check job was submitted (async path via job_service).
        """
        if self._job_svc is None:
            # No job service wired — patch storefront directly (test/dev path)
            ok = await self._patch_storefront_resource(lease)
            if ok:
                self._lease_svc.mark_released(lease.id)
                return True
            else:
                logger.warning(
                    "[LEASE_LIFECYCLE] No job_service; direct patch failed for lease %s",
                    lease.id,
                )
                return False

        # Submit check job
        try:
            from models.jobs_model import AnsibleJobParams
            import container as _container_module
            job_queue = _container_module.resolved_job_queue
            if job_queue is None:
                raise RuntimeError("job_queue not initialised")

            params = AnsibleJobParams(
                vm_host=lease.vm_host,
                vm_action="check",
                vm_target=lease.vm_target,
            )
            submit = await self._job_svc.submit(
                params, job_queue=job_queue
            )
            self._lease_svc.begin_releasing(lease.id, check_job_id=submit.job_id)
            logger.info(
                "[LEASE_LIFECYCLE] Lease %s: submitted check job %s (resource=%s)",
                lease.id, submit.job_id, lease.resource_id,
            )
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Failed to submit check job for lease %s: %s — "
                "will retry next cycle",
                lease.id, exc,
            )
        return False  # job submitted (or failed to submit) — async release path

    async def _process_releasing_lease(
        self, lease: VmLease, now: datetime, grace_seconds: int
    ) -> str:
        """Poll the check job for a lease in 'releasing' state.

        Returns 'released', 'forced', or 'skipped'.
        """
        lease_end = lease.lease_end_utc
        if lease_end.tzinfo is None:
            lease_end = lease_end.replace(tzinfo=timezone.utc)
        grace_deadline = lease_end + timedelta(seconds=grace_seconds)
        past_grace = now >= grace_deadline

        # If no check job recorded, fall through to patch (job submission failed)
        job_ok: Optional[bool] = None
        if lease.check_job_id and self._job_svc is not None:
            try:
                job = self._job_svc.get_job(lease.check_job_id)
                if job.status == "succeeded":
                    job_ok = True
                elif job.status in ("failed", "cancelled"):
                    job_ok = False
                    logger.warning(
                        "[LEASE_LIFECYCLE] Check job %s for lease %s %s — "
                        "proceeding with release",
                        lease.check_job_id, lease.id, job.status,
                    )
                else:
                    # Still running — wait unless past grace period
                    if not past_grace:
                        return "skipped"
                    logger.warning(
                        "[LEASE_LIFECYCLE] Check job %s still running past grace "
                        "period for lease %s — force-releasing",
                        lease.check_job_id, lease.id,
                    )
                    job_ok = False
            except Exception as exc:
                logger.warning(
                    "[LEASE_LIFECYCLE] Could not poll check job %s for lease %s: %s",
                    lease.check_job_id, lease.id, exc,
                )

        # Patch the storefront resource
        ok = await self._patch_storefront_resource(lease)

        if ok:
            self._lease_svc.mark_released(lease.id)
            logger.info(
                "[LEASE_LIFECYCLE] Lease %s released (resource=%s escrow=%s)",
                lease.id, lease.resource_id, lease.escrow_uid,
            )
            return "released"

        if past_grace:
            self._lease_svc.mark_forced(lease.id)
            logger.warning(
                "[LEASE_LIFECYCLE] Lease %s forced past grace period "
                "(resource=%s storefront=%s)",
                lease.id, lease.resource_id,
                getattr(self._settings, "storefront_url", ""),
            )
            return "forced"

        logger.warning(
            "[LEASE_LIFECYCLE] Lease %s storefront patch failed within grace period, "
            "will retry (resource=%s grace_deadline=%s)",
            lease.id, lease.resource_id, grace_deadline.isoformat(),
        )
        return "skipped"

    async def _patch_storefront_resource(self, lease: VmLease) -> bool:
        """PATCH the storefront resource back to available via StorefrontClient.

        storefront_url and storefront_admin_key are read from global settings.
        Returns True on success or 404 (idempotent — resource already gone),
        False on any connectivity or auth failure.
        """
        from storefront_client import StorefrontClient, StorefrontClientError

        storefront_url = str(getattr(self._settings, "storefront_url", "") or "").rstrip("/")
        storefront_admin_key = str(getattr(self._settings, "storefront_admin_key", "") or "")

        if not storefront_url:
            logger.error(
                "[LEASE_LIFECYCLE] storefront_url not configured — cannot release lease %s",
                lease.id,
            )
            return False

        try:
            async with StorefrontClient(
                base_url=storefront_url,
                admin_key=storefront_admin_key or None,
            ) as sf:
                await sf.patch_resource(
                    lease.resource_id,
                    state="available",
                    attributes={
                        "lease_end_utc": None,
                        "allocation_id": lease.allocation_id,
                    } if lease.allocation_id else {"lease_end_utc": None},
                )
            return True
        except StorefrontClientError as exc:
            if exc.status_code == 404:
                # Resource no longer exists on the storefront — treat as released
                logger.warning(
                    "[LEASE_LIFECYCLE] Storefront 404 for resource %s (lease %s) "
                    "— treating as released",
                    lease.resource_id, lease.id,
                )
                return True
            logger.warning(
                "[LEASE_LIFECYCLE] Storefront PATCH failed for resource %s (lease %s): %s",
                lease.resource_id, lease.id, exc,
            )
            return False
        except Exception as exc:
            name = type(exc).__name__
            if "Connect" in name or "connection" in str(exc).lower():
                logger.warning(
                    "[LEASE_LIFECYCLE] Cannot connect to storefront for lease %s: %s",
                    lease.id, exc,
                )
            elif "Timeout" in name or "timeout" in str(exc).lower():
                logger.warning(
                    "[LEASE_LIFECYCLE] Storefront PATCH timed out for lease %s: %s",
                    lease.id, exc,
                )
            else:
                logger.exception(
                    "[LEASE_LIFECYCLE] Unexpected error patching storefront for lease %s: %s",
                    lease.id, exc,
                )
            return False
