"""Every route FastAPI actually registered is either excluded or has a signed contract."""

from __future__ import annotations

import pytest
from market_site.auth import (
    CAPACITY_ROUTE_CONTRACTS,
    EXCLUDED_PATHS,
    resolve_site_route,
)
from arkhai_api_contracts.operations import SYSTEM_TIME
from starlette.routing import Route

from inference_service import main
from inference_service.main import INFERENCE_ROUTE_CONTRACTS

ALL_CONTRACTS = INFERENCE_ROUTE_CONTRACTS + CAPACITY_ROUTE_CONTRACTS

#: Substituted for each templated path segment.
_SAMPLE_SEGMENT = "sample-id"

#: `kit/site`'s defaults plus the docs' OAuth2 redirect and the health/version
#: pair an orchestrator probes without a credential.
_UNSIGNED_PATHS = EXCLUDED_PATHS | {
    "/docs/oauth2-redirect",
    "/api/v1/system/health",
    "/api/v1/system/version",
}


def _iter_api_routes(routes, prefix: str = "") -> "list[tuple[str, object]]":
    """Flatten included routers, whether spliced into `app.routes` or kept in a wrapper.

    Both shapes are walked so the test cannot pass enumerating only the docs routes.
    """
    flattened: list[tuple[str, object]] = []
    for route in routes:
        if isinstance(route, Route):
            flattened.append((prefix, route))
            continue
        original = getattr(route, "original_router", None)
        if original is None or not getattr(original, "routes", None):
            continue
        # In this shape the wrapper, not the child route, carries the mount prefix.
        context = getattr(route, "include_context", None)
        child_prefix = prefix + (getattr(context, "prefix", "") or "")
        flattened.extend(_iter_api_routes(original.routes, child_prefix))
    return flattened


def _mounted_routes(app) -> list[tuple[str, str]]:
    mounted: list[tuple[str, str]] = []
    api_routes = _iter_api_routes(app.routes)
    assert api_routes, "no routes enumerated; this test would check nothing"
    for route_prefix, route in api_routes:
        full_path = route_prefix + route.path
        if full_path in _UNSIGNED_PATHS:
            continue
        concrete = full_path
        while "{" in concrete:
            start = concrete.index("{")
            end = concrete.index("}", start)
            concrete = concrete[:start] + _SAMPLE_SEGMENT + concrete[end + 1 :]
        for method in sorted(route.methods or ()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            mounted.append((method, concrete))
    return mounted


@pytest.fixture(scope="module")
def mounted():
    return _mounted_routes(main.app)


def test_every_mounted_route_resolves_to_a_contract(mounted):
    unmatched = []
    for method, path in mounted:
        try:
            resolve_site_route(method, path, {}, contracts=ALL_CONTRACTS)
        except ValueError:
            unmatched.append(f"{method} {path}")
    assert not unmatched, (
        "routes are mounted with no signed contract, so the middleware will "
        f"refuse them as unknown: {unmatched}"
    )


def test_every_authority_contract_matches_a_mounted_route(mounted):
    """An unreachable contract reads as coverage while a real route at another path goes unsigned."""
    reachable = set()
    for method, path in mounted:
        for contract in INFERENCE_ROUTE_CONTRACTS:
            try:
                if contract.match(method, path, {}) is not None:
                    reachable.add(contract.operation)
            except ValueError:
                # A body-resource contract matched, but the probe sent no body.
                reachable.add(contract.operation)
    # The time-setting route is mounted only under injected time, whichever
    # source this process composed the service under.
    conditional = {SYSTEM_TIME}
    declared = {contract.operation for contract in INFERENCE_ROUTE_CONTRACTS}
    assert declared - conditional == reachable - conditional, (
        f"contracts matching no mounted route: {sorted(declared - reachable)}"
    )


def test_operations_are_unique_across_both_tables():
    """A caller signs the operation, so a shared name would let one route's signature verify for another."""
    operations = [contract.operation for contract in ALL_CONTRACTS]
    duplicates = {name for name in operations if operations.count(name) > 1}
    assert not duplicates, f"duplicate signed operation names: {duplicates}"


def test_consume_is_reachable_by_the_gateway_only():
    """The gateway may spend request credits but not mint or revoke them."""
    by_operation = {c.operation: c for c in INFERENCE_ROUTE_CONTRACTS}
    for operation in ("credits_key_consume", "credits_key_consume_batch"):
        contract = by_operation[operation]
        assert contract.permits("service")
        assert not contract.permits("seller")
    for operation in ("credits_issue", "credits_key_revoke", "credits_key_adjust"):
        contract = by_operation[operation]
        assert contract.permits("seller")
        assert not contract.permits("service")
