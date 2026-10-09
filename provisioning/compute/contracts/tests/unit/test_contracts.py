"""The family's contract models and its own route contracts."""

import re
import pytest
from pydantic import ValidationError
import compute_provisioning_contracts as contracts
from compute_provisioning_contracts import (
    PROVISIONING_ROUTE_CONTRACTS,
    LeaseTermination,
    resolve_provisioning_route,
)


def _termination(**overrides):
    return LeaseTermination(**overrides)


def test_contract_rejects_the_retired_major_version():
    """A 1.x caller carries the retired offering-mode spelling, so the
    contract refuses it rather than coercing it."""
    with pytest.raises(ValidationError, match="supported majors: 2"):
        _termination(contract_version="1.0")


def test_contract_rejects_an_unsupported_future_major_version():
    with pytest.raises(ValidationError, match="supported majors: 2"):
        _termination(contract_version="3.0")


@pytest.mark.parametrize(
    "contract",
    [
        contract
        for contract in PROVISIONING_ROUTE_CONTRACTS
        if contract.method in {"POST", "PUT", "PATCH", "DELETE"}
    ],
    ids=lambda contract: contract.operation,
)
def test_every_bound_mutation_contract_is_reachable(contract):
    path = re.sub(
        r"\(\?P<[^>]+>\[\^/\]\+\)",
        "resource-1",
        contract.pattern.pattern,
    )
    path = path.replace("(?P<trust_role>admin|seller)", "admin").replace(
        "/?",
        "",
    ).removesuffix("$")
    body = (
        {contract.body_resource: "resource-1"}
        if contract.body_resource is not None
        else {}
    )

    operation, resource = resolve_provisioning_route(
        contract.method,
        path,
        body,
    )

    assert operation == contract.operation
    assert resource == contract.match(contract.method, path, body)


def test_family_routes_name_their_roles():
    """Every family route admits the administrator; a seller's routes admit the
    seller too, and system routes are the administrator's alone."""
    routes = {contract.operation: contract for contract in PROVISIONING_ROUTE_CONTRACTS}

    for operation in (
        "provisioning_fulfillment_status",
        "provisioning_fulfillment_result",
        "provisioning_fulfillment_begin",
    ):
        assert routes[operation].allowed_roles == ("seller", "admin")
    assert routes["provisioning_system_status"].allowed_roles == ("admin",)


def test_the_family_table_declares_no_route_another_owner_owns():
    """Site capacity, pools, capacity definitions, host import, and relays are
    declared by their owners and assembled by the service."""
    patterns = [contract.pattern.pattern for contract in PROVISIONING_ROUTE_CONTRACTS]
    for prefix in ("/api/v1/capacity", "/api/v1/pools", "/api/v1/relays", "/api/v1/hosts/import"):
        assert not [pattern for pattern in patterns if pattern.startswith(prefix)], prefix


def test_every_fulfillment_route_is_a_family_route():
    """Fulfillment is the family's; each of its routes resolves in the family table."""
    for method, path, body in (
        ("POST", "/api/v1/fulfillment/schedule", {"capacity_reservation_id": "r-1"}),
        ("POST", "/api/v1/fulfillment/validate", {"capacity_reservation_id": "r-1"}),
        ("POST", "/api/v1/fulfillment/begin", {"capacity_reservation_id": "r-1"}),
        ("POST", "/api/v1/fulfillment/f-1/begin-teardown", {}),
        ("GET", "/api/v1/fulfillment/f-1/status", None),
        ("GET", "/api/v1/fulfillment/f-1/result", None),
    ):
        operation, _ = resolve_provisioning_route(method, path, body)
        assert operation.startswith("provisioning_fulfillment")


def test_no_contract_registers_a_lease():
    """No route writes a lease: commit records its window, provisioning its
    target at activation, and the lease lifecycle its release."""
    assert not hasattr(contracts, "LeaseRegistration")
