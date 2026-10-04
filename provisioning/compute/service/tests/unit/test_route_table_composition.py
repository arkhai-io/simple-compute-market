"""The provisioning service authenticates every route each owner declares.

The family's routes, the site's capacity and capacity-definition contracts, the
pool declarations, the Ansible host import, and each adapter's declarations are
assembled into one table; every route resolves to its own contract, with no two
contributions claiming one path, and each site route is canonicalized as the
site client signs it.
"""

from __future__ import annotations

import re

import pytest
from bare_metal_provisioning_adapter.routers import bare_metal_route_contracts
from compute_provisioning_contracts import PROVISIONING_ROUTE_CONTRACTS
from vm_provisioning_adapter.routers import vm_route_contracts

from compute_provisioning_service.route_table import (
    assemble_service_route_table,
    canonical_request_body,
    is_site_route,
)

_TABLE = assemble_service_route_table(vm_route_contracts(), bare_metal_route_contracts())


def _concrete_path(pattern: str) -> str:
    path = re.sub(r"\(\?P<[^>]+>\[\^/\]\+\)", "resource-1", pattern)
    path = path.replace("(?P<trust_role>admin|seller)", "admin")
    return path.replace("/?", "").removesuffix("$")


@pytest.mark.parametrize("contract", _TABLE.contracts, ids=lambda contract: contract.operation)
def test_every_assembled_route_resolves_to_itself(contract) -> None:
    path = _concrete_path(contract.pattern.pattern)
    body = {contract.body_resource: "resource-1"} if contract.body_resource else {}

    resolved, resource = _TABLE.resolve(contract.method, path, body)

    assert resolved is contract
    assert resource == contract.match(contract.method, path, body)


def test_every_contributed_route_admits_admin() -> None:
    family = {contract.operation for contract in PROVISIONING_ROUTE_CONTRACTS}
    refused = [
        contract.operation
        for contract in _TABLE.contracts
        if contract.operation not in family and "admin" not in contract.allowed_roles
    ]
    assert refused == []


def test_site_routes_admit_their_named_role_and_admin() -> None:
    routes = {contract.operation: contract for contract in _TABLE.contracts}
    assert routes["capacity_reserve"].allowed_roles == ("seller", "admin")
    assert routes["provisioning_capacity_definitions_import"].allowed_roles == ("admin",)


@pytest.mark.parametrize(
    ("body", "expected_resource"),
    [
        ({"deal_ref": {"settlement_obligation_ref": "obligation-1"}}, ""),
        ({"capacity_reservation_id": "reservation-1"}, "reservation-1"),
    ],
)
def test_capacity_release_route_allows_optional_reservation_hint(body, expected_resource) -> None:
    contract, resource = _TABLE.resolve("POST", "/api/v1/capacity/releases", body)
    assert (contract.operation, resource) == ("capacity_release", expected_resource)


def test_site_queries_are_canonicalized_as_the_site_client_signs_them() -> None:
    assert is_site_route("GET", "/api/v1/capacity/reservations")
    assert canonical_request_body(
        "GET", "/api/v1/capacity/reservations", query={"state": "held", "escrow_uid": None}
    ) == {"state": "held"}
    assert canonical_request_body("GET", "/api/v1/capacity/events") == {"after": 0, "limit": 500}
    assert canonical_request_body(
        "GET", "/api/v1/capacity/events", query={"limit": "25", "after": "7"}
    ) == {"after": 7, "limit": 25}


def test_family_queries_keep_the_family_form() -> None:
    assert not is_site_route("GET", "/api/v1/jobs/")
    assert canonical_request_body("GET", "/api/v1/jobs/", query={"limit": 5}) == {
        "query": {"limit": 5}
    }
