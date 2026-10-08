"""How VM's bindings answer a refusal and reach their collaborators."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from compute_provisioning.route_errors import ProvisioningRouteError, require_composed
from fastapi import HTTPException

T = TypeVar("T")


def routed(call: Callable[[], T]) -> T:
    """Run a route service call, answering its refusal with its status and detail."""
    try:
        return call()
    except ProvisioningRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


def dependency(accessor: Callable[[], T | None], what: str) -> Callable[[], T]:
    """A route dependency resolving ``accessor`` per request, 503 while it is unset."""

    def resolve() -> T:
        return routed(lambda: require_composed(accessor, what))

    return resolve


__all__ = ["dependency", "routed"]
