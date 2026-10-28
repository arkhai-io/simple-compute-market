"""Resolving a request against the site's route table, and why it fails.

The middleware answers a request that resolves to no contract by the case the
resolution names; these tests hold each case's status, headers, and field.
The middleware's answers themselves are asserted in
``tests/integration/test_site_auth_middleware.py``.
"""

from __future__ import annotations

import re

import pytest
from market_site import auth as server_auth


def test_a_path_no_contract_names_is_not_found():
    with pytest.raises(server_auth.SiteRouteNotFound) as excinfo:
        server_auth.resolve_site_route("GET", "/api/v1/capacity/not-a-route")
    assert excinfo.value.status_code == 404
    assert excinfo.value.headers == {}


def test_a_known_path_under_another_method_names_the_methods_served_there():
    with pytest.raises(server_auth.SiteRouteMethodNotAllowed) as excinfo:
        server_auth.resolve_site_route("DELETE", "/api/v1/capacity/reservations")
    assert excinfo.value.allowed_methods == ("GET", "POST")
    assert excinfo.value.status_code == 405
    assert excinfo.value.headers == {"Allow": "GET, POST"}


@pytest.mark.parametrize(
    "body", ({"capacity_reservation_id": ""}, {"capacity_reservation_id": 7}, [])
)
def test_a_body_resource_that_cannot_be_bound_names_its_field(body):
    with pytest.raises(server_auth.SiteRouteResourceUnbound) as excinfo:
        server_auth.resolve_site_route("POST", "/api/v1/capacity/releases", body)
    assert excinfo.value.field == "capacity_reservation_id"
    assert excinfo.value.status_code == 400
    assert "capacity_reservation_id" in excinfo.value.detail


def test_the_first_contract_matching_method_and_path_decides():
    """A later contract never claims what an earlier one matched."""
    first = server_auth.SiteRouteContract(
        method="GET",
        pattern=re.compile(r"/things/latest"),
        operation="things_latest",
        allowed_roles=frozenset({"seller"}),
    )
    second = server_auth.SiteRouteContract(
        method="GET",
        pattern=re.compile(r"/things/(?P<thing_id>[^/]+)"),
        operation="thing_get",
        allowed_roles=frozenset({"seller"}),
        path_resource="thing_id",
    )
    contract, resource = server_auth.resolve_site_route(
        "GET", "/things/latest", contracts=(first, second)
    )
    assert (contract.operation, resource) == ("things_latest", "")
