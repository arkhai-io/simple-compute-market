"""The declarations are the API-credits service's signed route table, field for field."""

import json
import re
from pathlib import Path

import pytest

from arkhai_api_contracts import operations
from arkhai_api_contracts.routes import AUTHORITY_ROUTES, route

BASELINE = Path(__file__).resolve().parents[4] / "domains" / "apicredits" / "service" / "tests" / "fixtures" / "baseline"
ROUTE_CONTRACTS = json.loads((BASELINE / "route_contracts.json").read_text(encoding="utf-8"))
MOUNTED = json.loads((BASELINE / "routes.json").read_text(encoding="utf-8"))
AUTHORITY_PATHS = ("/api/v1/issuance", "/api/v1/keys")


def _as_recorded(declaration: dict) -> dict:
    return {
        "allowed_roles": sorted(declaration["roles"]),
        "body_resource": declaration.get("body_resource"),
        "exact_retry_safe": declaration.get("exact_retry_safe", True),
        "method": declaration["method"],
        "operation": declaration["operation"],
        "optional_body_resource": declaration.get("optional_body_resource", False),
        "path_resource": declaration.get("path_resource"),
        "pattern": declaration["path"],
    }


def _matching(method: str, path: str) -> list[dict]:
    sample = re.sub(r"\{[^}]+\}", "x", path)
    return [d for d in AUTHORITY_ROUTES if d["method"] == method and re.fullmatch(d["path"], sample)]


def test_the_declarations_match_the_services_table_field_for_field():
    assert [_as_recorded(d) for d in AUTHORITY_ROUTES] == ROUTE_CONTRACTS["credits"]


def test_every_mounted_authority_route_resolves_to_exactly_one_declaration():
    mounted = [r for r in MOUNTED if r["path"].startswith(AUTHORITY_PATHS)]
    assert len(mounted) == len(AUTHORITY_ROUTES)
    for mounted_route in mounted:
        assert len(_matching(mounted_route["method"], mounted_route["path"])) == 1, mounted_route
    for path in ROUTE_CONTRACTS["unsigned_paths"]:
        assert not any(_matching(method, path) for method in ("GET", "POST", "PUT", "DELETE")), path


def test_each_operation_is_declared_once_and_looked_up_by_name():
    declared = [d["operation"] for d in AUTHORITY_ROUTES]
    assert len(declared) == len(set(declared))
    assert sorted(declared) == sorted(
        value for name, value in vars(operations).items() if name.isupper()
    )
    assert route(operations.KEY_ADJUST)["exact_retry_safe"] is False
    assert route(operations.ISSUE)["body_resource"] == "fulfillment_id"
    with pytest.raises(KeyError):
        route("credits_unknown")
