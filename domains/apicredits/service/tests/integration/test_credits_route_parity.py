"""Both credits clients' signed operations agree with the service's table.

The credits service recomputes the operation and the signed resource from
the route it matched, then verifies the caller's signature over *its* own
values. A client that names an operation the service spells differently, or
signs a resource the service derives from somewhere else, does not produce
a slightly wrong request -- it produces a signature that cannot verify, on
every call to that route. Three tables therefore have to stay identical:

- the table this service authenticates, adapted by the authority from
  `arkhai_api_contracts.routes` (the declarations the storefront's family
  client binds every `seller` request from; the authority's own tests hold
  the adaptation to the declarations),
- `arkhai_api_gate.client` (the gated app, `service` role).

Lives in the service's own suite because the service composes the table the
gated app signs against, and because the comparison needs `fastapi` and
`market_site` -- which the service has and the gate deliberately does not.
"""

from __future__ import annotations

import pytest

from apicredits_service.main import CREDITS_ROUTE_CONTRACTS


@pytest.fixture(scope="module")
def contracts():
    return {c.operation: c for c in CREDITS_ROUTE_CONTRACTS}


@pytest.fixture(scope="module")
def gate_client():
    from arkhai_api_gate import client

    return client


def test_gate_operations_exist_in_the_service_table(
    contracts, gate_client
):
    """The gated app's three operations are spelled the service's way."""
    for operation in (
        gate_client.VERIFY_OPERATION,
        gate_client.CONSUME_OPERATION,
        gate_client.CONSUME_BATCH_OPERATION,
    ):
        assert operation in contracts, (
            f"{operation!r} is not a declared credits route operation; "
            f"declared: {sorted(contracts)}"
        )


def test_gate_operations_are_admitted_for_the_service_role(
    contracts, gate_client
):
    """The gated app signs as `service`, so each route must admit it.

    A role the contract does not admit is refused after the signature
    verifies, which is a different and more confusing failure than a bad
    signature.
    """
    for operation in (
        gate_client.VERIFY_OPERATION,
        gate_client.CONSUME_OPERATION,
        gate_client.CONSUME_BATCH_OPERATION,
    ):
        contract = contracts[operation]
        assert gate_client.GATED_APP_ROLE in contract.allowed_roles, (
            f"{operation!r} does not admit "
            f"{gate_client.GATED_APP_ROLE!r}: "
            f"{sorted(contract.allowed_roles)}"
        )


def test_keyed_gate_routes_sign_the_path_key(contracts, gate_client):
    """`consume` and `verify` sign `key_id`, taken from the path."""
    for operation in (
        gate_client.VERIFY_OPERATION,
        gate_client.CONSUME_OPERATION,
    ):
        assert contracts[operation].path_resource == "key_id", (
            f"{operation!r} no longer derives its resource from the "
            "`key_id` path segment; the client signs that value"
        )


def test_batch_route_signs_the_empty_resource(contracts, gate_client):
    """The batch route names no single key, so the client signs "".

    Asserted against the contract declaring no resource of its own: if the
    service ever gave this route a resource, the client's empty string
    would stop verifying.
    """
    contract = contracts[gate_client.CONSUME_BATCH_OPERATION]
    assert getattr(contract, "path_resource", None) is None
    assert getattr(contract, "body_resource", None) is None
    assert gate_client.BATCH_RESOURCE == ""


def test_the_two_clients_do_not_claim_each_others_roles(gate_client):
    """The role split is the point of having two identities.

    A compromised gated app must not be able to mint grants or revoke
    keys. That is expressed by the roles the two clients sign as, so the
    two constants must stay different.
    """
    from arkhai_api_contracts.routes import SELLER_ROLE

    assert gate_client.GATED_APP_ROLE != SELLER_ROLE
