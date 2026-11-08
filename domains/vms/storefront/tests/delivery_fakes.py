"""A site and a provisioning service at the delivery path's external boundary.

``DeliverySite`` is an aggregate capacity client over one site's reservation
ledger: placement-keyed reserve replay, commit, activation and release, and an
acknowledgement that can be lost after its effect, as the site does.
``DeliveryProvisioning`` schedules and begins one fulfillment per reservation
and reports it active with a VM access delivery.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from compute_provisioning_contracts import (
    FulfillmentAcceptanceResponse,
    FulfillmentScheduleResponse,
    FulfillmentStatusResponse,
    LeaseView,
)
from compute_provisioning_contracts.contracts import lease_state_for_reservation_state
from market_site_client import SiteCapacityClientError

from tests.fulfillment_fixtures import vm_fulfillment_result


class LostAcknowledgement(SiteCapacityClientError):
    """The site applied the effect and its answer never arrived."""


class DeliverySite:
    def __init__(self, site_id: str) -> None:
        self.site_id = site_id
        self.site_names = (site_id,)
        self.rows: dict[str, dict[str, Any]] = {}
        self.keys: dict[str, tuple[str, dict[str, Any]]] = {}
        self.lose: dict[str, int] = {}
        #: Each commit's requested window, as sent.
        self.commits: list[tuple[str, str | None, str | None]] = []

    def _answer(self, operation: str, row: dict[str, Any]) -> dict[str, Any]:
        if self.lose.get(operation, 0) > 0:
            self.lose[operation] -= 1
            raise LostAcknowledgement(f"{operation} acknowledgement lost")
        return {**row, "site": self.site_id}

    def hold(self, reservation_id: str, *, placement_key: str, request: dict[str, Any]) -> None:
        """A hold placed at acceptance, as the site recorded it."""
        self.rows[reservation_id] = {
            "capacity_reservation_id": reservation_id, "state": "reserved", "deal_ref": {},
            "lease_start_utc": None, "lease_end_utc": None, "activated_at_utc": None,
        }
        self.keys[placement_key] = (reservation_id, request)

    async def reserve(self, *, claim, deal_ref, ttl_seconds=None, lease_start_utc=None,
                      lease_duration_seconds=None, site=None):
        key = (deal_ref or {}).get("placement_key")
        request = {"claim": dict(claim), "start": lease_start_utc, "duration": lease_duration_seconds}
        if key is not None and key in self.keys:
            reservation_id, recorded = self.keys[key]
            if recorded != request:
                raise SiteCapacityClientError("placement replay changes the request", status_code=409)
            return self._answer("reserve", self.rows[reservation_id])
        reservation_id = f"res-{len(self.rows) + 1}"
        self.rows[reservation_id] = {
            "capacity_reservation_id": reservation_id, "state": "reserved", "deal_ref": dict(deal_ref or {}),
            "lease_start_utc": None, "lease_end_utc": None, "activated_at_utc": None,
        }
        if key is not None:
            self.keys[key] = (reservation_id, request)
        return self._answer("reserve", self.rows[reservation_id])

    async def commit(self, *, resource_id, capacity_reservation_id, lease_start_utc=None,
                     lease_end_utc=None, idempotency_ref=None, deal_ref=None, site_id=None):
        self.commits.append((capacity_reservation_id, lease_start_utc, lease_end_utc))
        row = self.rows.get(capacity_reservation_id)
        if row is None:
            raise SiteCapacityClientError("unknown reservation", status_code=404)
        if row["state"] not in ("reserved", "leased"):
            raise SiteCapacityClientError(f"reservation is {row['state']}", status_code=409)
        if row["state"] == "reserved":
            row.update(state="leased", lease_start_utc=lease_start_utc, lease_end_utc=lease_end_utc)
        return self._answer("commit", row)

    async def release(self, *, capacity_reservation_id, deal_ref=None, failure_reason=None,
                      failure_message=None, site_id=None):
        row = self.rows[capacity_reservation_id]
        row["state"] = "released"
        return self._answer("release", row)

    async def truncate_lease(self, *, capacity_reservation_id, lease_end_utc, site_id=None):
        row = self.rows[capacity_reservation_id]
        row["lease_end_utc"] = lease_end_utc
        return {**row, "site": self.site_id}

    async def activate_lease(self, *, capacity_reservation_id, site_id=None):
        row = self.rows.get(capacity_reservation_id)
        if row is None:
            raise SiteCapacityClientError("unknown reservation", status_code=404)
        if row["state"] != "leased":
            raise SiteCapacityClientError(f"reservation is {row['state']}", status_code=409)
        if row["activated_at_utc"] is None:
            row["activated_at_utc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        return self._answer("activate", row)


class DeliveryProvisioning:
    """The provisioning service's per-site fulfillment surface."""

    def __init__(self, site: DeliverySite) -> None:
        self.site = site
        self.scheduled: list[str] = []
        self.by_reservation: dict[str, str] = {}
        self.begins: list[Any] = []
        self.credentials = ({"role": "tenant", "password": "tenant-pw", "key_type": "generated"},)

    async def schedule_resource(self, request, *, site_id=None):
        self.scheduled.append(request.capacity_reservation_id)
        return FulfillmentScheduleResponse(
            settlement_resource_id=f"vm-resource-{request.capacity_reservation_id}",
            pool_id="pool", resource_kind="vm", provider="mock",
        )

    async def begin_fulfillment(self, body, *, site_id=None):
        self.begins.append(body)
        reservation_id = body.capacity_reservation_id
        fulfillment_id = self.by_reservation.setdefault(reservation_id, f"ful-{len(self.by_reservation) + 1}")
        return FulfillmentAcceptanceResponse(
            fulfillment_id=fulfillment_id, capacity_reservation_id=reservation_id, state="dispatch_pending",
        )

    async def get_fulfillment_status(self, fulfillment_id, *, capacity_reservation_id=None, site_id=None):
        return FulfillmentStatusResponse(
            fulfillment_id=fulfillment_id, capacity_reservation_id=capacity_reservation_id, state="active",
        )

    async def get_fulfillment_result(self, fulfillment_id, *, capacity_reservation_id=None, site_id=None):
        return vm_fulfillment_result(
            fulfillment_id=fulfillment_id, capacity_reservation_id=capacity_reservation_id,
            credentials=self.credentials,
        )

    async def get_lease(self, capacity_reservation_id, *, site_id):
        row = self.site.rows[capacity_reservation_id]
        return LeaseView(
            capacity_reservation_id=capacity_reservation_id, deal_ref=row["deal_ref"], offering_mode="vm",
            executor_target="host-1", lease_start_utc=row["lease_start_utc"],
            lease_end_utc=row["lease_end_utc"], status=lease_state_for_reservation_state(row["state"]),
        )
