"""The host definitions wire models and their two route contracts.

An entry states its whole host with the registration contract's field names and
refuses what it does not define; the import's response carries whether it
applied, its diff, the hosts it does not name, and every problem; and the export
and import paths resolve to their own contracts, never to a single host's.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from compute_provisioning_contracts import (
    ADMIN_PROVISIONING_OPERATIONS,
    PROVISIONING_ROUTE_TABLE,
    HostDefinition,
    HostDefinitionProblem,
    HostDefinitionProblemCode,
    HostDefinitionsDiff,
    HostDefinitionsImportRequest,
    HostDefinitionsImportResponse,
    resolve_provisioning_route,
)

_ENTRY = {
    "host_id": "kvm1",
    "pool_id": "vm-default",
    "enabled": False,
    "connection": {
        "kind": "ssh",
        "version": 2,
        "public": {"ssh_host": "192.0.2.5", "key_path": "/keys/id_ed25519"},
    },
}


def test_an_entry_round_trips() -> None:
    entry = HostDefinition.model_validate(_ENTRY)

    assert HostDefinition.model_validate(entry.model_dump(mode="json")) == entry
    assert entry.model_dump(mode="json") == _ENTRY


def test_an_entry_omitting_its_pool_and_enabled_state_is_unplaced_and_enabled() -> None:
    entry = HostDefinition.model_validate(
        {"host_id": "kvm1", "connection": _ENTRY["connection"]}
    )
    explicit_null = HostDefinition.model_validate({**_ENTRY, "pool_id": None, "enabled": True})

    assert (entry.pool_id, entry.enabled) == (None, True)
    assert explicit_null == entry


@pytest.mark.parametrize(
    ("change", "location"),
    [
        ({"enabled": None}, ("enabled",)),
        ({"enabled": "true"}, ("enabled",)),
        ({"connection": {**_ENTRY["connection"], "version": "2"}}, ("connection", "version")),
        ({"rack": "r1"}, ("rack",)),
        ({"connection": {**_ENTRY["connection"], "secrets": {"private_key": "k"}}}, ("connection", "secrets")),
    ],
)
def test_an_entry_refuses_a_wrong_type_and_any_field_it_does_not_define(change, location) -> None:
    """Strictness is the model's own, so no caller can validate an entry
    leniently by leaving a flag out."""
    with pytest.raises(ValidationError) as refused:
        HostDefinition.model_validate({**_ENTRY, **change})

    assert [error["loc"] for error in refused.value.errors()] == [location]


def test_an_entry_requires_its_connection_version() -> None:
    connection = {key: value for key, value in _ENTRY["connection"].items() if key != "version"}

    with pytest.raises(ValidationError) as refused:
        HostDefinition.model_validate({**_ENTRY, "connection": connection})

    assert [(e["loc"], e["type"]) for e in refused.value.errors()] == [
        (("connection", "version"), "missing")
    ]


@pytest.mark.parametrize(
    ("change", "location", "error_type"),
    [
        ({"host_id": ""}, ("host_id",), "string_too_short"),
        ({"pool_id": ""}, ("pool_id",), "string_too_short"),
        ({"connection": {**_ENTRY["connection"], "kind": ""}}, ("connection", "kind"), "string_too_short"),
        ({"connection": {**_ENTRY["connection"], "version": 0}}, ("connection", "version"), "greater_than_equal"),
        ({"connection": {**_ENTRY["connection"], "public": ["ssh_host"]}}, ("connection", "public"), "dict_type"),
        ({"connection": "ssh"}, ("connection",), "model_type"),
    ],
)
def test_an_entry_refuses_a_value_outside_its_bounds(change, location, error_type) -> None:
    with pytest.raises(ValidationError) as refused:
        HostDefinition.model_validate({**_ENTRY, **change})

    assert [(e["loc"], e["type"]) for e in refused.value.errors()] == [(location, error_type)]


@pytest.mark.parametrize("field", ["host_id", "connection"])
def test_an_entry_requires_its_host_id_and_connection(field) -> None:
    with pytest.raises(ValidationError) as refused:
        HostDefinition.model_validate({k: v for k, v in _ENTRY.items() if k != field})

    assert [(e["loc"], e["type"]) for e in refused.value.errors()] == [((field,), "missing")]


def test_an_entry_requires_its_connection_kind() -> None:
    connection = {key: value for key, value in _ENTRY["connection"].items() if key != "kind"}

    with pytest.raises(ValidationError) as refused:
        HostDefinition.model_validate({**_ENTRY, "connection": connection})

    assert [(e["loc"], e["type"]) for e in refused.value.errors()] == [(("connection", "kind"), "missing")]


def test_the_import_models_round_trip() -> None:
    request = HostDefinitionsImportRequest(yaml_text="hosts: []\n", validate_only=True)
    response = HostDefinitionsImportResponse(
        applied=True,
        diff=HostDefinitionsDiff(created=["kvm2"], updated=["kvm1"], unchanged=["bm1"]),
        not_named=["legacy"],
    )
    refused = HostDefinitionsImportResponse(
        applied=False,
        problems=[
            HostDefinitionProblem(
                path="hosts[0].pool_id",
                code=HostDefinitionProblemCode.POOL_CHANGE_REFUSED,
                message="relay leases held",
            )
        ],
    )

    assert HostDefinitionsImportRequest.model_validate(request.model_dump()) == request
    assert HostDefinitionsImportResponse.model_validate(response.model_dump(mode="json")) == response
    assert HostDefinitionsImportResponse.model_validate(refused.model_dump(mode="json")) == refused
    assert refused.model_dump(mode="json")["problems"][0]["code"] == "pool_change_refused"
    assert HostDefinitionsImportRequest(yaml_text="").validate_only is False


def test_a_refused_response_parses_with_every_problem() -> None:
    body = {
        "applied": False,
        "diff": {"created": ["kvm2"], "updated": [], "unchanged": []},
        "not_named": [],
        "problems": [
            {"path": "hosts[0].pool_id", "code": "unknown_pool", "message": "no pool"},
            {"path": "hosts[1].pool_id", "code": "pool_change_refused", "message": "relay"},
        ],
    }

    response = HostDefinitionsImportResponse.model_validate(body)

    assert response.applied is False
    assert [problem.code for problem in response.problems] == [
        HostDefinitionProblemCode.UNKNOWN_POOL,
        HostDefinitionProblemCode.POOL_CHANGE_REFUSED,
    ]


def test_a_problem_code_the_reader_does_not_know_still_parses() -> None:
    problem = HostDefinitionProblem(path="hosts[0]", code="a_newer_code", message="m")

    assert problem.code == "a_newer_code"
    assert HostDefinitionProblemCode.POOL_CHANGE_REFUSED == "pool_change_refused"


@pytest.mark.parametrize(
    ("method", "path", "operation"),
    [
        ("GET", "/api/v1/hosts/definitions/export", "provisioning_host_definitions_export"),
        ("POST", "/api/v1/hosts/definitions/import", "provisioning_host_definitions_import"),
    ],
)
def test_each_definitions_route_resolves_to_its_own_contract(method, path, operation) -> None:
    assert resolve_provisioning_route(method, path, {}) == (operation, "")
    contract, _ = PROVISIONING_ROUTE_TABLE.resolve(method, path, {})
    assert contract.allowed_roles == ("admin",)
    assert operation in ADMIN_PROVISIONING_OPERATIONS


def test_a_single_host_route_claims_neither_definitions_path() -> None:
    """``/hosts/{host}`` matches one segment, and the definitions paths have two,
    so no host name is reserved by them and a host named ``definitions`` stays
    readable."""
    contracts = {contract.operation: contract for contract in PROVISIONING_ROUTE_TABLE.contracts}

    for operation in ("provisioning_host_get", "provisioning_host_update"):
        single_host = contracts[operation]
        for path in ("/api/v1/hosts/definitions/export", "/api/v1/hosts/definitions/import"):
            assert single_host.pattern.fullmatch(path) is None
    assert resolve_provisioning_route("GET", "/api/v1/hosts/definitions", {}) == (
        "provisioning_host_get",
        "definitions",
    )
