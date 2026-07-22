"""Bare-metal release adapter for leased site reservations."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from typing import Any

from arkhai_bare_metal import (
    BARE_METAL_EXECUTOR_KIND,
    PHYSICAL_HOST_ID_REF_KEY,
    bare_metal_executor_ref,
)

BareMetalReleaseDelegate = Callable[
    [dict[str, Any]], Awaitable[str | None] | str | None
]


def get_physical_host_id(reservation: dict[str, Any]) -> str | None:
    executor_ref = reservation.get("executor_ref") or {}
    if not isinstance(executor_ref, dict):
        return None
    physical_host_id = executor_ref.get(PHYSICAL_HOST_ID_REF_KEY)
    return str(physical_host_id) if physical_host_id else None


class BareMetalReleaseExecutor:
    def __init__(
        self,
        *,
        release_delegate: BareMetalReleaseDelegate | None = None,
    ) -> None:
        self._release_delegate = release_delegate

    async def submit_release(self, reservation: dict[str, Any]) -> str | None:
        if self._release_delegate is None:
            return "direct-release"
        result = self._release_delegate(reservation)
        if inspect.isawaitable(result):
            result = await result
        return result


__all__ = [
    "BARE_METAL_EXECUTOR_KIND",
    "BareMetalReleaseExecutor",
    "PHYSICAL_HOST_ID_REF_KEY",
    "bare_metal_executor_ref",
    "get_physical_host_id",
]
