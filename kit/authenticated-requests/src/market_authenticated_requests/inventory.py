"""The route inventory: every route of an authority is declared or marked.

An authority that authenticates inside its routes cannot see a route that forgot
to, so the core reads the application's own route table when it is installed and
refuses to start, naming each route that admits through the core with neither a
declaration nor a public operation's mark, and is not marked unauthenticated.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from starlette.routing import BaseRoute

from market_authenticated_requests.application import AuthenticatedApplication
from market_authenticated_requests.core import AdmissionCore
from market_authenticated_requests.dependency import PublicAdmission, RouteAdmission
from market_authenticated_requests.routes import RouteTable, Unauthenticated

class RouteInventoryError(RuntimeError):
    """Routes with no exact-retry declaration, public mark, or unauthenticated mark."""

    def __init__(self, routes: list[str]) -> None:
        super().__init__(
            "routes with no exact-retry declaration, public mark, or unauthenticated mark: "
            + ", ".join(routes)
        )
        self.routes = routes


def undeclared_routes(app: Any, *, routes: RouteTable | None, unauthenticated: Unauthenticated) -> list[str]:
    """Each route of ``app``, as ``<METHOD> <path>``, that nothing declares or marks."""

    missing = []
    for path, route in _routes(list(getattr(app, "routes", ()))):
        if unauthenticated.marks(path):
            continue
        admits = isinstance(route, APIRoute) and _admits(route.dependant)
        methods = sorted(set(getattr(route, "methods", None) or {"*"}))
        if routes is None:
            missing.extend([] if admits else [f"{method} {path}" for method in methods])
            continue
        # The middleware form admits every unmarked request through its table, so a
        # route admitting again through a dependency would be admitted twice.
        for method in methods:
            if admits:
                missing.append(f"{method} {path} (admits through a dependency in the middleware form)")
            elif not routes.declares(method, path):
                missing.append(f"{method} {path}")
    return missing


def install(
    app: Any,
    core: AdmissionCore,
    *,
    routes: RouteTable | None = None,
    unauthenticated: Unauthenticated | None = None,
) -> AuthenticatedApplication:
    """Wrap ``app`` in the core, refusing an application whose inventory is incomplete.

    ``routes`` is the middleware form's route table; an application in the
    dependency form passes none. ``unauthenticated`` marks the routes served
    without authentication, the OpenAPI document's by default.
    """

    marks = unauthenticated if unauthenticated is not None else Unauthenticated.of()
    missing = undeclared_routes(app, routes=routes, unauthenticated=marks)
    if missing:
        raise RouteInventoryError(missing)
    return AuthenticatedApplication(app, core, routes=routes, unauthenticated=marks)


def _routes(routes: list[BaseRoute]) -> Iterator[tuple[str, BaseRoute]]:
    # A mounted application is one route, by its mount's path, as the wrapper
    # judges a request reaching it: it is declared by the middleware form's table
    # or marked, never admitted route by route.
    for route in routes:
        yield str(getattr(route, "path", "")), route


def _admits(dependant: Dependant) -> bool:
    if isinstance(dependant.call, (RouteAdmission, PublicAdmission)):
        return True
    return any(_admits(child) for child in dependant.dependencies)
