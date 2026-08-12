"""Shared accepted-settlement job coordination."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from market_identity import Identity

from .runtime import SettlementRuntime


@dataclass(frozen=True)
class PreparedSettlement:
    agreement_ref: str
    obligations: tuple[dict[str, Any], ...]
    selected_obligation_index: int
    local_principal: Identity
    mechanism_ref: str
    mechanism_receipt: dict[str, Any] | None
    fulfillment_input: Any
    projection_context: Any = None

    def __post_init__(self) -> None:
        if not self.agreement_ref:
            raise ValueError("agreement_ref must be non-empty")
        if not self.obligations:
            raise ValueError("prepared settlement must contain obligations")
        if not isinstance(self.local_principal, Identity):
            raise TypeError("local_principal must be a canonical marketplace identity")
        if not 0 <= self.selected_obligation_index < len(self.obligations):
            raise ValueError("selected_obligation_index is out of range")
        if not self.mechanism_ref:
            raise ValueError("mechanism_ref must be non-empty")


@dataclass(frozen=True)
class FulfillmentOutcome:
    status: Literal["fulfilled", "failed"]
    fulfillment_ref: str | None = None
    public_result: dict[str, Any] = field(default_factory=dict)
    private_result: Any = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status == "fulfilled" and not self.fulfillment_ref:
            raise ValueError("fulfilled outcome requires fulfillment_ref")


PrepareSettlementHook = Callable[..., Awaitable[PreparedSettlement]]
ReserveSettlementStartHook = Callable[
    [PreparedSettlement, str, str], Awaitable[dict[str, Any] | None]
]
FulfillSettlementHook = Callable[..., Awaitable[FulfillmentOutcome]]
PersistSettlementOutcomeHook = Callable[
    [PreparedSettlement, FulfillmentOutcome], Awaitable[None]
]
WakeSettlementServicingHook = Callable[[str], Awaitable[None]]


class SettlementJobCoordinator:
    """Verifies, adopts, fulfills, projects, and wakes one exact obligation."""

    def __init__(
        self,
        runtime: SettlementRuntime,
        *,
        prepare: PrepareSettlementHook,
        reserve_start: ReserveSettlementStartHook,
        fulfill: FulfillSettlementHook,
        persist_outcome: PersistSettlementOutcomeHook,
        wake_servicing: WakeSettlementServicingHook,
    ) -> None:
        self._runtime = runtime
        self._prepare = prepare
        self._reserve_start = reserve_start
        self._fulfill = fulfill
        self._persist_outcome = persist_outcome
        self._wake_servicing = wake_servicing
        self._tasks: set[asyncio.Task[FulfillmentOutcome]] = set()

    async def start(
        self,
        *,
        escrow_uid: str,
        negotiation_id: str,
        mechanism_client: Any,
        chain_name: str,
        request: Any = None,
    ) -> dict[str, Any]:
        prepared = await self._prepare(
            escrow_uid=escrow_uid,
            negotiation_id=negotiation_id,
            mechanism_client=mechanism_client,
            chain_name=chain_name,
            request=request,
        )
        records = await self._runtime.register_plan(
            agreement_ref=prepared.agreement_ref,
            obligations=prepared.obligations,
        )
        selected = records[prepared.selected_obligation_index]
        await self._runtime.adopt(
            selected.obligation_ref,
            local_principal=prepared.local_principal,
            mechanism_ref=prepared.mechanism_ref,
            receipt=prepared.mechanism_receipt,
        )
        existing = await self._reserve_start(
            prepared,
            escrow_uid,
            negotiation_id,
        )
        if existing is not None:
            return existing
        task = asyncio.create_task(
            self.run_once(
                prepared,
                obligation_ref=selected.obligation_ref,
                mechanism_client=mechanism_client,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return {
            "escrow_uid": escrow_uid,
            "negotiation_id": negotiation_id,
            "status": "provisioning",
        }

    async def run_once(
        self,
        prepared: PreparedSettlement,
        *,
        obligation_ref: str,
        mechanism_client: Any,
    ) -> FulfillmentOutcome:
        try:
            outcome = await self._fulfill(
                prepared,
                mechanism_client=mechanism_client,
            )
        except Exception as exc:
            outcome = FulfillmentOutcome(
                status="failed",
                reason=f"{type(exc).__name__}: {exc}",
            )
        if outcome.status == "fulfilled":
            assert outcome.fulfillment_ref is not None
            try:
                await self._runtime.bind_fulfillment(
                    obligation_ref,
                    outcome.fulfillment_ref,
                    local_principal=prepared.local_principal,
                )
            except Exception as exc:
                outcome = FulfillmentOutcome(
                    status="failed",
                    public_result=outcome.public_result,
                    private_result=outcome.private_result,
                    reason=f"fulfillment_binding_error: {type(exc).__name__}: {exc}",
                )
        await self._persist_outcome(prepared, outcome)
        if outcome.status == "fulfilled":
            await self._wake_servicing(obligation_ref)
        return outcome
