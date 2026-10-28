"""The family's contract models and its own route contracts."""

import re
import pytest
from pydantic import ValidationError
import compute_provisioning_contracts as contracts
from compute_provisioning_contracts import (
    PROVISIONING_ROUTE_CONTRACTS,
    HostCreate,
    HostResponse,
    HostUpdate,
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


_GPU_FIELDS = {"gpu_count": 8, "gpu_model": "H200"}
_CONNECTION = {"kind": "ssh", "public": {"ssh_host": "192.0.2.1"}}


@pytest.mark.parametrize(
    "model, body",
    [
        (HostCreate, {"host_id": "kvm1", "connection": _CONNECTION}),
        (HostUpdate, {"enabled": False}),
        (
            HostResponse,
            {
                "host_id": "kvm1",
                "connection": {"kind": "ssh", "version": 1, "public": {}},
                "enabled": True,
                "pool_id": None,
                "created_at": "2026-10-28T00:00:00Z",
                "updated_at": "2026-10-28T00:00:00Z",
            },
        ),
    ],
    ids=["create", "update", "response"],
)
def test_a_host_model_ignores_gpu_fields(model, body):
    """A host describes no hardware: a body still carrying the GPU fields
    parses, and the model exposes and serializes neither."""
    parsed = model.model_validate({**body, **_GPU_FIELDS})

    assert parsed == model.model_validate(body)
    assert not set(_GPU_FIELDS) & set(type(parsed).model_fields)
    assert not set(_GPU_FIELDS) & set(parsed.model_dump(mode="json"))


def test_an_update_carrying_only_gpu_fields_sets_nothing():
    """An update naming only the GPU fields sets no field, so it changes
    nothing on the host."""
    assert HostUpdate.model_validate(_GPU_FIELDS).model_fields_set == set()
