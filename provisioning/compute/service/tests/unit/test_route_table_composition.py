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
from compute_provisioning_ansible.host_import import HOST_IMPORT_ROUTES
from compute_provisioning_contracts import PROVISIONING_ROUTE_CONTRACTS, MockRouteMount
from market_resource_pools_contracts import RESOURCE_POOL_ROUTES
from market_site.auth import (
    CAPACITY_DEFINITION_ROUTE_CONTRACTS,
    CAPACITY_ROUTE_CONTRACTS,
)
from vm_provisioning_adapter.routers import vm_route_contracts

from compute_provisioning_service.main import provisioning_route_table
from compute_provisioning_service.route_table import (
    assemble_service_route_table,
    canonical_request_body,
    is_site_route,
)

_TABLE = assemble_service_route_table(vm_route_contracts(), bare_metal_route_contracts())


def _concrete_path(pattern: str) -> str:
    path = re.sub(r"\(\?P<[^>]+>\[\^/\]\+\)", "resource-1", pattern)
    path = path.replace("(?P<trust_role>admin|seller)", "admin")
    return path.replace("/?", "")


def test_the_composition_root_builds_the_complete_table() -> None:
    """Every contribution the service ships composes under the route grammar
    and the overlap check: building the table refuses either at startup."""
    served = {contract.operation for contract in provisioning_route_table.contracts}
    contributions = {
        "family": PROVISIONING_ROUTE_CONTRACTS,
        "site": CAPACITY_ROUTE_CONTRACTS,
        "capacity definitions": CAPACITY_DEFINITION_ROUTE_CONTRACTS,
        "resource pools": RESOURCE_POOL_ROUTES,
        "Ansible host import": HOST_IMPORT_ROUTES,
        "VM": vm_route_contracts(),
        "bare metal": bare_metal_route_contracts(),
    }
    for name, contribution in contributions.items():
        operations = {
            item.operation if hasattr(item, "operation") else item["operation"]
            for item in contribution
        }
        assert operations and operations <= served, name


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/jobs"),
        ("GET", "/api/v1/hosts"),
        ("POST", "/api/v1/hosts"),
        ("GET", "/api/v1/hosts/kvm1/vms"),
        ("POST", "/api/v1/hosts/kvm1/vms"),
        ("GET", "/api/v1/relays"),
        ("POST", "/api/v1/relays"),
        ("GET", "/api/v1/pools"),
        ("POST", "/api/v1/pools"),
    ],
)
def test_a_slashed_and_an_unslashed_path_resolve_to_one_route(method, path) -> None:
    unslashed, _ = provisioning_route_table.resolve(method, path, {})
    slashed, _ = provisioning_route_table.resolve(method, path + "/", {})

    assert slashed is unslashed


@pytest.mark.parametrize("contract", _TABLE.contracts, ids=lambda contract: contract.operation)
def test_every_assembled_route_resolves_to_itself(contract) -> None:
    path = _concrete_path(contract.pattern.pattern)
    body = {contract.body_resource: "resource-1"} if contract.body_resource else {}

    resolved, resource = _TABLE.resolve(contract.method, path, body)

    assert resolved is contract
    assert resource == contract.match(contract.method, path, body)


def _signed(declarations) -> list[tuple]:
    return [
        (d["method"], d["path"], d["operation"], tuple(d["roles"]), d.get("path_resource"))
        for d in declarations
    ]


def test_each_domain_contributes_its_mock_routes_from_the_family_template() -> None:
    vm_mount = MockRouteMount("/test", "provisioning_test")
    bare_metal_mount = MockRouteMount("/test/bare-metal", "provisioning_test_bare_metal")
    vm_mock = [d for d in vm_route_contracts() if d["path"].startswith("/test/")]

    assert _signed(vm_mock) == _signed(vm_mount.route_declarations())
    assert _signed(bare_metal_route_contracts()) == _signed(
        bare_metal_mount.route_declarations()
    )


def test_vm_mock_routes_are_served_at_their_signed_paths_and_operations() -> None:
    vm_mock = {
        (d["method"], d["path"], d["operation"])
        for d in vm_route_contracts()
        if d["path"].startswith("/test/")
    }

    assert vm_mock == {
        ("POST", "/test/mock-rules", "provisioning_test_rule_add"),
        ("GET", "/test/mock-rules", "provisioning_test_rules_list"),
        ("DELETE", "/test/mock-rules/(?P<rule_id>[^/]+)", "provisioning_test_rule_delete"),
        ("POST", "/test/mock-rules/(?P<rule_id>[^/]+)/resume", "provisioning_test_rule_resume"),
        ("POST", "/test/evaluate-job", "provisioning_test_job_evaluate"),
    }


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
