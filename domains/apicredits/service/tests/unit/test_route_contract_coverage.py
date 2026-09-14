"""Every mounted route is either excluded or has a signed contract.

Checked against the routes FastAPI actually registered, not against a reading
of the controller. Transcribing a route table by hand is exactly the kind of
work that goes wrong quietly: a missed route keeps working while nobody signs
it, and an invented one is dead config that looks like coverage. Asking the app
makes both failures loud.

This is the coverage guard. `kit/site`'s own parity test covers agreement
between the capacity table and the client that signs against it.
"""

from __future__ import annotations

import pytest
from market_site.auth import (
    CAPACITY_ROUTE_CONTRACTS,
    EXCLUDED_PATHS,
    resolve_site_route,
)
from middleware.route_contracts import CREDITS_ROUTE_CONTRACTS
from starlette.routing import Route

ALL_CONTRACTS = CREDITS_ROUTE_CONTRACTS + CAPACITY_ROUTE_CONTRACTS

#: A concrete stand-in for each templated path segment, so a registered path
#: can be resolved against the patterns the middleware will actually match.
_SAMPLE_SEGMENT = "sample-id"

#: Paths this service serves without a signature. `kit/site`'s defaults plus
#: the two the credits service adds: FastAPI's OAuth2 redirect helper, which
#: the docs page loads, and the versioned health/version pair, which exists so
#: an orchestrator can probe liveness without holding a credential.
_UNSIGNED_PATHS = EXCLUDED_PATHS | {
    "/docs/oauth2-redirect",
    "/api/v1/system/health",
    "/api/v1/system/version",
}


def _iter_api_routes(routes, prefix: str = "") -> "list[tuple[str, object]]":
    """Flatten however this FastAPI version represents included routers.

    Older versions splice each included router's `APIRoute`s directly into
    `app.routes`; newer ones keep a wrapper holding the original router. Both
    shapes are walked, because a test that silently enumerates only the four
    auto-generated docs routes would pass while checking nothing -- which is
    what the first version of this did.
    """
    flattened: list[tuple[str, object]] = []
    for route in routes:
        if isinstance(route, Route):
            flattened.append((prefix, route))
            continue
        original = getattr(route, "original_router", None)
        if original is None or not getattr(original, "routes", None):
            continue
        # The wrapper, not the child route, carries the mount prefix in this
        # shape. Missing it yields paths like `/keys/{id}` for routes actually
        # served at `/api/v1/keys/{id}`, which no contract matches -- so the
        # test fails loudly rather than checking the wrong paths.
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
    import main

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


def test_every_credits_contract_matches_a_mounted_route(mounted):
    """The other direction: no contract for a route that does not exist.

    A contract nobody can reach is not harmless -- it reads as coverage of a
    route while the real one, if it is ever added under a slightly different
    path, goes unsigned.
    """
    reachable = set()
    for method, path in mounted:
        for contract in CREDITS_ROUTE_CONTRACTS:
            try:
                if contract.match(method, path, {}) is not None:
                    reachable.add(contract.operation)
            except ValueError:
                # A body-resource contract matched the route but this probe
                # sent no body. The route exists, which is what is asserted.
                reachable.add(contract.operation)
    declared = {contract.operation for contract in CREDITS_ROUTE_CONTRACTS}
    assert declared == reachable, (
        f"contracts matching no mounted route: {sorted(declared - reachable)}"
    )


def test_operations_are_unique_across_both_tables():
    """One operation name per route, across the tables composed together.

    The operation is what a caller signs, so two routes sharing a name would
    let a signature for one verify against the other.
    """
    operations = [contract.operation for contract in ALL_CONTRACTS]
    duplicates = {name for name in operations if operations.count(name) > 1}
    assert not duplicates, f"duplicate signed operation names: {duplicates}"


def test_consume_and_verify_are_reachable_by_the_gated_service_only():
    """The narrow role the widening was for.

    A single shared admin secret could not express that the gated application
    may spend credits but not mint or revoke them. These assertions are the
    reason the storefront and the sample app now hold different roles.
    """
    by_operation = {c.operation: c for c in CREDITS_ROUTE_CONTRACTS}
    for operation in ("credits_key_consume", "credits_key_consume_batch"):
        contract = by_operation[operation]
        assert contract.permits("service")
        assert not contract.permits("seller")
    for operation in ("credits_issue", "credits_key_revoke", "credits_key_adjust"):
        contract = by_operation[operation]
        assert contract.permits("seller")
        assert not contract.permits("service")
