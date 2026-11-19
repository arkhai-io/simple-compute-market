"""The control routes' paths, the faultless prefix, and control-token admission."""

from __future__ import annotations

import pytest

from lane_double_controls import routes
from lane_double_controls.models import ControlError


@pytest.mark.parametrize(("path", "control"), [
    ("/test", True), ("/test/rules", True), ("/test/cases/x/close", True),
    ("/testing", False), ("/transactions", False), ("/cases", False), ("/", False),
])
def test_only_the_test_prefix_is_a_control_path(path: str, control: bool) -> None:
    assert routes.is_control_path(path) is control


@pytest.mark.parametrize(("path", "contract"), [
    ("/transactions", True), ("/cases", True), ("/record", True), ("/healthz", True),
    ("/health", False), ("/test/status", False), ("/test", False),
])
def test_neither_a_control_nor_the_health_route_is_a_contract_path(
        path: str, contract: bool) -> None:
    assert routes.is_contract_path(path) is contract


def test_every_route_is_a_control_path() -> None:
    assert all(routes.is_control_path(route.path) for route in routes.ROUTES)


def test_a_path_parameter_is_escaped() -> None:
    assert routes.RULE_DELETE.url(rule_id="a/b c") == "/test/rules/a%2Fb%20c"


def test_the_reservation_route_is_the_payments_partys_alone_and_names_its_transaction() -> None:
    assert routes.RESERVE.parties == frozenset({"payments"})
    assert (routes.RESERVE.method, routes.RESERVE.url(transaction="ab" * 32)) == (
        "POST", f"/test/transactions/{'ab' * 32}/reserve")


def test_a_route_refuses_parameters_it_does_not_take() -> None:
    with pytest.raises(ValueError):
        routes.RULE_DELETE.url()
    with pytest.raises(ValueError):
        routes.STATUS.url(rule_id="r1")


def test_each_party_serves_its_own_controls() -> None:
    payments = set(routes.routes_for("payments", time_settable=True))
    mediation = set(routes.routes_for("mediation", time_settable=True))
    sample_app = set(routes.routes_for("sample-app", time_settable=True))

    assert {routes.FUNDING, routes.SIGNER_ROTATE, routes.RESERVE} <= payments - mediation
    assert {routes.CASE_LIST, routes.CASE_DECIDE, routes.CASE_CLOSE,
            routes.RULE_RESUME} <= mediation - payments
    assert {routes.RULES, routes.RULE_LIST, routes.RULE_DELETE, routes.TIME,
            routes.STATUS} <= payments & mediation
    assert sample_app == {routes.TIME, routes.STATUS}


@pytest.mark.parametrize("party", ["payments", "mediation", "sample-app"])
def test_a_party_on_wall_time_serves_no_time_route(party: str) -> None:
    settable = set(routes.routes_for(party, time_settable=True))  # type: ignore[arg-type]
    wall = set(routes.routes_for(party, time_settable=False))  # type: ignore[arg-type]

    assert settable - wall == {routes.TIME}
    assert routes.STATUS in wall


@pytest.mark.parametrize("header", ["Bearer control-token", "bearer control-token"])
def test_the_control_token_is_admitted(header: str) -> None:
    routes.authorize(header, "control-token")


@pytest.mark.parametrize("header", [None, "", "Bearer wrong", "Basic control-token",
                                    "Bearer control-token extra"])
def test_a_missing_or_wrong_token_is_refused(header: str | None) -> None:
    with pytest.raises(ControlError) as refused:
        routes.authorize(header, "control-token")
    assert (refused.value.status, refused.value.code) == (401, "authentication_required")
