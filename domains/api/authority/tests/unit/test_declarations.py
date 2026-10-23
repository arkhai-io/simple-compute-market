"""The adapted contracts are the declarations, field for field, and the service's recorded table."""

import json
import re
from pathlib import Path

from arkhai_api_authority import site_route_contracts
from arkhai_api_contracts.routes import AUTHORITY_ROUTES
from market_site.auth import SiteRouteContract

RECORDED = json.loads(
    (
        Path(__file__).resolve().parents[5]
        / "domains" / "apicredits" / "service" / "tests" / "fixtures" / "baseline" / "route_contracts.json"
    ).read_text(encoding="utf-8")
)["credits"]


def _as_recorded(contract: SiteRouteContract) -> dict:
    return {
        "allowed_roles": sorted(contract.allowed_roles),
        "body_resource": contract.body_resource,
        "exact_retry_safe": contract.exact_retry_safe,
        "method": contract.method,
        "operation": contract.operation,
        "optional_body_resource": contract.optional_body_resource,
        "path_resource": contract.path_resource,
        "pattern": contract.pattern.pattern,
    }


def test_the_adapted_contracts_are_the_declarations_field_for_field_in_order():
    adapted = site_route_contracts()
    assert [c.operation for c in adapted] == [d["operation"] for d in AUTHORITY_ROUTES]
    for contract, declaration in zip(adapted, AUTHORITY_ROUTES):
        assert contract.method == declaration["method"]
        assert contract.pattern == re.compile(declaration["path"])
        assert contract.allowed_roles == frozenset(declaration["roles"])
        assert contract.path_resource == declaration.get("path_resource")
        assert contract.body_resource == declaration.get("body_resource")
        assert contract.optional_body_resource == declaration.get("optional_body_resource", False)
        assert contract.exact_retry_safe == declaration.get("exact_retry_safe", True)
        assert contract.permits("admin")


def test_the_adapted_contracts_equal_the_services_recorded_table():
    assert [_as_recorded(c) for c in site_route_contracts()] == RECORDED
