"""Injected ports for settlement mechanisms and durable persistence."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .models import (
    ConditionOutcome,
    EffectOutcome,
    MaterializationOutcome,
    StatusOutcome,
)


@runtime_checkable
class ConditionalEscrowClient(Protocol):
    async def materialize(
        self,
        obligation: dict[str, Any],
        *,
        operation_ref: str,
    ) -> MaterializationOutcome: ...

    async def get_status(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> StatusOutcome: ...

    async def check(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        fulfillment_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> ConditionOutcome: ...

    async def collect(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        fulfillment_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> EffectOutcome: ...

    async def reclaim_expired(
        self,
        obligation: dict[str, Any],
        *,
        mechanism_ref: str,
        operation_ref: str,
        mechanism_state: dict[str, Any],
    ) -> EffectOutcome: ...


@runtime_checkable
class SettlementRuntimeRepository(Protocol):
    async def upsert_settlement_obligation(
        self, obligation: dict[str, Any]
    ) -> dict[str, Any]: ...
    async def load_settlement_obligation(
        self, obligation_ref: str
    ) -> dict[str, Any] | None: ...
    async def load_settlement_obligation_by_mechanism_ref(
        self, mechanism_ref: str
    ) -> dict[str, Any] | None: ...
    async def list_settlement_obligations(
        self, agreement_ref: str
    ) -> list[dict[str, Any]]: ...
    async def bind_settlement_fulfillment(
        self, *, obligation_ref: str, fulfillment_ref: str
    ) -> dict[str, Any]: ...
    async def reserve_settlement_operation(
        self,
        *,
        obligation_ref: str,
        operation: str,
        request_hash: str,
        lease_owner: str,
        now_unix: float,
        lease_until_unix: float,
    ) -> dict[str, Any] | None: ...
    async def finish_settlement_operation(
        self,
        *,
        obligation_ref: str,
        operation: str,
        lease_owner: str,
        state: str,
        receipt: dict[str, Any] | None = None,
        last_error: str | None = None,
        uncertain_acknowledgement: bool = False,
        mechanism_ref: str | None = None,
        mechanism_status: str | None = None,
        mechanism_state: dict[str, Any] | None = None,
        buyer_action: dict[str, Any] | None = None,
        condition_anchor: str | None = None,
        condition_state: str | None = None,
        next_attempt_unix: float | None = None,
    ) -> bool: ...


@runtime_checkable
class SettlementServicingRepository(Protocol):
    async def load_settlement_obligation(
        self,
        obligation_ref: str,
    ) -> dict[str, Any] | None: ...
    async def load_settlement_operation(
        self,
        obligation_ref: str,
        operation: str,
    ) -> dict[str, Any] | None: ...
    async def list_due_settlement_obligations(
        self, *, now_unix: float, limit: int = 50
    ) -> list[dict[str, Any]]: ...
    async def schedule_settlement_retry(
        self,
        *,
        obligation_ref: str,
        operation: str,
        next_attempt_unix: float,
        last_error: str | None = None,
    ) -> None: ...
    async def wake_settlement_obligation(self, obligation_ref: str) -> None: ...
