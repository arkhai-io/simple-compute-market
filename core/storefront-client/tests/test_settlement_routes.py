"""The settlement route contract binds each request to exactly one route."""

from __future__ import annotations

import pytest

from storefront_client.settlement_routes import (
    REFUND,
    SETTLE,
    SETTLE_STATUS,
    SETTLEMENT_ROUTES,
    SettlementRouteError,
    bind_settlement_route,
    unmounted_settlement_routes,
)


@pytest.mark.parametrize("route", SETTLEMENT_ROUTES, ids=lambda route: route.operation)
def test_a_route_binds_the_identifier_its_path_carries(route):
    binding = bind_settlement_route(route.method, route.path("neg-1"))

    assert binding is not None
    assert binding.route is route
    assert binding.resource == "neg-1"


def test_routes_are_distinguished_by_method_and_path():
    assert SETTLE.path("x") == "/api/v1/settle/x"
    assert SETTLE_STATUS.path("x") == "/api/v1/settle/x/status"
    assert REFUND.path("x") == "/api/v1/settlements/x/refund"
    assert bind_settlement_route("GET", "/api/v1/settle/x") is None
    assert bind_settlement_route("POST", "/api/v1/settle/x/status") is None
    assert bind_settlement_route("GET", "/api/v1/settlements/x/refund") is None


def test_roles_and_operations_are_declared_once():
    assert (SETTLE.operation, SETTLE.role) == ("settle_escrow", "buyer")
    assert (SETTLE_STATUS.operation, SETTLE_STATUS.role) == ("settle_status", "buyer")
    assert (REFUND.operation, REFUND.role) == ("refund_settlement", "seller")


@pytest.mark.parametrize("identifier", ["", "a/b"])
def test_an_identifier_must_be_one_path_segment(identifier):
    with pytest.raises(SettlementRouteError):
        SETTLE.path(identifier)
    assert bind_settlement_route("POST", f"/api/v1/settle/{identifier}") is None


def test_unmounted_routes_are_reported():
    mounted = [
        ("POST", "/api/v1/settle/{escrow_uid}"),
        ("GET", "/api/v1/settle/{escrow_uid}/status"),
        ("GET", "/api/v1/settlements/{negotiation_id}/refund"),
    ]

    assert unmounted_settlement_routes(mounted) == [REFUND]
