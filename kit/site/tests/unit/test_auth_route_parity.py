"""The server and client halves of the capacity wire contract must agree.

`kit/site` defines the capacity paths and now the roles that may call them;
`kit/site-client` signs requests against its own table of the same paths. They
cannot share one table without the router depending on its own caller, so this
asserts the duplication stays honest instead.

A test rather than an import is a deliberate trade: the alternative is a
package inversion that outlives this change. What it buys is that a route added
to one table and not the other fails here, at the cheapest point, rather than
as a 403 from a live authority against a client that signed a different
operation name.
"""

from __future__ import annotations

import pytest
from market_site import auth as server_auth
from market_site_client import client as client_contracts


def _server_index() -> dict[tuple[str, str], server_auth.SiteRouteContract]:
    return {
        (contract.method, contract.pattern.pattern): contract
        for contract in server_auth.CAPACITY_ROUTE_CONTRACTS
    }


def _client_index() -> dict[tuple[str, str], object]:
    return {
        (contract.method, contract.pattern.pattern): contract
        for contract in client_contracts.CAPACITY_ROUTE_CONTRACTS
    }


def test_both_tables_cover_the_same_method_and_path_pairs():
    server, client = _server_index(), _client_index()
    assert server.keys() == client.keys(), (
        "capacity route tables disagree on which routes exist: "
        f"server-only={sorted(server.keys() - client.keys())} "
        f"client-only={sorted(client.keys() - server.keys())}"
    )


@pytest.mark.parametrize(
    "method,pattern",
    sorted(_client_index().keys()),
)
def test_operation_and_resource_extraction_match(method: str, pattern: str):
    """The signed fields, not just the route set.

    `operation` and the resource are both signed, so a disagreement here does
    not fail as a missing route: the client signs one operation, the server
    verifies another, and the refusal names a signature problem rather than the
    mapping that caused it.
    """
    server = _server_index()[(method, pattern)]
    client = _client_index()[(method, pattern)]
    assert server.operation == client.operation
    assert server.path_resource == client.path_resource
    assert server.body_resource == client.body_resource
    assert server.optional_body_resource == client.optional_body_resource


def test_every_capacity_route_names_at_least_one_caller_role():
    """An empty role set is a route only `admin` could ever reach.

    Cheap to write and easy to reach by omission, since `permits()` admits
    `admin` unconditionally -- so a contract with no roles would look
    functional to an operator and refuse the storefront that needs it.
    """
    for contract in server_auth.CAPACITY_ROUTE_CONTRACTS:
        assert contract.allowed_roles, (
            f"{contract.operation} names no caller role"
        )


def test_headers_agree_between_the_two_halves():
    """Third copy of the same seven header names in this repository.

    `kit/site-client` and the provisioning client each declare them too. Until
    one owner exists, a rename in one place has to fail somewhere.
    """
    for name in (
        "SIGNATURE_VERSION_HEADER",
        "IDENTITY_SCHEME_HEADER",
        "IDENTITY_IDENTIFIER_HEADER",
        "ROLE_HEADER",
        "REQUEST_ID_HEADER",
        "TIMESTAMP_HEADER",
        "SIGNATURE_HEADER",
    ):
        assert getattr(server_auth, name) == getattr(client_contracts, name), name


def test_admin_is_accepted_on_every_route_without_being_enumerated():
    """`admin` is the operator's role, for manual operation and intervention.

    Asserted because the alternative was route-by-route enumeration, which is
    what made `admin` unable to reach some routes and inhibited testing. A
    future contract that omits `admin` from `allowed_roles` -- as they all do
    -- must still admit it.
    """
    for contract in server_auth.CAPACITY_ROUTE_CONTRACTS:
        assert contract.permits(server_auth.ADMIN_ROLE)
        assert server_auth.ADMIN_ROLE not in contract.allowed_roles


def test_an_unknown_route_is_refused_rather_than_defaulted():
    with pytest.raises(ValueError, match="no authenticated site contract"):
        server_auth.resolve_site_route("GET", "/api/v1/capacity/not-a-route")
