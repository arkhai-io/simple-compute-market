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


def test_a_route_refuses_parameters_it_does_not_take() -> None:
    with pytest.raises(ValueError):
        routes.RULE_DELETE.url()
    with pytest.raises(ValueError):
        routes.STATUS.url(rule_id="r1")


def test_each_double_serves_its_own_controls() -> None:
    payments = set(routes.routes_for("payments"))
    mediation = set(routes.routes_for("mediation"))

    assert {routes.FUNDING, routes.SIGNER_ROTATE} <= payments - mediation
    assert {routes.CASE_LIST, routes.CASE_DECIDE, routes.CASE_CLOSE,
            routes.RULE_RESUME} <= mediation - payments
    assert {routes.RULES, routes.RULE_LIST, routes.RULE_DELETE, routes.CLOCK_ADVANCE,
            routes.CLOCK_RESET, routes.STATUS} <= payments & mediation


@pytest.mark.parametrize("header", ["Bearer control-token", "bearer control-token"])
def test_the_control_token_is_admitted(header: str) -> None:
    routes.authorize(header, "control-token")


@pytest.mark.parametrize("header", [None, "", "Bearer wrong", "Basic control-token",
                                    "Bearer control-token extra"])
def test_a_missing_or_wrong_token_is_refused(header: str | None) -> None:
    with pytest.raises(ControlError) as refused:
        routes.authorize(header, "control-token")
    assert (refused.value.status, refused.value.code) == (401, "authentication_required")
