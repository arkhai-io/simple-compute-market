"""Lease lifecycle orchestration over the site ledger.

LeaseLifecycleService.check_leases() is the single entry point for all
lease lifecycle processing. It is called by:
  - LeaseWatchdog (on a timer)
  - POST /api/v1/system/check-leases (on demand, admin only)

The lease is the temporal tail of a ledger allocation (one merged row
in ``site_allocations``). A watchdog cycle:

1. Finds leased allocations whose ``lease_end_utc`` has passed and
   submits a check Ansible job to confirm teardown (state → releasing).
2. Polls releasing allocations' check jobs; a finished check (succeeded,
   or failed — VM state unknown but we proceed) releases the allocation
   in the ledger's local transaction, which emits the anonymous
   capacity event for subscribed storefronts. "Forced" means the grace
   period elapsed without the teardown check completing.
3. Delivers the deal-scoped capacity-released event point-to-point to
   the owning storefront — best-effort, since the storefront also
   converges through the capacity-event feed.

The storefront_url and storefront_admin_key are read from global
settings; one provisioning service instance serves one storefront's
deal notifications today (per-deal routing lives in the deal_ref
recorded at reserve time when that changes).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class LeaseLifecycleService:
    """Lease-tail transitions over the capacity ledger.

    Injected with the CapacityLedgerService (the merged allocation/lease
    rows), job_service (Ansible job submission and polling), and
    settings. Does not own the asyncio timer — that belongs to
    LeaseWatchdog.
    """

    def __init__(
        self,
        settings,
        capacity_ledger,
        job_service=None,
    ) -> None:
        self._settings = settings
        self._ledger = capacity_ledger
        self._job_svc = job_service  # AnsibleJobService | None; None disables check jobs
        self._paused = False
        self._resume_event = asyncio.Event()
        self._resume_event.set()  # not paused initially

    def pause(self) -> None:
        """Pause timer-driven watchdog cycles.

        Subsequent calls to check_leases() will block until resume() is
        called. force_check_leases() bypasses this flag entirely.
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
        """Process one lease lifecycle cycle, blocking if paused."""
        if not self._resume_event.is_set():
            logger.debug("[LEASE_LIFECYCLE] Cycle blocked — watchdog is paused")
            await self._resume_event.wait()
        return await self._run_cycle()

    async def force_check_leases(self) -> dict:
        """Run one cycle immediately, ignoring the pause flag.

        Called by POST /api/v1/system/check-leases so operators and
        tests can drive individual lifecycle advances while the timer
        is paused.
        """
        return await self._run_cycle()

    async def _run_cycle(self) -> dict:
        """Process all lease lifecycle transitions for one watchdog cycle.

        Returns a summary dict:
            {
                "checked": int,   # expired leases with check jobs submitted
                "released": int,  # released after a finished check
                "forced": int,    # released past grace without confirmation
                "skipped": int,   # waiting or transient errors
            }
        """
        now = datetime.now(timezone.utc)
        grace_seconds = int(
            getattr(self._settings, "lease_watchdog_grace_period_seconds", 300)
        )

        checked = 0
        released = 0
        forced = 0
        skipped = 0

        for allocation in self._ledger.list_lease_due(now):
            try:
                if self._job_svc is None:
                    if await self._finish_release(allocation, forced_release=False):
                        released += 1
                    else:
                        skipped += 1
                    continue
                job_id = await self._submit_check_job(
                    vm_host=allocation.get("vm_host"),
                    vm_target=allocation.get("vm_target"),
                )
                if job_id is not None:
                    self._ledger.begin_releasing(
                        allocation["allocation_id"], check_job_id=job_id,
                    )
                    checked += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.exception(
                    "[LEASE_LIFECYCLE] Failed to begin release for "
                    "allocation %s: %s", allocation.get("allocation_id"), exc,
                )
                skipped += 1

        for allocation in self._ledger.list_allocations(state="releasing"):
            try:
                outcome = await self._process_releasing_allocation(
                    allocation, now, grace_seconds,
                )
                if outcome == "released":
                    released += 1
                elif outcome == "forced":
                    forced += 1
                else:
                    skipped += 1
            except Exception as exc:
                logger.exception(
                    "[LEASE_LIFECYCLE] Unhandled error processing releasing "
                    "allocation %s: %s", allocation.get("allocation_id"), exc,
                )
                skipped += 1

        if checked or released or forced:
            logger.info(
                "[LEASE_LIFECYCLE] Cycle: checked=%d released=%d "
                "forced=%d skipped=%d",
                checked, released, forced, skipped,
            )
        return {
            "checked": checked,
            "released": released,
            "forced": forced,
            "skipped": skipped,
        }

    async def _submit_check_job(self, *, vm_host, vm_target) -> Optional[str]:
        """Submit a teardown-confirmation check job; None on failure."""
        if not vm_host or not vm_target:
            return None
        try:
            from models.jobs_model import AnsibleJobParams
            import container as _container_module
            job_queue = _container_module.resolved_job_queue
            if job_queue is None:
                raise RuntimeError("job_queue not initialised")
            params = AnsibleJobParams(
                vm_host=vm_host,
                vm_action="check",
                vm_target=vm_target,
            )
            submit = await self._job_svc.submit(params, job_queue=job_queue)
            return submit.job_id
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Failed to submit check job for %s/%s: %s — "
                "will retry next cycle", vm_host, vm_target, exc,
            )
            return None

    async def _process_releasing_allocation(
        self, allocation: dict, now: datetime, grace_seconds: int
    ) -> str:
        """Poll the check job for a releasing allocation.

        A finished check job (succeeded, or failed — VM state unknown
        but we proceed) releases normally; "forced" means the grace
        period elapsed without the teardown check completing.
        """
        from core_site.ledger import parse_utc as _parse_utc

        lease_end = _parse_utc(allocation.get("lease_end_utc")) or now
        past_grace = now >= lease_end + timedelta(seconds=grace_seconds)

        check_done = False
        check_job_id = allocation.get("check_job_id")
        if check_job_id and self._job_svc is not None:
            try:
                job = self._job_svc.get_job(check_job_id)
                if job.status == "succeeded":
                    check_done = True
                elif job.status in ("failed", "cancelled"):
                    logger.warning(
                        "[LEASE_LIFECYCLE] Check job %s for allocation %s %s — "
                        "proceeding with release",
                        check_job_id, allocation["allocation_id"], job.status,
                    )
                    check_done = True
            except Exception as exc:
                logger.warning(
                    "[LEASE_LIFECYCLE] Could not poll check job %s for "
                    "allocation %s: %s", check_job_id,
                    allocation["allocation_id"], exc,
                )

        if not check_done and not past_grace:
            return "skipped"  # check still running — wait for it or the grace
        force = not check_done
        if not await self._finish_release(allocation, forced_release=force):
            return "skipped"
        return "forced" if force else "released"

    async def _finish_release(
        self, allocation: dict, *, forced_release: bool
    ) -> bool:
        """Release the allocation locally, then notify the owning storefront.

        The release is the ledger's local transaction (capacity event
        emitted there); the deal-scoped notification is best-effort —
        the storefront also converges through the capacity-event feed.
        """
        state = "forced" if forced_release else "released"
        released = self._ledger.release(
            allocation_id=allocation["allocation_id"], state=state,
        )
        if released is None:
            return False
        log = logger.warning if forced_release else logger.info
        log(
            "[LEASE_LIFECYCLE] Allocation %s %s (resource=%s escrow=%s)",
            allocation["allocation_id"], state,
            allocation.get("resource_id"), allocation.get("escrow_uid"),
        )
        await self._notify_storefront_capacity_released(released)
        return True

    async def _notify_storefront_capacity_released(self, allocation: dict) -> bool:
        """POST the deal-scoped capacity-released event to the owner.

        Point-to-point per the capacity design's event model — this
        carries deal context (allocation/escrow) and so is never
        broadcast.
        """
        from storefront_client import StorefrontClient, StorefrontClientError

        storefront_url = str(getattr(self._settings, "storefront_url", "") or "").rstrip("/")
        storefront_admin_key = str(getattr(self._settings, "storefront_admin_key", "") or "")
        if not storefront_url:
            logger.warning(
                "[LEASE_LIFECYCLE] storefront_url not configured — skipping "
                "capacity-released event for allocation %s",
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
                "[LEASE_LIFECYCLE] capacity-released event rejected by "
                "storefront for allocation %s: %s",
                allocation.get("allocation_id"), exc,
            )
            return False
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Could not deliver capacity-released event "
                "for allocation %s: %s",
                allocation.get("allocation_id"), exc,
            )
            return False
