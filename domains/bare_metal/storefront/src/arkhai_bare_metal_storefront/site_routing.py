"""Durable selected-site routing for bare-metal agreement lifecycle calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .site_capacity import BareMetalSiteCapacity
from .site_config import TrustedSiteBindings
from .sqlite_client import SQLiteClient

_ROUTING_KEY_PARTS = (
    "admin_key",
    "authority",
    "credential",
    "service_url",
    "site_id",
    "url",
)


class AgreementSiteRoutingError(ValueError):
    """Agreement routing is unavailable, conflicting, or untrusted."""


@dataclass(frozen=True)
class AgreementSiteRoute:
    negotiation_id: str
    site_id: str
    capacity_reservation_id: str
    reserved_resource_id: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AgreementSiteRoute":
        return cls(
            negotiation_id=str(value["negotiation_id"]),
            site_id=str(value["site_id"]),
            capacity_reservation_id=str(value["capacity_reservation_id"]),
            reserved_resource_id=str(value["reserved_resource_id"]),
        )


class AgreementSiteRouter:
    """Select once through trusted clients, then route only by durable site ID."""

    def __init__(
        self,
        *,
        db: SQLiteClient,
        sites: TrustedSiteBindings,
        capacity: BareMetalSiteCapacity,
    ) -> None:
        self._db = db
        self._sites = sites
        self._capacity = capacity

    async def reserve_for_agreement(
        self,
        *,
        negotiation_id: str,
        claim: Mapping[str, Any],
        ttl_seconds: float | None = None,
        lease_start_utc: str | None = None,
        lease_duration_seconds: int | None = None,
    ) -> AgreementSiteRoute | None:
        existing = await self.load(negotiation_id=negotiation_id)
        if existing is not None:
            return existing
        _reject_routing_material(claim)
        reserved = await self._capacity.reserve(
            claim=dict(claim),
            deal_ref={"negotiation_id": negotiation_id},
            ttl_seconds=ttl_seconds,
            lease_start_utc=lease_start_utc,
            lease_duration_seconds=lease_duration_seconds,
        )
        if reserved is None:
            return None
        site_id = str(reserved.get("site") or "")
        reservation_id = str(reserved.get("capacity_reservation_id") or "")
        resource_id = str(reserved.get("resource_id") or "")
        if (
            site_id not in self._sites.by_site_id
            or not reservation_id
            or not resource_id
        ):
            raise AgreementSiteRoutingError(
                "trusted capacity placement returned an invalid site or reservation identity",
            )
        try:
            row = await self._db.record_agreement_site_route(
                negotiation_id=negotiation_id,
                site_id=site_id,
                capacity_reservation_id=reservation_id,
                reserved_resource_id=resource_id,
            )
        except ValueError as exc:
            raise AgreementSiteRoutingError(str(exc)) from exc
        return AgreementSiteRoute.from_mapping(row)

    async def load(
        self,
        *,
        negotiation_id: str,
    ) -> AgreementSiteRoute | None:
        row = await self._db.load_agreement_site_route(
            negotiation_id=negotiation_id,
        )
        if row is None:
            return None
        route = AgreementSiteRoute.from_mapping(row)
        if route.site_id not in self._sites.by_site_id:
            raise AgreementSiteRoutingError(
                f"agreement references unconfigured site {route.site_id!r}",
            )
        return route

    async def commit_reservation(
        self,
        *,
        negotiation_id: str,
        lease_start_utc: str | None = None,
        lease_end_utc: str | None = None,
        idempotency_ref: str | None = None,
    ) -> AgreementSiteRoute:
        route = await self.load(negotiation_id=negotiation_id)
        if route is None:
            raise AgreementSiteRoutingError("agreement has no selected site")
        client = self._capacity.client_for_site(route.site_id)
        await client.commit(
            resource_id=route.reserved_resource_id,
            capacity_reservation_id=route.capacity_reservation_id,
            lease_start_utc=lease_start_utc,
            lease_end_utc=lease_end_utc,
            idempotency_ref=idempotency_ref,
        )
        return route

    async def client_for_agreement(self, *, negotiation_id: str) -> Any:
        route = await self.load(negotiation_id=negotiation_id)
        if route is None:
            raise AgreementSiteRoutingError("agreement has no selected site")
        return self._capacity.client_for_site(route.site_id)


def _reject_routing_material(value: Any, *, path: str = "claim") -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key).strip().lower()
            if key in _ROUTING_KEY_PARTS or key.endswith("_url"):
                raise AgreementSiteRoutingError(
                    f"buyer-controlled routing field is forbidden: {path}.{key}",
                )
            _reject_routing_material(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_routing_material(child, path=f"{path}[{index}]")
