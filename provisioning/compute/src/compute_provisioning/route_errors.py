"""The one error a framework-free route service reports a refusal with.

A route service validates and performs a route without depending on a web
framework, so it cannot raise an HTTP exception. It raises this, carrying the
status a binding answers with and the detail it returns; each binding turns it
into its framework's response.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

T = TypeVar("T")


class ProvisioningRouteError(RuntimeError):
    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


def require_composed(accessor: Callable[[], T | None], what: str) -> T:
    """The collaborator ``accessor`` resolves, or a 503 refusal while there is none.

    A binding is mounted when the app is built and its collaborators are
    composed later, at startup, so it reaches them through an accessor. A
    request that finds nothing composed is refused as unavailable rather than
    failing inside the route.
    """
    collaborator = accessor()
    if collaborator is None:
        raise ProvisioningRouteError(503, f"{what} is not initialised")
    return collaborator


__all__ = ["ProvisioningRouteError", "require_composed"]
