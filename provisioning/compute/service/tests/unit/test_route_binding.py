"""Every route the service mounts has one contract, and every contract a route.

A binding repeats its contract's path, so the two can drift apart: a mounted
route with no contract is refused by request authentication, and a contract
with no route is a client method that can never succeed. The app's mounted
routes and the table its authentication reads are compared in both directions.
Unauthenticated routes (liveness and the API documentation) are outside the
table by design.

The mounted routes are read from the app's OpenAPI document, the framework's
public account of every route it serves; no route here is hidden from it.
"""

from __future__ import annotations

import re

import pytest
from compute_provisioning_service.main import app, provisioning_route_table
from compute_provisioning_service.middleware.auth import EXCLUDED_PATHS

# Every name a contract binds its resource from in a body.
_BODY = {
    contract.body_resource: "resource-1"
    for contract in provisioning_route_table.contracts
    if contract.body_resource
}


def _mounted() -> list[tuple[str, str]]:
    routes = []
    for path, operations in app.openapi()["paths"].items():
        if path in EXCLUDED_PATHS:
            continue
        for method in operations:
            if method in {"get", "put", "post", "delete", "patch"}:
                routes.append((method.upper(), path))
    return sorted(routes)


def _concrete(template: str) -> str:
    # The rotation route's role is a closed set its contract names.
    template = template.replace("/identity/rotations/{role}", "/identity/rotations/admin")
    return re.sub(r"\{[^}]+\}", "resource-1", template)


def _contract_path(pattern: str) -> str:
    path = pattern.replace("(?P<trust_role>admin|seller)", "admin")
    path = re.sub(r"\(\?P<[^>]+>\[\^/\]\+\)", "resource-1", path)
    return path.replace("/?", "").removesuffix("$")


@pytest.mark.parametrize(("method", "template"), _mounted(), ids=lambda value: str(value))
def test_every_mounted_route_resolves_to_exactly_one_contract(method, template):
    # Resolution refuses a path two contributions claim, so a single answer is
    # also proof that no other contribution claims it.
    contract, _resource = provisioning_route_table.resolve(method, _concrete(template), dict(_BODY))

    assert contract.method == method


@pytest.mark.parametrize(
    "contract", provisioning_route_table.contracts, ids=lambda contract: contract.operation
)
def test_every_contract_resolves_to_a_mounted_route(contract):
    path = _contract_path(contract.pattern.pattern)
    mounted = [
        (method, template)
        for method, template in _mounted()
        if method == contract.method
        and re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", template.rstrip("/")) + "/?", path)
    ]

    assert mounted, f"{contract.operation}: no mounted {contract.method} route serves {path}"
