"""What a route declares to the admission core, in either form.

Every authenticated route binds an operation and, where the operation acts on one
object, that object's identifier as its resource; the route, not the request, says
whether its operation has a target. It admits a set of caller roles, and declares
how an exact retry is resolved, with no default (:class:`market_identity.ExactRetry`).
A route that admits through a contract table the core consults before the
application runs is in the middleware form; one that admits inside the application,
through its :class:`~market_authenticated_requests.dependency.RouteAdmission`, is in
the dependency form.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol

from market_identity import ExactRetry

#: The routes FastAPI adds to serve its OpenAPI document.
DOCUMENTATION_PATHS = ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc")


@dataclass(frozen=True)
class RouteBinding:
    """What one admitted route binds and declares.

    ``resource`` is ``None`` for an operation with no target object, such as a
    publication or a collection read: a request to it states no resource.
    """

    operation: str
    resource: str | None
    roles: frozenset[str]
    exact_retry: ExactRetry

    def __post_init__(self) -> None:
        if self.resource == "":
            raise ValueError(
                f"route {self.operation} binds an empty resource; an operation with no target binds None"
            )
        if not isinstance(self.exact_retry, ExactRetry):
            raise TypeError(
                f"route {self.operation} declares no exact-retry resolution: "
                f"exact_retry must be an ExactRetry, not {self.exact_retry!r}"
            )
        if not self.roles:
            raise ValueError(f"route {self.operation} admits no role")


class RouteNotServed(Exception):
    """No route serves the request's path, or none its method there."""

    def __init__(self, *, allowed_methods: Iterable[str] = ()) -> None:
        super().__init__("no route serves the request")
        self.allowed_methods = tuple(sorted(allowed_methods))

    @property
    def status_code(self) -> int:
        return 405 if self.allowed_methods else 404


class ResourceUnbound(Exception):
    """The route the request reached derives its resource from a body that holds none."""

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class RouteTable(Protocol):
    """The middleware form's routes: how a request is bound, and what is declared."""

    def resolve(self, method: str, path: str, body: bytes) -> RouteBinding:
        """The binding of the route serving the request.

        Raises :class:`RouteNotServed` or :class:`ResourceUnbound`.
        """
        ...

    def declares(self, method: str, path_template: str) -> bool:
        """Whether a route of the application, by its method and path template,
        is one this table binds."""
        ...


@dataclass(frozen=True)
class Unauthenticated:
    """The routes an authority serves without authentication, by path.

    Health and the OpenAPI document everywhere, and an injected time route only
    where its authority does not sign it. A time-setting route the authority
    signs carries a declaration instead.
    """

    paths: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def of(cls, *paths: str, documentation: bool = True) -> Unauthenticated:
        return cls(frozenset(paths) | (frozenset(DOCUMENTATION_PATHS) if documentation else frozenset()))

    def marks(self, path_template: str) -> bool:
        return path_template in self.paths


ResourceOf = Callable[[dict[str, str], bytes], str]
"""How a dependency-form route whose operation has a target derives that target's
identifier: from its path parameters and the request body."""


def path_resource(name: str) -> ResourceOf:
    """A resource that is the path parameter ``name``."""

    def resource(path_params: dict[str, str], body: bytes) -> str:
        return str(path_params[name])

    return resource


def fixed_resource(value: str) -> ResourceOf:
    """A resource that is the same for every request to the route."""

    if not value:
        raise ValueError("a fixed resource names its object; an operation with no target takes none")

    def resource(path_params: dict[str, str], body: bytes) -> str:
        return value

    return resource
