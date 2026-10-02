"""Bare metal's provisioning routes and the typed client for its lease routes.

The compute-provisioning client is a family-kit client and carries no domain's
vocabulary, so these methods wrap its market-neutral ``authenticated_request``.
Any transport offering that coroutine works; the request is signed, and the
response's authority signature verified, by the transport.

Bare metal declares the signed contract of each route it mounts on the
provisioning service as plain data, so this package needs no dependency on the
compute family kit: the operation and resource a request signs, and the caller
roles the route admits. The provisioning service assembles these declarations
into the table its request authentication reads, and the client names the
declaration for each call it makes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol
from urllib.parse import quote

from .schema import BareMetalLeaseCreate, BareMetalLeaseView

BARE_METAL_LEASES_PATH = "/api/v1/bare-metal/leases/"

BARE_METAL_LEASE_ROUTES = (
    {
        "method": "GET",
        "path": r"/api/v1/bare-metal/leases/?",
        "operation": "provisioning_bare_metal_leases_list",
        "roles": ("admin",),
    },
    {
        "method": "POST",
        "path": r"/api/v1/bare-metal/leases/?",
        "operation": "provisioning_bare_metal_lease_create",
        "roles": ("admin",),
    },
    {
        "method": "GET",
        "path": r"/api/v1/bare-metal/leases/by-escrow/(?P<escrow_uid>[^/]+)",
        "operation": "provisioning_bare_metal_lease_by_escrow",
        "roles": ("admin",),
        "path_resource": "escrow_uid",
    },
    {
        "method": "GET",
        "path": r"/api/v1/bare-metal/leases/(?P<lease_id>[^/]+)",
        "operation": "provisioning_bare_metal_lease_get",
        "roles": ("admin",),
        "path_resource": "lease_id",
    },
)

BARE_METAL_TEST_ROUTES = (
    {
        "method": "POST",
        "path": r"/test/bare-metal/mock-rules",
        "operation": "provisioning_test_bare_metal_rule_add",
        "roles": ("admin",),
    },
    {
        "method": "GET",
        "path": r"/test/bare-metal/mock-rules",
        "operation": "provisioning_test_bare_metal_rules_list",
        "roles": ("admin",),
    },
    {
        "method": "DELETE",
        "path": r"/test/bare-metal/mock-rules/(?P<rule_id>[^/]+)",
        "operation": "provisioning_test_bare_metal_rule_delete",
        "roles": ("admin",),
        "path_resource": "rule_id",
    },
    {
        "method": "POST",
        "path": r"/test/bare-metal/mock-rules/(?P<rule_id>[^/]+)/resume",
        "operation": "provisioning_test_bare_metal_rule_resume",
        "roles": ("admin",),
        "path_resource": "rule_id",
    },
    {
        "method": "POST",
        "path": r"/test/bare-metal/evaluate-job",
        "operation": "provisioning_test_bare_metal_job_evaluate",
        "roles": ("admin",),
    },
)

#: Every route bare metal mounts on the provisioning service; the test routes
#: are mounted only under the mock profile.
BARE_METAL_PROVISIONING_ROUTES = BARE_METAL_LEASE_ROUTES + BARE_METAL_TEST_ROUTES

_LIST_ROUTE, _CREATE_ROUTE, _BY_ESCROW_ROUTE, _GET_ROUTE = BARE_METAL_LEASE_ROUTES


class ProvisioningTransport(Protocol):
    async def authenticated_request(
        self,
        method: str,
        path: str,
        body: Any = ...,
        *,
        request_id: str | None = None,
        route: Mapping[str, Any] | None = None,
    ) -> Any: ...


def _segment(value: str) -> str:
    if not value or not value.strip():
        raise ValueError("a lease path identifier must be non-empty")
    return quote(value, safe="")


class BareMetalLeaseClient:
    """Bare-metal lease administration on a provisioning service.

    Registering a lease attaches it to its live reservation and, unless the
    request names an existing grant job, submits the access grant.
    """

    def __init__(self, transport: ProvisioningTransport) -> None:
        self._transport = transport

    async def register_lease(
        self,
        registration: BareMetalLeaseCreate,
        *,
        request_id: str | None = None,
    ) -> BareMetalLeaseView:
        return BareMetalLeaseView.model_validate(
            await self._transport.authenticated_request(
                "POST",
                BARE_METAL_LEASES_PATH,
                registration.model_dump(mode="json", exclude_none=True),
                request_id=request_id,
                route=_CREATE_ROUTE,
            )
        )

    async def list_leases(
        self, *, request_id: str | None = None
    ) -> list[BareMetalLeaseView]:
        payload = await self._transport.authenticated_request(
            "GET", BARE_METAL_LEASES_PATH, request_id=request_id, route=_LIST_ROUTE
        )
        if not isinstance(payload, list):
            raise ValueError("bare-metal lease list response must be a list")
        return [BareMetalLeaseView.model_validate(item) for item in payload]

    async def get_lease(
        self,
        capacity_reservation_id: str,
        *,
        request_id: str | None = None,
    ) -> BareMetalLeaseView:
        return BareMetalLeaseView.model_validate(
            await self._transport.authenticated_request(
                "GET",
                BARE_METAL_LEASES_PATH + _segment(capacity_reservation_id),
                request_id=request_id,
                route=_GET_ROUTE,
            )
        )

    async def get_lease_by_escrow(
        self,
        escrow_uid: str,
        *,
        request_id: str | None = None,
    ) -> BareMetalLeaseView:
        return BareMetalLeaseView.model_validate(
            await self._transport.authenticated_request(
                "GET",
                f"{BARE_METAL_LEASES_PATH}by-escrow/{_segment(escrow_uid)}",
                request_id=request_id,
                route=_BY_ESCROW_ROUTE,
            )
        )


__all__ = [
    "BARE_METAL_LEASES_PATH",
    "BARE_METAL_LEASE_ROUTES",
    "BARE_METAL_PROVISIONING_ROUTES",
    "BARE_METAL_TEST_ROUTES",
    "BareMetalLeaseClient",
    "ProvisioningTransport",
]
