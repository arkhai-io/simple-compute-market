"""Admin controller — global pause/resume, status, and resource maintenance.

require_admin_key is applied via __init__ Depends (not router-level) to avoid
a fastapi_utils @cbv + router-level dependencies interaction issue that causes
routes to return 404.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, UploadFile, File
from fastapi_utils.cbv import cbv

import market_storefront.container as _container
from market_storefront.middleware.admin_auth import require_admin_key
from market_storefront.models.system_models import (
    AdminPauseResponse,
    ImportResourcesResponse,
    ReleaseReservationsResponse,
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
        from fastapi import HTTPException
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

    @router.post(
        "/portfolio/resources/{resource_id}/release-reservation",
        response_model=ReleaseReservationsResponse,
        summary="Release one held compute resource back to available (admin)",
    )
    async def release_one_reservation(
        self, resource_id: str
    ) -> ReleaseReservationsResponse:
        """Force a single resource in any held state back to ``available``.

        Surgical counterpart to ``release-reservations``: clears exactly the
        named row's hold, so an operator can target one stuck resource
        without freeing every reservation in the seller's portfolio. Covers
        both ``reserved`` (held during provisioning) and ``leased`` (held
        for the duration of an active lease) — they're both "held" states
        from the portfolio's perspective. The only mutation is the
        ``state`` transition; ``value``, ``attributes``, and
        ``lease_end_utc`` are left intact.

        404 if the row doesn't exist; idempotent on already-available rows
        (returns ``released_count=0`` rather than failing).

        For an actual stuck VM with a running workload, pair this with the
        provisioning service's
        ``POST /api/v1/hosts/{host}/vms/{vm_name}/destroy`` (and optionally
        ``/undefine``) — those run real Ansible against the host, while
        this endpoint only clears the storefront's own bookkeeping.
        """
        from fastapi import HTTPException
        row = await self._db.get_resource(resource_id=resource_id)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Resource {resource_id!r} not found",
            )
        if row.get("state") not in _HELD_STATES:
            return ReleaseReservationsResponse(released_count=0, resource_ids=[])
        await self._db.apply_resource_set_transition(
            resource_id=resource_id,
            event_type="reservation_released_by_admin",
            idempotency_key=f"admin-release:{resource_id}:{row.get('updated_at', '')}",
            set_state="available",
        )
        logger.info(
            "[ADMIN] Released %s resource: %s",
            row.get("state"), resource_id,
        )
        return ReleaseReservationsResponse(
            released_count=1, resource_ids=[resource_id]
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
        normally clears via ``resource_poller`` once the lease expires;
        under mocked or short-circuited flows the poller has nothing to
        do, so this endpoint is the explicit cleanup.

        Use cases:
          - e2e test teardown between back-to-back runs against the same stack
            (mocked provisioning never reaches lease end, so leased resources
            otherwise leak across runs).
          - Operator recovery after a fleet-wide provisioner crash: when the
            storefront thinks resources are held but the actual workloads
            are gone, this clears the bookkeeping without touching
            value/inventory data.

        Sledgehammer — for surgical single-row release, use
        ``POST /portfolio/resources/{resource_id}/release-reservation``
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