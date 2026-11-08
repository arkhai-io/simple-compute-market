"""Framework-free settlement admin routes every storefront binds.

Verify and evaluate are dry runs: they read and plan, and write nothing. Wait
long-polls a settlement until it is terminal. What a domain checks and plans is
its own, supplied as hooks; the paths, bodies, refusals, and wait semantics are
the same for every storefront. Results are plain mappings, which each storefront
wraps in its response models.

Which settlement a waited reference names, and which delivery statuses end the
wait, are decided here for every storefront and every mechanism
(:class:`SettlementLookup`, :data:`TERMINAL_SETTLEMENT_STATUSES`); a storefront
supplies only its settlement-evidence lookups and its delivery status for a
resolved settlement, so an operator waits on any storefront's deal by the same
references.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from market_core import SettlementEvidence

#: Longest a wait may block, whatever the caller asks for.
MAX_WAIT_SECONDS = 120.0

#: The delivery statuses that end a wait: delivered, or never to be — failed,
#: or ended before it was delivered.
TERMINAL_SETTLEMENT_STATUSES = frozenset({"ready", "failed", "ended"})


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


class SettlementEvidenceLookup(Protocol):
    async def __call__(self, key: str, /) -> SettlementEvidence | None:
        """The storefront's settlement evidence under ``key``, or ``None``."""


class DeliveryStatusHook(Protocol):
    async def __call__(self, evidence: SettlementEvidence, /) -> Mapping[str, Any]:
        """The domain's delivery status for a resolved settlement.

        Its ``status`` ends a wait when it is one of
        :data:`TERMINAL_SETTLEMENT_STATUSES`; the rest of the mapping is the
        domain's report, returned to the waiting administrator as it is. Raises
        ``LookupError`` or :class:`SettlementAdminRouteError` to refuse."""


@dataclass(frozen=True)
class SettlementLookup:
    """A storefront's two ways to find a settlement's evidence.

    ``by_reference`` finds the evidence whose settlement reference is the key
    (an Alkahest escrow, an Arkhai payments transaction); ``by_negotiation``
    finds the evidence of the negotiation the key names.
    """

    by_reference: SettlementEvidenceLookup
    by_negotiation: SettlementEvidenceLookup

    async def resolve(self, reference: str) -> SettlementEvidence | None:
        """The settlement ``reference`` names, whatever its mechanism.

        A reference names a settlement by the reference its evidence records
        first, and otherwise by its negotiation, so a deal is found by either
        whether or not its mechanism has established a reference yet. ``None``
        when it names neither.
        """

        evidence = await self.by_reference(reference)
        if evidence is None:
            evidence = await self.by_negotiation(reference)
        return evidence


class SettlementAdminRouteService:
    """Verify, evaluate, and wait on one storefront's settlements."""

    def __init__(
        self,
        *,
        settlements: SettlementLookup,
        delivery_status: DeliveryStatusHook,
        verify: EscrowVerifyHook | None = None,
        preview_fulfillment: FulfillmentPreviewHook | None = None,
        poll_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._verify = verify
        self._preview = preview_fulfillment
        self._settlements = settlements
        self._delivery_status = delivery_status
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

    async def wait(self, reference: str, *, timeout: float) -> dict[str, Any]:
        """Block until the settlement ``reference`` names is terminal or
        ``timeout`` elapses.

        Each poll resolves the reference afresh (:meth:`SettlementLookup.resolve`),
        since evidence may be recorded, or its reference established, while the
        wait runs; a reference that resolves to nothing is a poll that found
        nothing terminal. ``ready`` says whether a terminal delivery status was
        reached; the status mapping the domain reports is returned beside it
        either way. A read that fails, a lookup's or the delivery status's, is a
        poll that found nothing terminal, since the wait is how an operator
        learns the outcome and one failed read is not one: the wait polls on,
        and a wait that ends unready after a failed last read carries its
        ``last_error``. A refusal either raises, a ``LookupError`` or a
        :class:`SettlementAdminRouteError`, is an answer, not a failed read, and
        ends the wait.
        """

        start = self._clock()
        deadline = start + min(max(timeout, 0.0), MAX_WAIT_SECONDS)
        status: dict[str, Any] = {}
        last_error: str | None = None
        while True:
            try:
                evidence = await self._settlements.resolve(reference)
                status = (
                    {} if evidence is None else dict(await self._delivery_status(evidence))
                )
            except (LookupError, SettlementAdminRouteError):
                raise
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                last_error = None
                if status.get("status") in TERMINAL_SETTLEMENT_STATUSES:
                    return self._waited(status, ready=True, start=start)
            remaining = deadline - self._clock()
            if remaining <= 0:
                return self._waited(
                    status, ready=False, start=start, last_error=last_error
                )
            await asyncio.sleep(min(self._poll_seconds, remaining))

    def _waited(
        self,
        status: dict[str, Any],
        *,
        ready: bool,
        start: float,
        last_error: str | None = None,
    ) -> dict[str, Any]:
        waited = {
            **status,
            "ready": ready,
            "status": status.get("status") or ("unknown" if not ready else ""),
            "elapsed_ms": int((self._clock() - start) * 1000),
        }
        if last_error is not None:
            waited["last_error"] = last_error
        return waited


__all__ = [
    "DeliveryStatusHook",
    "EscrowVerifyHook",
    "FulfillmentPreviewHook",
    "MAX_WAIT_SECONDS",
    "SettlementAdminRouteError",
    "SettlementAdminRouteService",
    "SettlementEvidenceLookup",
    "SettlementLookup",
    "TERMINAL_SETTLEMENT_STATUSES",
]
