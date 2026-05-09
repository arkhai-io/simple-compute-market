"""Admin controller — global pause/resume, status, and resource maintenance.

require_admin_key is applied via __init__ Depends (not router-level) to avoid
a fastapi_utils @cbv + router-level dependencies interaction issue that causes
routes to return 404.
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.system_models import (
    AdminPauseResponse,
    ImportResourcesResponse,
    ReleaseReservationsResponse,
    ResourcePatchRequest,
    ResourcePatchResponse,
)
from market_storefront.server import _set_globally_paused

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
        without rolling back successfully imported rows.

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
        return ImportResourcesResponse(
            imported_count=report.get("imported_count", 0),
            failed_count=report.get("failed_count", 0),
            total_rows=report.get("total_rows", 0),
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

        await self._db.apply_resource_transition(
            resource_id=resource_id,
            event_type=event_type,
            idempotency_key=f"admin-patch:{resource_id}:{new_state}:{json.dumps(new_attrs, sort_keys=True) if new_attrs is not None else ''}",
            set_state=new_state if state_changed else None,
            set_attribute=(
                {f"$.{k}": v for k, v in body.attributes.items()}
                if body.attributes is not None else None
            ),
        )

        if state_changed:
            logger.info("[ADMIN] Resource %s state: %s → %s", resource_id, old_state, new_state)
        if attrs_changed:
            logger.info("[ADMIN] Resource %s attributes patched", resource_id)

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
        resources = await self._db.list_resources()
        released = []
        for r in resources:
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

