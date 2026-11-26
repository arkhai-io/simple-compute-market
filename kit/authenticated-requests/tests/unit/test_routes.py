from __future__ import annotations

import pytest
from market_identity import ExactRetry

from market_authenticated_requests import DOCUMENTATION_PATHS, RouteBinding, RouteNotServed, Unauthenticated


def test_a_binding_without_a_resolution_is_refused_naming_its_operation() -> None:
    with pytest.raises(TypeError, match="item_set declares no exact-retry resolution"):
        RouteBinding("item_set", "a", frozenset({"seller"}), None)  # type: ignore[arg-type]


def test_a_binding_admitting_no_role_is_refused() -> None:
    with pytest.raises(ValueError, match="admits no role"):
        RouteBinding("item_set", "a", frozenset(), ExactRetry.RECORDED)


def test_a_path_served_under_other_methods_is_a_405_naming_them() -> None:
    assert RouteNotServed().status_code == 404
    assert RouteNotServed(allowed_methods=["POST", "GET"]).status_code == 405
    assert RouteNotServed(allowed_methods=["POST", "GET"]).allowed_methods == ("GET", "POST")


def test_the_unauthenticated_marks_carry_the_openapi_document_by_default() -> None:
    marks = Unauthenticated.of("/health")

    assert marks.marks("/health") and all(marks.marks(path) for path in DOCUMENTATION_PATHS)
    assert not Unauthenticated.of("/health", documentation=False).marks("/openapi.json")
