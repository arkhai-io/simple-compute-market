"""The compute family's lease routes, without a web framework.

A lease records and releases; it never delivers. Its routes register a lease's
tail on a capacity reservation, read and list leases, and drive release:
terminate, release-oversight, retry-release, and force-release. Every route
addresses a lease by its capacity reservation id, and every route reports the
neutral ``LeaseView``, whatever the reservation's offering mode. A domain extends
what a lease reports only by contributing a versioned projection, never by
adding lease routes; delivery happens through fulfillment.

``LeaseRouteService`` reports a refusal as a ``ProvisioningRouteError`` the
service's binding turns into a response: a lease that does not exist is 404, and
a request the lease's current state refuses (a registration naming another
target, a terminate of a lease being handed to an operator) is 409.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from compute_provisioning_contracts import (
    LeaseForceRelease,
    LeaseListResponse,
    LeaseRegistration,
    LeaseReleaseOversight,
    LeaseRetryRelease,
    LeaseState,
    LeaseTermination,
    LeaseView,
    lease_state_for_reservation_state,
)
from market_site.ledger import CapacityConflictError

from compute_provisioning.executor_leases import (
    ExecutorLeaseRegistration,
    ExecutorLeaseService,
)
from compute_provisioning.lease_lifecycle import (
    InvalidLeaseStateError,
    LeaseLifecycleService,
    LeaseNotFoundError,
)
from compute_provisioning.route_errors import ProvisioningRouteError


def _parsed(value: Any) -> datetime | None:
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def lease_view(reservation: dict[str, Any]) -> LeaseView:
    """The neutral lease view of a reservation carrying a lease.

    Every reservation records the offering mode its claim named; one without it
    is corrupt data, refused as a conflict rather than reported with a guess.
    """
    offering_mode = reservation.get("offering_mode")
    if not offering_mode:
        raise ProvisioningRouteError(
            409, "reservation records no explicit offering mode"
        )
    return LeaseView(
        capacity_reservation_id=str(reservation["capacity_reservation_id"]),
        deal_ref=dict(reservation.get("deal_ref") or {}),
        offering_mode=str(offering_mode),
        executor_target=str(reservation.get("executor_target") or ""),
        lease_start_utc=_parsed(reservation.get("lease_start_utc")),
        lease_end_utc=_parsed(reservation.get("lease_end_utc")),
        create_job_id=reservation.get("create_job_id"),
        status=lease_state_for_reservation_state(str(reservation.get("state"))),
        release_job_id=reservation.get("release_job_id"),
        failure_reason=reservation.get("failure_reason"),
        failure_message=reservation.get("failure_message"),
    )


def _refusal(exc: Exception) -> ProvisioningRouteError:
    if isinstance(exc, LeaseNotFoundError):
        return ProvisioningRouteError(404, str(exc))
    return ProvisioningRouteError(409, str(exc))


class LeaseRouteService:
    """Serve the lease routes over the lease registry and the lease lifecycle."""

    def __init__(
        self,
        leases: ExecutorLeaseService,
        lifecycle: LeaseLifecycleService,
    ) -> None:
        self._leases = leases
        self._lifecycle = lifecycle

    def register(self, body: LeaseRegistration) -> LeaseView:
        """Record a lease's tail once; a repeat naming the same target and start
        returns it unchanged, and one naming another is refused. A window the
        site already recorded is kept."""
        try:
            reservation = self._leases.register_lease(
                ExecutorLeaseRegistration(
                    capacity_reservation_id=body.capacity_reservation_id,
                    executor_target=body.executor_target,
                    deal_ref=dict(body.deal_ref),
                    lease_start_utc=body.lease_start_utc,
                    lease_end_utc=body.lease_end_utc,
                )
            )
        except (LeaseNotFoundError, CapacityConflictError) as exc:
            raise _refusal(exc) from exc
        return lease_view(reservation)

    def get(self, capacity_reservation_id: str) -> LeaseView:
        try:
            return lease_view(self._leases.get_lease(capacity_reservation_id))
        except LeaseNotFoundError as exc:
            raise _refusal(exc) from exc

    def list(
        self,
        *,
        status: LeaseState | None = None,
        offering_mode: str | None = None,
    ) -> LeaseListResponse:
        """Every lease at the site, filtered by lease status and offering mode."""
        views = [
            view
            for view in (lease_view(reservation) for reservation in self._leases.list_leases())
            if (status is None or view.status == status)
            and (offering_mode is None or view.offering_mode == offering_mode)
        ]
        return LeaseListResponse(leases=views, total=len(views))

    async def terminate(
        self, capacity_reservation_id: str, body: LeaseTermination
    ) -> LeaseView:
        try:
            return lease_view(
                await self._lifecycle.terminate_lease(capacity_reservation_id, body)
            )
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _refusal(exc) from exc

    def release_oversight(
        self, capacity_reservation_id: str, body: LeaseReleaseOversight
    ) -> LeaseView:
        try:
            return lease_view(
                self._lifecycle.release_oversight(capacity_reservation_id, body)
            )
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _refusal(exc) from exc

    async def retry_release(
        self, capacity_reservation_id: str, body: LeaseRetryRelease
    ) -> LeaseView:
        try:
            return lease_view(
                await self._lifecycle.retry_release(capacity_reservation_id, body)
            )
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _refusal(exc) from exc

    async def force_release(
        self, capacity_reservation_id: str, body: LeaseForceRelease
    ) -> LeaseView:
        try:
            return lease_view(
                await self._lifecycle.force_release(capacity_reservation_id, body)
            )
        except (LeaseNotFoundError, InvalidLeaseStateError) as exc:
            raise _refusal(exc) from exc


__all__ = ["LeaseRouteService", "lease_view"]
