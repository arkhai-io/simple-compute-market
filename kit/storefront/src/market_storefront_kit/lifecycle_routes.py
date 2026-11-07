"""Framework-free lifecycle routes over one storefront's loop controller.

Each storefront binds these into its own router behind its own administrator
authentication; the paths and response shapes are the same for every
storefront, so one typed client drives all of them.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .lifecycle import LoopNotFound, PreviewNotOffered, StorefrontLoopController


class LifecycleRouteError(RuntimeError):
    """HTTP-shaped failure emitted without depending on a web framework."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class StorefrontLifecycleRouteService:
    """Pause, resume, step, and preview the loops of one storefront."""

    def __init__(self, controller: StorefrontLoopController) -> None:
        self._controller = controller

    async def pause(self) -> dict[str, Any]:
        """Hold every loop; trading is unaffected."""

        return {"paused": True, "loops": await self._controller.pause()}

    async def resume(self) -> dict[str, Any]:
        """Return every loop to work."""

        return {"paused": False, "loops": await self._controller.resume()}

    async def run_cycle(self, route: str) -> Mapping[str, Any]:
        """Run one cycle of a loop, returning exactly what its step returns."""

        try:
            return await self._controller.run_cycle(route)
        except LoopNotFound as exc:
            raise LifecycleRouteError(404, f"no lifecycle loop {route!r}") from exc

    async def dry_run(self, route: str) -> Mapping[str, Any]:
        """Preview one cycle of a loop, applying nothing."""

        try:
            return await self._controller.dry_run(route)
        except LoopNotFound as exc:
            raise LifecycleRouteError(404, f"no lifecycle loop {route!r}") from exc
        except PreviewNotOffered as exc:
            raise LifecycleRouteError(
                404, f"lifecycle loop {route!r} offers no preview"
            ) from exc


__all__ = ["LifecycleRouteError", "StorefrontLifecycleRouteService"]
