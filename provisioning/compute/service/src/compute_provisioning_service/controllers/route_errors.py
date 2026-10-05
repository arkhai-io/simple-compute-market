"""How this service's bindings answer a route service's refusal."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from compute_provisioning.route_errors import ProvisioningRouteError
from fastapi import HTTPException

T = TypeVar("T")


def routed(call: Callable[[], T]) -> T:
    """Run a route service call, answering its refusal with its status and detail."""
    try:
        return call()
    except ProvisioningRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


async def routed_async(call: Callable[[], Awaitable[T]]) -> T:
    try:
        return await call()
    except ProvisioningRouteError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
