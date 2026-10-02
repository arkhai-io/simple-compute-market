"""The typed bare-metal lease client over a provisioning transport.

The transport here is a recording fake: signing and response verification are
the compute-provisioning client's, proven in that package and, against the
mounted routes, in the provisioning service's integration suite.
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

import pytest

from arkhai_bare_metal import (
    BARE_METAL_LEASES_PATH,
    BARE_METAL_PROVISIONING_ROUTES,
    BareMetalLeaseClient,
    BareMetalLeaseCreate,
)

_VIEW = {
    "capacity_reservation_id": "reservation-1",
    "escrow_uid": "escrow-1",
    "host_id": "bm-node-1",
    "physical_host_id": "physical-1",
    "state": "leased",
    "access_ref": {"ssh_user": "tenant-a"},
}


class _Transport:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[str, str, Any, str | None]] = []
        self.routes: list[str] = []

    async def authenticated_request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        request_id: str | None = None,
        route=None,
    ) -> Any:
        # Every call names its declared route, and the declaration describes
        # exactly the request the client sends.
        assert route["method"] == method
        assert re.fullmatch(route["path"], path), (route["path"], path)
        self.calls.append((method, path, body, request_id))
        self.routes.append(route["operation"])
        return self.response


def _run(coroutine):
    return asyncio.run(coroutine)


def test_register_sends_the_registration_and_reads_the_view() -> None:
    transport = _Transport(_VIEW)
    registration = BareMetalLeaseCreate(
        capacity_reservation_id="reservation-1",
        escrow_uid="escrow-1",
        host_id="bm-node-1",
        physical_host_id="physical-1",
        access_ref={"ssh_user": "tenant-a"},
        lease_end_utc=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )

    view = _run(
        BareMetalLeaseClient(transport).register_lease(registration, request_id="r-1")
    )

    ((method, path, body, request_id),) = transport.calls
    assert (method, path, request_id) == ("POST", BARE_METAL_LEASES_PATH, "r-1")
    assert transport.routes == ["provisioning_bare_metal_lease_create"]
    assert body == {
        "capacity_reservation_id": "reservation-1",
        "escrow_uid": "escrow-1",
        "host_id": "bm-node-1",
        "physical_host_id": "physical-1",
        "access_ref": {"ssh_user": "tenant-a"},
        "lease_end_utc": "2099-01-01T00:00:00Z",
    }
    assert view.capacity_reservation_id == "reservation-1"
    assert view.access_ref == {"ssh_user": "tenant-a"}


def test_reads_address_one_lease_by_reservation_or_escrow() -> None:
    transport = _Transport(_VIEW)
    client = BareMetalLeaseClient(transport)

    _run(client.get_lease("reservation/1"))
    _run(client.get_lease_by_escrow("escrow-1"))

    assert [call[:2] for call in transport.calls] == [
        ("GET", BARE_METAL_LEASES_PATH + "reservation%2F1"),
        ("GET", BARE_METAL_LEASES_PATH + "by-escrow/escrow-1"),
    ]
    assert transport.routes == [
        "provisioning_bare_metal_lease_get",
        "provisioning_bare_metal_lease_by_escrow",
    ]


def test_list_reads_every_view_and_refuses_a_non_list() -> None:
    assert [
        view.host_id
        for view in _run(BareMetalLeaseClient(_Transport([_VIEW])).list_leases())
    ] == ["bm-node-1"]

    with pytest.raises(ValueError):
        _run(BareMetalLeaseClient(_Transport(_VIEW)).list_leases())


def test_an_empty_identifier_is_refused_before_any_request() -> None:
    transport = _Transport(_VIEW)

    with pytest.raises(ValueError):
        _run(BareMetalLeaseClient(transport).get_lease(" "))

    assert transport.calls == []


def test_every_declared_route_names_its_roles_and_a_unique_operation() -> None:
    operations = [route["operation"] for route in BARE_METAL_PROVISIONING_ROUTES]

    assert len(set(operations)) == len(operations)
    for route in BARE_METAL_PROVISIONING_ROUTES:
        assert route["roles"] and set(route["roles"]) <= {"seller", "admin"}
        re.compile(route["path"])
