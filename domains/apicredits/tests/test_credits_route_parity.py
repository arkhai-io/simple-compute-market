"""Both credits clients' signed operations agree with the service's table.

The credits service recomputes the operation and the signed resource from
the route it matched, then verifies the caller's signature over *its* own
values. A client that names an operation the service spells differently, or
signs a resource the service derives from somewhere else, does not produce
a slightly wrong request -- it produces a signature that cannot verify, on
every call to that route. Three tables therefore have to stay identical:

- `CREDITS_ROUTE_CONTRACTS` (the service, authoritative),
- `apicredits_middleware.client` (the gated app, `service` role),
- `domains.apicredits.settlement.credits_client` (the storefront, `seller`).

`route_contracts.py` is loaded from its path rather than imported: it lives
in the service distribution under the package name `middleware`, which
collides with the published `apicredits_middleware` this test also needs.
It is a leaf module over `market_site.auth`, so loading it directly costs
nothing and avoids installing the service to check a table.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
_CONTRACTS = (
    _REPO
    / "domains/apicredits/service/src/middleware/route_contracts.py"
)
_MIDDLEWARE_SRC = _REPO / "domains/apicredits/middleware/python/src"


def _load_contracts():
    spec = importlib.util.spec_from_file_location(
        "_credits_route_contracts", _CONTRACTS
    )
    assert spec and spec.loader, _CONTRACTS
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CREDITS_ROUTE_CONTRACTS


@pytest.fixture(scope="module")
def contracts():
    return {c.operation: c for c in _load_contracts()}


@pytest.fixture(scope="module")
def middleware_client():
    if str(_MIDDLEWARE_SRC) not in sys.path:
        sys.path.insert(0, str(_MIDDLEWARE_SRC))
    from apicredits_middleware import client

    return client


def test_middleware_operations_exist_in_the_service_table(
    contracts, middleware_client
):
    """The gated app's three operations are spelled the service's way."""
    for operation in (
        middleware_client.VERIFY_OPERATION,
        middleware_client.CONSUME_OPERATION,
        middleware_client.CONSUME_BATCH_OPERATION,
    ):
        assert operation in contracts, (
            f"{operation!r} is not a declared credits route operation; "
            f"declared: {sorted(contracts)}"
        )


def test_middleware_operations_are_admitted_for_the_service_role(
    contracts, middleware_client
):
    """The gated app signs as `service`, so each route must admit it.

    A role the contract does not admit is refused after the signature
    verifies, which is a different and more confusing failure than a bad
    signature.
    """
    for operation in (
        middleware_client.VERIFY_OPERATION,
        middleware_client.CONSUME_OPERATION,
        middleware_client.CONSUME_BATCH_OPERATION,
    ):
        contract = contracts[operation]
        assert middleware_client.GATED_APP_ROLE in contract.allowed_roles, (
            f"{operation!r} does not admit "
            f"{middleware_client.GATED_APP_ROLE!r}: "
            f"{sorted(contract.allowed_roles)}"
        )


def test_keyed_middleware_routes_sign_the_path_key(contracts, middleware_client):
    """`consume` and `verify` sign `key_id`, taken from the path."""
    for operation in (
        middleware_client.VERIFY_OPERATION,
        middleware_client.CONSUME_OPERATION,
    ):
        assert contracts[operation].path_resource == "key_id", (
            f"{operation!r} no longer derives its resource from the "
            "`key_id` path segment; the client signs that value"
        )


def test_batch_route_signs_the_empty_resource(contracts, middleware_client):
    """The batch route names no single key, so the client signs "".

    Asserted against the contract declaring no resource of its own: if the
    service ever gave this route a resource, the client's empty string
    would stop verifying.
    """
    contract = contracts[middleware_client.CONSUME_BATCH_OPERATION]
    assert getattr(contract, "path_resource", None) is None
    assert getattr(contract, "body_resource", None) is None
    assert middleware_client.BATCH_RESOURCE == ""


def test_storefront_operations_exist_and_admit_the_seller_role(contracts):
    """The storefront's five operations, signed as `seller`."""
    from domains.apicredits.settlement import credits_client as sf

    keyed = {
        sf.ISSUANCE_GET_OPERATION: "fulfillment_id",
        sf.KEY_GET_OPERATION: "key_id",
        sf.KEY_REVOKE_OPERATION: "key_id",
        sf.KEY_ADJUST_OPERATION: "key_id",
    }
    for operation, path_resource in keyed.items():
        assert operation in contracts, sorted(contracts)
        contract = contracts[operation]
        assert sf.STOREFRONT_ROLE in contract.allowed_roles, operation
        assert contract.path_resource == path_resource, operation


def test_issuance_signs_the_optional_body_resource(contracts):
    """`credits_issue` takes its resource from the body, optionally.

    The client mirrors that by signing the body's `fulfillment_id` or the
    empty string. Pinned because it is the one operation whose resource is
    not a path segment, so it is the one most likely to be "fixed" into
    signing something else.
    """
    from domains.apicredits.settlement import credits_client as sf

    contract = contracts[sf.ISSUE_OPERATION]
    assert sf.STOREFRONT_ROLE in contract.allowed_roles
    assert contract.body_resource == "fulfillment_id"
    assert contract.optional_body_resource is True
    assert getattr(contract, "path_resource", None) is None


def test_the_two_clients_do_not_claim_each_others_roles(middleware_client):
    """The role split is the point of having two identities.

    A compromised gated app must not be able to mint grants or revoke
    keys. That is expressed by the roles the two clients sign as, so the
    two constants must stay different.
    """
    from domains.apicredits.settlement import credits_client as sf

    assert middleware_client.GATED_APP_ROLE != sf.STOREFRONT_ROLE
