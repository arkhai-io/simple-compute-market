"""The compute family's lease routes, bound to ``LeaseRouteService``.

Every offering mode's leases are served here, as the neutral ``LeaseView``. A
lease is addressed by its capacity reservation id; the list is the operator's
view of every lease at the site. No route writes a lease: commit records its
window, and provisioning its target when the fulfillment becomes active.
"""

from __future__ import annotations

from compute_provisioning.leases import LeaseRouteService
from compute_provisioning_contracts import (
    LeaseForceRelease,
    LeaseListResponse,
    LeaseReleaseOversight,
    LeaseRetryRelease,
    LeaseState,
    LeaseTermination,
    LeaseView,
)
from fastapi import APIRouter, Depends, Query

from compute_provisioning_service import container as _container_module
from compute_provisioning_service.controllers.route_errors import routed, routed_async

router = APIRouter(prefix="/contract/leases", tags=["leases"])


def _service() -> LeaseRouteService:
    service = _container_module.resolved_lease_route_service
    if service is None:
        raise RuntimeError("lease route service is not initialised")
    return service


@router.get("", response_model=LeaseListResponse, summary="List leases")
def list_leases(
    status: LeaseState | None = Query(default=None, description="Filter by lease status"),
    offering_mode: str | None = Query(default=None, description="Filter by offering mode"),
    service: LeaseRouteService = Depends(_service),
) -> LeaseListResponse:
    return routed(lambda: service.list(status=status, offering_mode=offering_mode))


@router.get("/{capacity_reservation_id}", response_model=LeaseView, summary="Get a lease")
def get_lease(
    capacity_reservation_id: str, service: LeaseRouteService = Depends(_service)
) -> LeaseView:
    return routed(lambda: service.get(capacity_reservation_id))


@router.post(
    "/{capacity_reservation_id}/terminate", response_model=LeaseView, summary="End a lease now"
)
async def terminate_lease(
    capacity_reservation_id: str,
    body: LeaseTermination,
    service: LeaseRouteService = Depends(_service),
) -> LeaseView:
    return await routed_async(lambda: service.terminate(capacity_reservation_id, body))


@router.post(
    "/{capacity_reservation_id}/release-oversight",
    response_model=LeaseView,
    summary="Hand a lease to an operator",
)
def release_oversight(
    capacity_reservation_id: str,
    body: LeaseReleaseOversight,
    service: LeaseRouteService = Depends(_service),
) -> LeaseView:
    return routed(lambda: service.release_oversight(capacity_reservation_id, body))


@router.post(
    "/{capacity_reservation_id}/retry-release",
    response_model=LeaseView,
    summary="Retry a failed release",
)
async def retry_release(
    capacity_reservation_id: str,
    body: LeaseRetryRelease,
    service: LeaseRouteService = Depends(_service),
) -> LeaseView:
    return await routed_async(lambda: service.retry_release(capacity_reservation_id, body))


@router.post(
    "/{capacity_reservation_id}/force-release",
    response_model=LeaseView,
    summary="Release a lease's capacity on the operator's word",
)
async def force_release(
    capacity_reservation_id: str,
    body: LeaseForceRelease,
    service: LeaseRouteService = Depends(_service),
) -> LeaseView:
    return await routed_async(lambda: service.force_release(capacity_reservation_id, body))
