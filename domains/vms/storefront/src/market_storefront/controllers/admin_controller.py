"""Admin controller — global pause/resume, status, and resource maintenance.

require_admin_key is applied via __init__ Depends (not router-level) to avoid
a fastapi_utils @cbv + router-level dependencies interaction issue that causes
routes to return 404.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
from core_storefront.models.system_models import AdminPauseResponse
from domains.vms.provisioning.storefront_models import (
    CapacityReleasedEventRequest,
    FulfillmentEventResponse,
    FulfillmentFailedEventRequest,
    FulfillmentStartedEventRequest,
    ImportResourcesResponse,
    ImportRowError,
    ReleaseReservationsResponse,
    ReleaseStartedEventRequest,
    ReserveCapacityRequest,
    ReserveCapacityResponse,
    ResourcePatchRequest,
    ResourcePatchResponse,
    UsageStartedEventRequest,
)
from market_storefront.utils.failure_policy import (
    FulfillmentFailureContext,
    apply_fulfillment_failure_policy,
    configured_failure_actions,
)
from market_storefront.server import _set_globally_paused
from market_storefront.utils.config import ESCROW_TEMPLATES
from core_storefront.stage_log import stage_event

logger = logging.getLogger(__name__)

# States that the release-reservations endpoints transition back to
# ``available``. ``reserved`` is the in-flight provisioning hold;
# ``leased`` is the post-fulfillment hold for the duration of the lease.
# Anything else (``available``, ``deleted``, etc.) is a no-op.
_HELD_STATES = frozenset({"reserved", "leased"})

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

@cbv(router)
class AdminController:
    def __init__(
        self,
        db=Depends(lambda: _container.resolved_sqlite_client),
        _key: None = Depends(require_admin_key),
    ) -> None:
        self._db = db

    @router.post("/pause", response_model=AdminPauseResponse,
                 summary="Pause new negotiations globally (admin)")
    async def pause(self) -> AdminPauseResponse:
        _set_globally_paused(True)
        return AdminPauseResponse(
            paused=True, message="Storefront paused. New negotiations will receive 503."
        )

    @router.post("/resume", response_model=AdminPauseResponse,
                 summary="Resume new negotiations globally (admin)")
    async def resume(self) -> AdminPauseResponse:
        _set_globally_paused(False)
        return AdminPauseResponse(paused=False, message="Storefront resumed.")

    @router.post(
        "/portfolio/resources/import",
        response_model=ImportResourcesResponse,
        summary="Bulk-import compute resources from a CSV file (admin)",
    )
    async def import_resources(
        self,
        file: UploadFile = File(..., description="Compute resource CSV file."),
    ) -> ImportResourcesResponse:
        """Upload a CSV file and upsert resource rows into the portfolio.

        Upsert semantics: rows present in the file are inserted or updated;
        rows absent from the file are not touched. Always upserts regardless
        of whether the table is already populated — use this to force a
        clobber of the current inventory.

        The CSV must contain at minimum a ``resource_type`` column. Rows that
        fail schema validation are counted in ``failed_count`` and skipped
        without rolling back successfully imported rows. The first failing
        rows surface via ``errors[]`` (capped at 50) so the caller doesn't
        have to attach a debugger to see what went wrong.

        Example::

            curl -X POST http://localhost:8001/api/v1/admin/portfolio/resources/import \\
                 -H "X-Admin-Key: <key>" \\
                 -F "file=@/path/to/resources.csv"
        """
        try:
            csv_content = (await file.read()).decode("utf-8")
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Could not read uploaded file: {exc}")
        try:
            report = await self._db.upsert_resources_from_csv_content(
                csv_content=csv_content,
                source_label=f"admin-import:{file.filename or 'upload'}",
                templates=ESCROW_TEMPLATES,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        logger.info(
            "[ADMIN] Resource import: %d imported, %d failed, %d total rows (file=%s)",
            report.get("imported_count", 0),
            report.get("failed_count", 0),
            report.get("total_rows", 0),
            file.filename,
        )
        # Surface up to 50 per-row failures so operators can see what's
        # wrong without shell access. The full report.rows[] is also
        # logged below, capped lower per line.
        failed_rows = [row for row in report.get("rows") or [] if not row.get("imported")]
        errors_payload = [
            ImportRowError(
                row_number=int(row.get("row_number") or 0),
                resource_id=row.get("resource_id"),
                resource_type=row.get("resource_type"),
                errors=list(row.get("errors") or []),
            )
            for row in failed_rows[:50]
        ]
        for row in failed_rows[:20]:
            logger.warning(
                "[ADMIN] CSV row %s (%s) failed: %s",
                row.get("row_number"),
                row.get("resource_id") or "<no id>",
                "; ".join(row.get("errors") or []),
            )
        if report.get("imported_count"):
            await self._mirror_resources_to_site_authority("import")
        return ImportResourcesResponse(
            imported_count=report.get("imported_count", 0),
            failed_count=report.get("failed_count", 0),
            total_rows=report.get("total_rows", 0),
            errors=errors_payload,
        )

    @router.get(
        "/portfolio/resources/{resource_id}",
        response_model=ResourcePatchResponse,
        summary="Get a compute resource by ID (admin)",
    )
    async def get_resource(self, resource_id: str) -> ResourcePatchResponse:
        """Fetch the current state of a single resource row.

        Returns the same shape as PATCH so callers can use one model for
        both reads and writes.

        404 if the resource_id does not exist.
        """
        row = await self._db.get_resource(resource_id=resource_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Resource {resource_id!r} not found",
            )
        attrs_raw = row.get("attributes") or {}
        if isinstance(attrs_raw, str):
            try:
                attrs = json.loads(attrs_raw)
            except (json.JSONDecodeError, TypeError):
                attrs = {}
        else:
            attrs = attrs_raw
        return ResourcePatchResponse(
            resource_id=resource_id,
            state=row.get("state"),
            attributes=attrs,
            updated=False,  # read-only — no write happened
        )

    @router.patch(
        "/portfolio/resources/{resource_id}",
        response_model=ResourcePatchResponse,
        summary="Partial update of a compute resource (admin)",
    )
    async def patch_resource(
        self, resource_id: str, body: ResourcePatchRequest
    ) -> ResourcePatchResponse:
        """Partially update a resource row.

        Only fields present in the request body (non-None) are written;
        unspecified fields are left unchanged. Idempotent: calling with the
        same state the resource is already in returns ``updated=False`` rather
        than erroring.

        Primary use cases:

        * **Lease expiry** — the provisioning service's LeaseWatchdog calls
          this with ``{"state": "available", "attributes": {"lease_end_utc": null}}``
          when a VM has been cleaned up.
        * **Manual operator intervention** — release a stuck resource, force a
          state transition for debugging, or patch attributes for testing.
        * **Test scenarios** — set arbitrary state without going through the
          full settlement flow.

        Returns the full resource row after the patch so callers can confirm
        what was written without a second GET.

        404 if the resource_id does not exist.
        """
        row = await self._db.get_resource(resource_id=resource_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Resource {resource_id!r} not found",
            )

        old_state = row.get("state")
        old_attrs_raw = row.get("attributes") or {}
        if isinstance(old_attrs_raw, str):
            try:
                old_attrs = json.loads(old_attrs_raw)
            except (json.JSONDecodeError, TypeError):
                old_attrs = {}
        else:
            old_attrs = old_attrs_raw

        # Determine what actually needs to change.
        new_state = body.state
        new_attrs: dict | None = None
        if body.attributes is not None:
            # Merge: existing attrs overwritten by supplied keys; None values
            # clear individual keys.
            merged = {**old_attrs}
            for k, v in body.attributes.items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = v
            new_attrs = merged

        state_changed = new_state is not None and new_state != old_state
        attrs_changed = new_attrs is not None and new_attrs != old_attrs

        if not state_changed and not attrs_changed:
            return ResourcePatchResponse(
                resource_id=resource_id,
                state=old_state,
                attributes=old_attrs,
                updated=False,
            )

        event_parts = []
        if state_changed:
            event_parts.append(f"state:{old_state}->{new_state}")
        if attrs_changed:
            event_parts.append("attrs_updated")
        event_type = "admin_resource_patch:" + ",".join(event_parts)

        # Each admin PATCH is an independent operation — the inputs
        # (resource_id, new_state, new_attrs) repeat across calls
        # (lease watchdog issues the same {state:available,
        # lease_end_utc:null} every time a lease expires), but each
        # call is a real transition that must apply, not a retry of a
        # past one. Idempotency-key dedup is only useful at the HTTP
        # retry layer; we generate a fresh uuid here so each call hits
        # the resources table.
        result = await self._db.apply_resource_transition(
            resource_id=resource_id,
            event_type=event_type,
            idempotency_key=f"admin-patch:{resource_id}:{uuid.uuid4()}",
            set_state=new_state if state_changed else None,
            set_attribute=(
                {f"$.{k}": v for k, v in body.attributes.items()}
                if body.attributes is not None else None
            ),
        )
        applied = bool(result.get("applied"))

        if state_changed and applied:
            logger.info("[ADMIN] Resource %s state: %s → %s", resource_id, old_state, new_state)
        if attrs_changed and applied:
            logger.info("[ADMIN] Resource %s attributes patched", resource_id)

        # Emit a wait-able event when the lease watchdog releases a
        # resource. The provisioning service calls this endpoint with
        # state=available after a lease ends; tests and operators need a
        # synchronization point because the PATCH completes after the
        # /lifecycle/check-leases response returns. Other state
        # transitions (manual ops, init bookkeeping) don't produce this
        # event — it's specifically the leased→available edge.
        if applied and state_changed and old_state == "leased" and new_state == "available":
            stage_event(
                "lease_lifecycle",
                "resource_released",
                resource_id=resource_id,
            )

        await self._mirror_resources_to_site_authority("patch")

        # Re-fetch the updated row to return accurate state.
        updated_row = await self._db.get_resource(resource_id=resource_id)
        attrs_out = updated_row.get("attributes") or {}
        if isinstance(attrs_out, str):
            try:
                attrs_out = json.loads(attrs_out)
            except (json.JSONDecodeError, TypeError):
                attrs_out = {}
        return ResourcePatchResponse(
            resource_id=resource_id,
            state=updated_row.get("state"),
            attributes=attrs_out,
            updated=True,
        )

    async def _mirror_resources_to_site_authority(self, source: str) -> None:
        """Re-sync inventory to the site ledger after an admin mutation.

        Remote-capacity mode only (no-op otherwise): resources imported or
        patched mid-run must be reservable at the site authority, not just
        present in the local market view. Best-effort — the admin call
        already succeeded locally.
        """
        from market_storefront.services.capacity_client import sync_site_resources

        try:
            await sync_site_resources(lambda: self._db)
        except Exception as exc:
            logger.warning(
                "[ADMIN] Site-authority resource sync after %s failed: %s",
                source, exc,
            )

    async def _apply_fulfillment_event(
        self,
        *,
        allocation_id: str,
        event_name: str,
        state: str,
        close_oversized: bool = False,
        reopen_available: bool = False,
        release_allocation: bool = False,
        provider_resource_id: str | None = None,
        failure_reason: str | None = None,
        failure_message: str | None = None,
        **_extra: Any,
    ) -> FulfillmentEventResponse:
        """Record a deal-scoped event and reconcile derived listings.

        The allocation itself lives in the site authority's ledger.
        Progress events (started / usage-started / release-started) carry
        no capacity effect — a held allocation is held in every one of
        those states — so they only stage and reconcile;
        ``release_allocation`` (capacity-released, failed) returns the
        units through the capacity client. A release that finds nothing
        is tolerated: the watchdog or failure policy usually got there
        first, and these events must stay idempotent.
        """
        result: dict[str, Any] = {"resource_id": provider_resource_id}
        if release_allocation:
            try:
                released = await self._capacity().release(
                    allocation_id=allocation_id,
                    failure_reason=failure_reason,
                    failure_message=failure_message,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Could not release allocation {allocation_id!r} "
                           f"at the site authority: {exc}",
                )
            if released is not None:
                result = released
                result.setdefault("gpu_count", released.get("allocated_gpu_count"))
        closed_listing_ids = (
            await self._close_oversized_compute_listings() if close_oversized else []
        )
        reopened_listing_ids = (
            await self._reopen_available_compute_listings() if reopen_available else []
        )
        stage_event(
            "fulfillment",
            event_name,
            allocation_id=allocation_id,
            resource_id=result.get("resource_id"),
            gpu_count=result.get("gpu_count"),
            closed_listing_ids=closed_listing_ids,
            reopened_listing_ids=reopened_listing_ids,
        )
        return FulfillmentEventResponse(
            allocation_id=allocation_id,
            state=state,
            resource_id=result.get("resource_id"),
            gpu_count=result.get("gpu_count"),
            resource_state=result.get("resource_state"),
            closed_listing_ids=closed_listing_ids,
            reopened_listing_ids=reopened_listing_ids,
        )

    def _capacity(self) -> Any:
        from market_storefront.services.capacity_client import build_capacity_client

        return build_capacity_client(lambda: self._db)

    async def _member_availability(self) -> dict | None:
        """Aggregated site availability, or None when unobtainable.

        None makes the close path a no-op and the reopen path skip — a
        transient authority outage must not close (or worse, reopen)
        everything on ignorance.
        """
        from market_storefront.services.capacity_client import (
            member_availability_view,
        )

        try:
            return await member_availability_view(
                self._capacity(), self._db.db_path,
            )
        except Exception as exc:
            logger.warning(
                "[ADMIN] Could not snapshot site-authority capacity: %s", exc,
            )
            return None

    async def _close_oversized_compute_listings(self) -> list[str]:
        from domains.vms.listings.reconciler import (
            mark_derived_listings_closed,
            stale_open_listing_ids,
        )

        availability = await self._member_availability()
        if availability is None:
            return []
        closed_listing_ids = stale_open_listing_ids(
            self._db.db_path, member_availability=availability,
        )
        for listing_id in closed_listing_ids:
            await self._db.update_listing(listing_id=listing_id, status="closed")
        mark_derived_listings_closed(self._db.db_path, closed_listing_ids)
        return closed_listing_ids

    async def _reopen_available_compute_listings(self) -> list[str]:
        from domains.vms.listings.reconciler import (
            closed_available_listing_ids,
            mark_derived_listings_open,
        )

        availability = await self._member_availability()
        if availability is None:
            return []
        reopened_listing_ids = closed_available_listing_ids(
            self._db.db_path, member_availability=availability,
        )
        for listing_id in reopened_listing_ids:
            await self._db.update_listing(listing_id=listing_id, status="open")
        mark_derived_listings_open(self._db.db_path, reopened_listing_ids)
        return reopened_listing_ids

    @router.post(
        "/fulfillment/events/started",
        response_model=FulfillmentEventResponse,
        summary="Record provisioning fulfillment start (admin)",
    )
    async def fulfillment_started(
        self, body: FulfillmentStartedEventRequest,
    ) -> FulfillmentEventResponse:
        return await self._apply_fulfillment_event(
            allocation_id=body.allocation_id,
            event_name="started",
            state="provisioning",
            close_oversized=True,
            provider_id=body.provider_id,
            provider_job_id=body.provider_job_id,
            provider_resource_id=body.resource_id,
        )

    @router.post(
        "/fulfillment/events/usage-started",
        response_model=FulfillmentEventResponse,
        summary="Record compute usage start (admin)",
    )
    async def usage_started(
        self, body: UsageStartedEventRequest,
    ) -> FulfillmentEventResponse:
        return await self._apply_fulfillment_event(
            allocation_id=body.allocation_id,
            event_name="usage_started",
            state="leased",
            close_oversized=True,
            provider_id=body.provider_id,
            provider_lease_id=body.provider_lease_id,
            provider_resource_id=body.resource_id,
            vm_host=body.vm_host,
            vm_target=body.vm_target,
            lease_end_utc=body.lease_end_utc,
        )

    @router.post(
        "/fulfillment/events/release-started",
        response_model=FulfillmentEventResponse,
        summary="Record compute release start (admin)",
    )
    async def release_started(
        self, body: ReleaseStartedEventRequest,
    ) -> FulfillmentEventResponse:
        return await self._apply_fulfillment_event(
            allocation_id=body.allocation_id,
            event_name="release_started",
            state="releasing",
            close_oversized=True,
            provider_lease_id=body.provider_lease_id,
            check_job_id=body.check_job_id,
        )

    @router.post(
        "/fulfillment/events/capacity-released",
        response_model=FulfillmentEventResponse,
        summary="Record compute capacity release (admin)",
    )
    async def capacity_released(
        self, body: CapacityReleasedEventRequest,
    ) -> FulfillmentEventResponse:
        return await self._apply_fulfillment_event(
            allocation_id=body.allocation_id,
            event_name="capacity_released",
            state="released",
            close_oversized=False,
            reopen_available=True,
            release_allocation=True,
            provider_lease_id=body.provider_lease_id,
            provider_resource_id=body.resource_id,
            released_at=body.released_at,
        )

    @router.post(
        "/fulfillment/events/failed",
        response_model=FulfillmentEventResponse,
        summary="Record provisioning fulfillment failure (admin)",
    )
    async def fulfillment_failed(
        self, body: FulfillmentFailedEventRequest,
    ) -> FulfillmentEventResponse:
        result = await apply_fulfillment_failure_policy(
            self._db,
            FulfillmentFailureContext(
                allocation_id=body.allocation_id,
                escrow_uid=body.escrow_uid,
                provider_id=body.provider_id,
                provider_job_id=body.provider_job_id,
                provider_resource_id=body.resource_id,
                resource_id=body.resource_id,
                reason=body.reason,
                message=body.message,
                logs_ref=body.logs_ref,
                source="admin_event",
            ),
        )
        if "release_capacity" in configured_failure_actions() and result.state is None:
            raise HTTPException(
                status_code=404,
                detail=f"Allocation {body.allocation_id!r} not found",
            )
        return FulfillmentEventResponse(
            allocation_id=result.allocation_id or body.allocation_id,
            state=result.state or "unchanged",
            resource_id=result.resource_id,
            gpu_count=result.gpu_count,
            resource_state=result.resource_state,
            closed_listing_ids=[],
            reopened_listing_ids=result.reopened_listing_ids,
        )

    @router.post(
        "/portfolio/reservations",
        response_model=ReserveCapacityResponse,
        summary="Reserve compute capacity without negotiation (admin)",
    )
    async def reserve_capacity(
        self, body: ReserveCapacityRequest,
    ) -> ReserveCapacityResponse:
        """Force-reserve compute capacity using the allocation model.

        This is an operator/test hook for manual holds and recovery
        workflows. The hold lands in the site authority's ledger like
        every other reservation, so partial GPU capacity accounting and
        derived-listing reconciliation stay consistent across consumers.
        """
        reserved = await self._capacity().reserve(
            claim=body.required_attributes or None,
            deal_ref={
                "listing_id": body.listing_id,
                "escrow_uid": body.escrow_uid,
                "reserved_by": "admin",
            },
        )
        if not reserved:
            raise HTTPException(
                status_code=409,
                detail="No available compute VM matched required attributes",
            )
        closed_listing_ids = await self._close_oversized_compute_listings()
        stage_event(
            "portfolio",
            "capacity_reserved_by_admin",
            allocation_id=reserved.get("allocation_id"),
            pool_id=reserved.get("pool_id"),
            member_id=reserved.get("member_id"),
            resource_id=reserved.get("resource_id"),
            gpu_count=reserved.get("allocated_gpu_count"),
            resource_state=reserved.get("state"),
            listing_id=body.listing_id,
            escrow_uid=body.escrow_uid,
            closed_listing_ids=closed_listing_ids,
        )
        # Pools are the aggregator's concept, not the ledger's — surface
        # the membership from the resource attributes the sync mirrored.
        pool_id = (
            reserved.get("pool_id")
            or (reserved.get("attributes") or {}).get("pool_id")
        )
        return ReserveCapacityResponse(
            allocation_id=str(reserved["allocation_id"]),
            pool_id=str(pool_id) if pool_id else None,
            member_id=str(reserved["member_id"]) if reserved.get("member_id") else None,
            resource_id=str(reserved["resource_id"]),
            gpu_count=int(reserved.get("allocated_gpu_count") or 1),
            resource_state=reserved.get("state") or "available",
            closed_listing_ids=closed_listing_ids,
        )

    @router.post(
        "/portfolio/release-reservations",
        response_model=ReleaseReservationsResponse,
        summary="Release every held compute resource back to available (admin)",
    )
    async def release_reservations(self) -> ReleaseReservationsResponse:
        """Force every resource in a held state back to ``available``.

        "Held" means ``reserved`` (during provisioning) OR ``leased`` (during
        an active lease). Both are forms of bookkeeping that the storefront
        normally clears via the provisioning service's LeaseWatchdog once the
        lease expires; under mocked or short-circuited flows the watchdog has
        nothing to do, so this endpoint is the explicit cleanup.

        Use cases:
          - e2e test teardown between back-to-back runs against the same stack
            (mocked provisioning never reaches lease end, so leased resources
            otherwise leak across runs).
          - Operator recovery after a fleet-wide provisioner crash: when the
            storefront thinks resources are held but the actual workloads
            are gone, this clears the bookkeeping without touching
            value/inventory data.

        Sledgehammer — for surgical single-row release, use
        ``PATCH /portfolio/resources/{resource_id}`` with ``state=available``
        instead. Production operators should prefer the targeted variant.

        Does not touch resources in any other state (e.g. ``available`` or
        ``deleted``). Idempotent — safe to call repeatedly.
        """
        released = list(await self._release_site_ledger_holds())

        # Normalize any legacy aggregate state left on local rows so the
        # market view doesn't advertise stale "leased" resources.
        for r in await self._db.list_resources():
            if r.get("state") not in _HELD_STATES:
                continue
            resource_id = str(r["resource_id"])
            await self._db.apply_resource_set_transition(
                resource_id=resource_id,
                event_type="reservation_released_by_admin",
                idempotency_key=f"admin-release:{resource_id}:{r.get('updated_at', '')}",
                set_state="available",
            )
            released.append(resource_id)

        if released:
            logger.info(
                "[ADMIN] Released %d held resource(s): %s",
                len(released), released,
            )
        return ReleaseReservationsResponse(
            released_count=len(released),
            resource_ids=released,
        )

    async def _release_site_ledger_holds(self) -> list[str]:
        from market_storefront.services.capacity_client import (
            remote_site_clients,
        )

        released: list[str] = []
        try:
            sites = remote_site_clients(self._capacity())
            for site_name, client in sites.items():
                for state in ("reserved", "provisioning", "leased", "releasing"):
                    for allocation in await client.list_allocations(state=state):
                        done = await client.release(
                            allocation_id=allocation.get("allocation_id"),
                        )
                        if done:
                            released.append(
                                f"ledger:{site_name}:"
                                f"{allocation.get('allocation_id')}",
                            )
        except Exception as exc:
            logger.warning(
                "[ADMIN] Could not release site-ledger holds: %s", exc,
            )
        return released
