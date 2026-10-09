"""Framework-free settlement admin routes every storefront binds.

Verify and evaluate are dry runs: they read and plan, and write nothing. Wait
long-polls a settlement until it is terminal. What a domain checks and plans is
its own, supplied as hooks; the paths, bodies, refusals, and wait semantics are
the same for every storefront. Results are plain mappings, which each storefront
wraps in its response models.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

#: Longest a wait may block, whatever the caller asks for.
MAX_WAIT_SECONDS = 120.0


class SettlementAdminRouteError(RuntimeError):
    """HTTP-shaped failure raised without depending on a web framework."""

    def __init__(self, status_code: int, detail: Any) -> None:
        super().__init__(str(detail))
        self.status_code = status_code
        self.detail = detail


class EscrowVerifyHook(Protocol):
    async def __call__(
        self, escrow_uid: str, request: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Read the escrow and compare it with the expected terms, writing
        nothing. Returns ``valid`` and, when invalid, ``reason``; raises
        ``LookupError`` when the referenced listing or agreement is unknown."""


class FulfillmentPreviewHook(Protocol):
    async def __call__(
        self, escrow_uid: str, request: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        """Plan the fulfillment settlement would start, writing nothing.
        Returns ``would_submit`` and the domain's plan, or a ``reason``; raises
        ``LookupError`` when the referenced listing or agreement is unknown."""


class SettlementAdminRouteService:
    """Verify, evaluate, and wait on one storefront's settlements."""

    def __init__(
        self,
        *,
        settle_status: Callable[[str], Awaitable[Mapping[str, Any] | None]],
        is_terminal: Callable[[Mapping[str, Any]], bool],
        verify: EscrowVerifyHook | None = None,
        preview_fulfillment: FulfillmentPreviewHook | None = None,
        poll_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._verify = verify
        self._preview = preview_fulfillment
        self._settle_status = settle_status
        self._is_terminal = is_terminal
        self._poll_seconds = poll_seconds
        self._clock = clock

    async def verify(
        self, escrow_uid: str, request: Mapping[str, Any]
    ) -> dict[str, Any]:
        if self._verify is None:
            raise SettlementAdminRouteError(404, "settle verify is not offered here")
        try:
            result = dict(await self._verify(escrow_uid, request))
        except LookupError as exc:
            raise SettlementAdminRouteError(404, str(exc)) from exc
        result["escrow_uid"] = escrow_uid
        return result

    async def evaluate(
        self, escrow_uid: str, request: Mapping[str, Any]
    ) -> dict[str, Any]:
        if self._preview is None:
            raise SettlementAdminRouteError(404, "settle evaluate is not offered here")
        try:
            result = dict(await self._preview(escrow_uid, request))
        except LookupError as exc:
            raise SettlementAdminRouteError(404, str(exc)) from exc
        result["escrow_uid"] = escrow_uid
        return result

    async def wait(self, escrow_uid: str, *, timeout: float) -> dict[str, Any]:
        """Block until the settlement is terminal or ``timeout`` elapses.

        ``ready`` says whether a terminal state was reached; the status mapping
        the domain reports is returned beside it either way.
        """

        start = self._clock()
        deadline = start + min(max(timeout, 0.0), MAX_WAIT_SECONDS)
        while True:
            status = dict(await self._settle_status(escrow_uid) or {})
            if status and self._is_terminal(status):
                return self._waited(status, ready=True, start=start)
            remaining = deadline - self._clock()
            if remaining <= 0:
                return self._waited(status, ready=False, start=start)
            await asyncio.sleep(min(self._poll_seconds, remaining))

    def _waited(
        self, status: dict[str, Any], *, ready: bool, start: float
    ) -> dict[str, Any]:
        return {
            **status,
            "ready": ready,
            "status": status.get("status") or ("unknown" if not ready else ""),
            "elapsed_ms": int((self._clock() - start) * 1000),
        }


__all__ = [
    "EscrowVerifyHook",
    "FulfillmentPreviewHook",
    "MAX_WAIT_SECONDS",
    "SettlementAdminRouteError",
    "SettlementAdminRouteService",
]
