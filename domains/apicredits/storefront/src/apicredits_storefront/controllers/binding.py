"""What every binding does with a route service's refusal: serve it as the response it names."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import TypeVar

from arkhai_api_selling.route_services import RouteRefusal
from fastapi import HTTPException

T = TypeVar("T")


async def serve(call: Awaitable[T]) -> T:
    try:
        return await call
    except RouteRefusal as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
