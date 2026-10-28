"""The provisioning route table: the family's routes plus contributed declarations.

A domain declares the routes it mounts as plain data in the route grammar;
assembly refuses an ambiguous table, two contributions that can claim one
request among it, and resolution names why a request matches no route.
"""

from __future__ import annotations

import re

import pytest

from compute_provisioning_contracts import (
    PROVISIONING_ROUTE_CONTRACTS,
    PROVISIONING_ROUTE_TABLE,
    ProvisioningRouteContract,
    ProvisioningRouteMethodNotAllowed,
    ProvisioningRouteNotFound,
    ProvisioningRouteResourceUnbound,
    ProvisioningRouteTable,
    assemble_provisioning_route_table,
    route_contract_from_declaration,
)

_LEASE_GET = {
    "method": "GET",
    "path": r"/api/v1/example/leases/(?P<lease_id>[^/]+)",
    "operation": "provisioning_example_lease_get",
    "roles": ("admin",),
    "path_resource": "lease_id",
}
_LEASE_CREATE = {
    "method": "POST",
    "path": r"/api/v1/example/leases/?",
    "operation": "provisioning_example_lease_create",
    "roles": ("seller", "admin"),
    "body_resource": "capacity_reservation_id",
}


def test_every_family_route_carries_its_roles() -> None:
    assert all(contract.roles for contract in PROVISIONING_ROUTE_CONTRACTS)


def test_every_family_route_admits_the_administrator() -> None:
    assert all("admin" in contract.allowed_roles for contract in PROVISIONING_ROUTE_CONTRACTS)


@pytest.mark.parametrize(
    ("method", "path", "roles"),
    [
        ("GET", "/api/v1/contract/leases/r-1", ("seller", "admin")),
        ("POST", "/api/v1/contract/leases/r-1/terminate", ("seller", "admin")),
        ("GET", "/api/v1/contract/leases", ("admin",)),
        ("POST", "/api/v1/contract/leases/r-1/release-oversight", ("admin",)),
        ("POST", "/api/v1/contract/leases/r-1/retry-release", ("admin",)),
        ("POST", "/api/v1/contract/leases/r-1/force-release", ("admin",)),
    ],
)
def test_the_lease_routes_admit_their_roles(method, path, roles) -> None:
    """A storefront reads and terminates its own leases by reservation id; the
    list and the release controls are the operator's. No route writes a lease."""
    contract, _ = PROVISIONING_ROUTE_TABLE.resolve(method, path, {})

    assert contract.allowed_roles == roles


def test_the_family_table_names_no_domain_route() -> None:
    for method, path in (
        ("GET", "/api/v1/bare-metal/leases/"),
        ("POST", "/api/v1/hosts/kvm1/vms/"),
        ("POST", "/test/mock-rules"),
        ("POST", "/test/bare-metal/mock-rules"),
    ):
        with pytest.raises(ValueError, match="no authenticated provisioning contract"):
            PROVISIONING_ROUTE_TABLE.resolve(method, path)


def test_an_assembled_table_resolves_a_declared_route_with_its_roles() -> None:
    table = assemble_provisioning_route_table((_LEASE_GET, _LEASE_CREATE))

    contract, resource = table.resolve("GET", "/api/v1/example/leases/lease-1")
    assert (contract.operation, resource) == ("provisioning_example_lease_get", "lease-1")
    assert contract.allowed_roles == ("admin",)

    contract, resource = table.resolve(
        "POST", "/api/v1/example/leases/", {"capacity_reservation_id": "r-1"}
    )
    assert (contract.required_role, contract.allowed_roles) == ("seller", ("seller", "admin"))
    assert resource == "r-1"


def test_order_decides_within_one_contribution() -> None:
    """A literal before a capture in one contribution composes: overlap there
    is its owner's to order, not refused."""
    export = {
        "method": "GET",
        "path": r"/api/v1/example/leases/export",
        "operation": "provisioning_example_lease_export",
        "roles": ("admin",),
    }
    table = assemble_provisioning_route_table((export, _LEASE_GET))

    contract, _ = table.resolve("GET", "/api/v1/example/leases/export")
    assert contract.operation == "provisioning_example_lease_export"
    contract, resource = table.resolve("GET", "/api/v1/example/leases/l-1")
    assert (contract.operation, resource) == ("provisioning_example_lease_get", "l-1")


def _route(method: str, path: str, operation: str) -> dict:
    return {"method": method, "path": path, "operation": operation, "roles": ("admin",)}


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (r"/api/v1/example/leases/(?P<lease_id>[^/]+)", r"/api/v1/example/leases/(?P<other>[^/]+)"),
        (r"/api/v1/example/leases/(?P<lease_id>[^/]+)", r"/api/v1/example/leases/export"),
        (r"/api/v1/example/(?P<kind>leases|holds)/x", r"/api/v1/example/holds/(?P<id>[^/]+)"),
        (r"/api/v1/example/(?P<kind>leases|holds)", r"/api/v1/example/(?P<id>[^/]+)"),
        (r"/api/v1/example/leases/?", r"/api/v1/example/leases"),
        (r"/api/v1/example/leases", r"/api/v1/example/(?P<kind>leases|holds)/?"),
    ],
    ids=[
        "capture-capture",
        "capture-literal",
        "alternation-literal",
        "alternation-capture",
        "slash-forms",
        "alternation-slash",
    ],
)
def test_two_contributions_that_can_claim_one_request_are_refused(first, second) -> None:
    with pytest.raises(ValueError, match="different contributions"):
        ProvisioningRouteTable(
            (_route("GET", first, "provisioning_first"),),
            (_route("GET", second, "provisioning_second"),),
        )


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (("GET", r"/api/v1/example/leases/(?P<id>[^/]+)"), ("POST", r"/api/v1/example/leases/(?P<id>[^/]+)")),
        (("GET", r"/api/v1/example/leases/export"), ("GET", r"/api/v1/example/leases/import")),
        (("GET", r"/api/v1/example/(?P<kind>leases|holds)"), ("GET", r"/api/v1/example/pools")),
        (("GET", r"/api/v1/example/leases/?"), ("GET", r"/api/v1/example/leases/(?P<id>[^/]+)")),
        (("GET", r"/api/v1/example/leases"), ("GET", r"/api/v1/example/leases/(?P<id>[^/]+)/logs")),
    ],
    ids=["method", "literal", "alternation", "slash-against-capture", "length"],
)
def test_contributions_no_request_can_join_compose(first, second) -> None:
    table = ProvisioningRouteTable(
        (_route(*first, "provisioning_first"),),
        (_route(*second, "provisioning_second"),),
    )
    assert len(table.contracts) == 2


@pytest.mark.parametrize(
    "path",
    [
        r"/api/v1/example",
        r"/api/v1/example/(?P<id>[^/]+)",
        r"/api/v1/identity/rotations/(?P<trust_role>admin|seller)",
        r"/api/v1/example/(?:leases|holds)/x",
        r"/api/v1/example/leases/?",
        r"/test/bare-metal/mock-rules/(?P<rule_id>[^/]+)/resume",
    ],
    ids=["literal", "capture", "named-alternation", "alternation", "optional-slash", "hyphens"],
)
def test_the_route_grammar_accepts_its_constructs(path) -> None:
    contract = route_contract_from_declaration(_route("GET", path, "provisioning_example"))
    assert contract.pattern.pattern == path


@pytest.mark.parametrize(
    "path",
    [
        r"/api/v1/files/(?P<rest>.*)",
        r"/api/v1/files/.*",
        r"/api/v1/jobs/(?P<job_id>\d+)",
        r"/api/v1/relays/?$",
        r"/api/v1/hosts/?/vms",
        r"api/v1/example",
        r"/api/v1/example.json",
    ],
    ids=["tail-capture", "wildcard", "typed-segment", "terminal-dollar", "mid-optional", "relative", "dot"],
)
def test_a_pattern_outside_the_grammar_is_refused_by_route_name(path) -> None:
    with pytest.raises(ValueError, match="'provisioning_example' pattern .* is outside the route grammar"):
        route_contract_from_declaration(_route("GET", path, "provisioning_example"))


def test_a_pattern_compiled_with_flags_is_refused() -> None:
    """A flag changes what the pattern matches beyond its text, which the
    overlap comparison reads."""
    contract = ProvisioningRouteContract(
        "GET",
        re.compile(r"/api/v1/JOBS", re.IGNORECASE),
        "provisioning_example",
        roles=("admin",),
    )
    with pytest.raises(ValueError, match="compiled with flags"):
        route_contract_from_declaration(contract)


def test_resolution_names_an_unknown_path() -> None:
    with pytest.raises(ProvisioningRouteNotFound) as refused:
        PROVISIONING_ROUTE_TABLE.resolve("GET", "/api/v1/nowhere")
    assert refused.value.status_code == 404
    assert refused.value.headers == {}


def test_resolution_names_the_methods_a_known_path_serves() -> None:
    with pytest.raises(ProvisioningRouteMethodNotAllowed) as refused:
        PROVISIONING_ROUTE_TABLE.resolve("DELETE", "/api/v1/hosts/")
    assert refused.value.status_code == 405
    assert refused.value.allowed_methods == ("GET", "POST")
    assert refused.value.headers == {"Allow": "GET, POST"}


@pytest.mark.parametrize("body", [{}, {"capacity_reservation_id": 7}, ["r-1"]])
def test_resolution_names_the_body_field_it_cannot_bind(body) -> None:
    with pytest.raises(ProvisioningRouteResourceUnbound) as refused:
        PROVISIONING_ROUTE_TABLE.resolve("POST", "/api/v1/fulfillment/schedule", body)
    assert refused.value.status_code == 400
    assert refused.value.field == "capacity_reservation_id"


@pytest.mark.parametrize(
    "duplicate",
    [
        {**_LEASE_CREATE, "path": r"/api/v1/elsewhere"},
        {**_LEASE_GET, "operation": "provisioning_example_other"},
    ],
    ids=["operation", "route"],
)
def test_assembly_refuses_a_duplicate(duplicate) -> None:
    with pytest.raises(ValueError, match="duplicate route"):
        ProvisioningRouteTable((_LEASE_GET, _LEASE_CREATE), (duplicate,))


@pytest.mark.parametrize(
    "roles",
    [(), ("operator",), ("admin", "admin"), None],
    ids=["empty", "unknown", "repeated", "absent"],
)
def test_a_declaration_must_name_its_roles(roles) -> None:
    declaration = {key: value for key, value in _LEASE_GET.items() if key != "roles"}
    if roles is not None:
        declaration["roles"] = roles

    with pytest.raises(ValueError, match="must name its roles"):
        route_contract_from_declaration(declaration)


def test_a_declaration_that_does_not_admit_the_administrator_is_refused() -> None:
    with pytest.raises(ValueError, match="must admit admin"):
        route_contract_from_declaration({**_LEASE_GET, "roles": ("seller",)})


def test_a_declaration_with_an_unknown_key_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown keys"):
        route_contract_from_declaration({**_LEASE_GET, "resource": "lease_id"})


def test_a_list_of_path_resources_joins_its_groups() -> None:
    contract = route_contract_from_declaration(
        {
            "method": "POST",
            "path": r"/api/v1/example/(?P<host>[^/]+)/units/(?P<unit>[^/]+)/start",
            "operation": "provisioning_example_unit_start",
            "roles": ("admin",),
            "path_resource": ["host", "unit"],
        }
    )

    assert contract.match("POST", "/api/v1/example/h1/units/u1/start", {}) == "h1/u1"


def test_no_route_registers_a_lease() -> None:
    """Commit begins a lease and provisioning records its target when the
    fulfillment becomes active, so the lease collection takes no write."""
    with pytest.raises(ValueError):
        PROVISIONING_ROUTE_TABLE.resolve(
            "POST", "/api/v1/contract/leases", {"capacity_reservation_id": "r-1"}
        )
