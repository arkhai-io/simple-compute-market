"""Mechanism-neutral settlement lifecycle and operation journal control flow."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping
from typing import Any, Literal

from market_identity import Identity

from .models import (
    MaterializationOutcome,
    SettlementObligationRecord,
    SettlementOperationOutcome,
    SettlementPlanStatus,
    StatusOutcome,
    aggregate_settlement_status,
    canonical_json,
)
from .ports import ConditionalEscrowClient, SettlementRuntimeRepository


class SettlementManualRequired(RuntimeError):
    """A mechanism cannot safely converge without operator evidence."""


class SettlementRuntime:
    """Registers plans and executes principal-authorized obligation operations."""

    def __init__(
        self,
        repository: SettlementRuntimeRepository,
        clients: Mapping[str, ConditionalEscrowClient],
        *,
        clock: Callable[[], float] = time.time,
        lease_seconds: float = 30.0,
    ) -> None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self._repository = repository
        self._clients = dict(clients)
        self._clock = clock
        self._lease_seconds = lease_seconds

    async def register_plan(
        self,
        *,
        agreement_ref: str,
        obligations: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    ) -> list[SettlementObligationRecord]:
        records: list[SettlementObligationRecord] = []
        for index, obligation in enumerate(obligations):
            record = SettlementObligationRecord.from_obligation(
                agreement_ref=agreement_ref,
                obligation_index=index,
                obligation=obligation,
            )
            stored = await self._repository.upsert_settlement_obligation(
                record.model_dump()
            )
            records.append(SettlementObligationRecord.model_validate(stored))
        return records

    async def get_status(self, agreement_ref: str) -> SettlementPlanStatus:
        obligations = [
            SettlementObligationRecord.model_validate(row)
            for row in await self._repository.list_settlement_obligations(agreement_ref)
        ]
        return SettlementPlanStatus(
            agreement_ref=agreement_ref,
            status=aggregate_settlement_status(obligations),
            obligations=obligations,
        )

    async def adopt(
        self,
        obligation_ref: str,
        *,
        local_principal: Identity,
        mechanism_ref: str,
        receipt: dict[str, Any] | None = None,
        condition_anchor: str | None = None,
        mechanism_state: dict[str, Any] | None = None,
        worker_id: str = "adopt",
    ) -> SettlementOperationOutcome:
        """Record an already verified escrow without dispatching an adapter."""
        if not mechanism_ref:
            raise ValueError("mechanism_ref must be non-empty")
        record = await self._load(obligation_ref)
        self._require_participant(record, local_principal, operation="adopt")
        reserved = await self._reserve(
            record,
            "materialize",
            worker_id,
            local_principal,
            request_values={"adopted_mechanism_ref": mechanism_ref},
        )
        if reserved is None:
            return self._outcome(record, "materialize", "busy")
        terminal = self._terminal_outcome(record, "materialize", reserved)
        if terminal is not None:
            return terminal
        await self._finish(
            record,
            "materialize",
            worker_id,
            state="succeeded",
            receipt=receipt,
            mechanism_ref=mechanism_ref,
            mechanism_status="ready",
            mechanism_state=mechanism_state or {},
            condition_anchor=condition_anchor,
        )
        return self._outcome(record, "materialize", "succeeded", receipt)

    async def bind_fulfillment(
        self,
        obligation_ref: str,
        fulfillment_ref: str,
        *,
        local_principal: Identity,
        worker_id: str = "fulfillment",
    ) -> SettlementObligationRecord:
        """Bind the claimant's immutable public fulfillment reference once."""
        del worker_id
        record = await self._load(obligation_ref)
        self._require_principal(record, local_principal, "claimant")
        if not fulfillment_ref:
            raise ValueError("fulfillment_ref must be non-empty")
        row = await self._repository.bind_settlement_fulfillment(
            obligation_ref=obligation_ref,
            fulfillment_ref=fulfillment_ref,
        )
        return SettlementObligationRecord.model_validate(row)

    async def reserve_fulfillment(
        self,
        obligation_ref: str,
        *,
        local_principal: Identity,
        worker_id: str,
    ) -> SettlementOperationOutcome:
        """Reserve one durable domain-fulfillment attempt.

        The reservation shares the settlement operation journal so a process
        restart can take over an expired lease without creating a second
        fulfillment.  A previously bound immutable reference is treated as
        authoritative and repairs an unfinished operation row.
        """
        record = await self._load(obligation_ref)
        self._require_principal(record, local_principal, "claimant")
        reserved = await self._reserve(record, "fulfill", worker_id, local_principal)
        if reserved is None:
            return self._outcome(record, "fulfill", "busy")
        terminal = self._terminal_outcome(record, "fulfill", reserved)
        if terminal is not None:
            return terminal
        if record.fulfillment_ref:
            receipt = {"fulfillment_ref": record.fulfillment_ref}
            await self._finish(
                record,
                "fulfill",
                worker_id,
                state="succeeded",
                receipt=receipt,
            )
            return self._outcome(record, "fulfill", "succeeded", receipt)
        return self._outcome(record, "fulfill", "pending")

    async def complete_fulfillment(
        self,
        obligation_ref: str,
        fulfillment_ref: str,
        *,
        local_principal: Identity,
        worker_id: str,
    ) -> SettlementObligationRecord:
        """Commit fulfillment identity before completing its leased operation."""
        record = await self.bind_fulfillment(
            obligation_ref,
            fulfillment_ref,
            local_principal=local_principal,
            worker_id=worker_id,
        )
        await self._finish(
            record,
            "fulfill",
            worker_id,
            state="succeeded",
            receipt={"fulfillment_ref": fulfillment_ref},
        )
        return await self._load(obligation_ref)

    async def retry_fulfillment(
        self,
        obligation_ref: str,
        error: Exception,
        *,
        local_principal: Identity,
        worker_id: str,
    ) -> None:
        """Release a failed fulfillment lease for deterministic retry."""
        record = await self._load(obligation_ref)
        self._require_principal(record, local_principal, "claimant")
        await self._finish_retry(
            record,
            "fulfill",
            worker_id,
            error,
            uncertain=True,
        )

    async def materialize(
        self,
        *,
        obligation_ref: str,
        local_principal: Identity,
        worker_id: str,
    ) -> SettlementOperationOutcome:
        record = await self._load(obligation_ref)
        self._require_principal(record, local_principal, "payer")
        client = self._client(record)
        reserved = await self._reserve(
            record, "materialize", worker_id, local_principal
        )
        if reserved is None:
            return self._outcome(record, "materialize", "busy")
        terminal = self._terminal_outcome(record, "materialize", reserved)
        if terminal is not None:
            return terminal
        try:
            result = await client.materialize(
                record.obligation,
                operation_ref=settlement_operation_ref(
                    record.obligation_ref, "materialize"
                ),
            )
        except SettlementManualRequired as exc:
            return await self._finish_manual(record, "materialize", worker_id, exc)
        except Exception as exc:
            await self._finish_retry(
                record, "materialize", worker_id, exc, uncertain=True
            )
            raise
        state = (
            "manual_required"
            if result.status == "manual_required"
            else "succeeded"
            if result.status == "ready"
            else "pending"
        )
        await self._finish_materialization(record, worker_id, result, state)
        return self._outcome(
            record,
            "materialize",
            "manual_required"
            if state == "manual_required"
            else "succeeded"
            if state == "succeeded"
            else "pending",
            result.receipt,
        )

    async def reconcile_status(
        self,
        *,
        obligation_ref: str,
        local_principal: Identity,
        worker_id: str,
    ) -> SettlementOperationOutcome:
        record = await self._load(obligation_ref)
        self._require_participant(record, local_principal, operation="reconcile")
        if record.collection_state == "succeeded":
            return self._outcome(
                record,
                "status",
                "terminal",
                record.collection_receipt,
            )
        if record.reclaim_state == "succeeded":
            return self._outcome(
                record,
                "status",
                "terminal",
                record.reclaim_receipt,
            )
        mechanism_ref = self._require_mechanism_ref(record)
        client = self._client(record)
        reserved = await self._reserve(record, "status", worker_id, local_principal)
        if reserved is None:
            return self._outcome(record, "status", "busy")
        terminal = self._terminal_outcome(record, "status", reserved)
        if terminal is not None:
            return terminal
        try:
            result = await client.get_status(
                record.obligation,
                mechanism_ref=mechanism_ref,
                operation_ref=settlement_operation_ref(record.obligation_ref, "status"),
                mechanism_state=dict(record.mechanism_state),
            )
        except SettlementManualRequired as exc:
            return await self._finish_manual(record, "status", worker_id, exc)
        except Exception as exc:
            await self._finish_retry(record, "status", worker_id, exc, uncertain=False)
            raise
        state = (
            "manual_required"
            if result.status == "manual_required"
            else "succeeded"
            if result.status in {"collected", "reclaimed", "expired", "failed"}
            else "pending"
        )
        await self._finish_status(record, worker_id, result, state)
        return self._outcome(
            record,
            "status",
            "manual_required"
            if state == "manual_required"
            else "terminal"
            if state == "succeeded"
            else "pending",
            result.receipt,
        )

    async def check(
        self,
        *,
        obligation_ref: str,
        local_principal: Identity,
        worker_id: str,
    ) -> SettlementOperationOutcome:
        record = await self._load(obligation_ref)
        self._require_principal(record, local_principal, "claimant")
        mechanism_ref = self._require_materialized(record)
        fulfillment_ref = self._require_fulfillment(record)
        client = self._client(record)
        reserved = await self._reserve(
            record,
            "check",
            worker_id,
            local_principal,
            request_values={"fulfillment_ref": fulfillment_ref},
        )
        if reserved is None:
            return self._outcome(record, "check", "busy")
        terminal = self._terminal_outcome(record, "check", reserved)
        if terminal is not None:
            return terminal
        try:
            result = await client.check(
                record.obligation,
                mechanism_ref=mechanism_ref,
                fulfillment_ref=fulfillment_ref,
                operation_ref=settlement_operation_ref(record.obligation_ref, "check"),
                mechanism_state=dict(record.mechanism_state),
            )
        except SettlementManualRequired as exc:
            return await self._finish_manual(record, "check", worker_id, exc)
        except Exception as exc:
            await self._finish_retry(record, "check", worker_id, exc, uncertain=False)
            raise
        state = (
            "pending"
            if result.decision == "pending"
            else "manual_required"
            if result.decision == "manual_required"
            else "succeeded"
        )
        await self._finish(
            record,
            "check",
            worker_id,
            state=state,
            receipt=result.receipt,
            last_error=result.last_error,
            mechanism_state=result.mechanism_state,
            condition_state=result.decision,
        )
        return self._outcome(
            record,
            "check",
            "manual_required"
            if state == "manual_required"
            else "pending"
            if state == "pending"
            else "terminal"
            if result.decision == "failed"
            else "succeeded",
            result.receipt,
        )

    async def collect(
        self,
        *,
        obligation_ref: str,
        local_principal: Identity,
        worker_id: str,
    ) -> SettlementOperationOutcome:
        record = await self._load(obligation_ref)
        self._require_principal(record, local_principal, "claimant")
        mechanism_ref = self._require_materialized(record)
        if record.condition_state != "ready":
            raise ValueError("obligation conditions are not ready")
        fulfillment_ref = self._require_fulfillment(record)
        client = self._client(record)
        reserved = await self._reserve(record, "collect", worker_id, local_principal)
        if reserved is None:
            return self._outcome(record, "collect", "busy")
        terminal = self._terminal_outcome(record, "collect", reserved)
        if terminal is not None:
            return terminal
        try:
            result = await client.collect(
                record.obligation,
                mechanism_ref=mechanism_ref,
                fulfillment_ref=fulfillment_ref,
                operation_ref=settlement_operation_ref(
                    record.obligation_ref, "collect"
                ),
                mechanism_state=dict(record.mechanism_state),
            )
        except SettlementManualRequired as exc:
            return await self._finish_manual(record, "collect", worker_id, exc)
        except Exception as exc:
            await self._finish_retry(record, "collect", worker_id, exc, uncertain=True)
            raise
        await self._finish(
            record,
            "collect",
            worker_id,
            state="succeeded",
            receipt=result.receipt,
            mechanism_state=result.mechanism_state,
        )
        return self._outcome(record, "collect", "succeeded", result.receipt)

    async def reclaim(
        self,
        *,
        obligation_ref: str,
        local_principal: Identity,
        worker_id: str,
    ) -> SettlementOperationOutcome:
        record = await self._load(obligation_ref)
        self._require_principal(record, local_principal, "payer")
        mechanism_ref = self._require_materialized(record)
        if self._clock() < float(record.obligation["expiration_unix"]):
            raise ValueError("obligation has not expired")
        client = self._client(record)
        reserved = await self._reserve(record, "reclaim", worker_id, local_principal)
        if reserved is None:
            return self._outcome(record, "reclaim", "busy")
        terminal = self._terminal_outcome(record, "reclaim", reserved)
        if terminal is not None:
            return terminal
        try:
            result = await client.reclaim_expired(
                record.obligation,
                mechanism_ref=mechanism_ref,
                operation_ref=settlement_operation_ref(
                    record.obligation_ref, "reclaim"
                ),
                mechanism_state=dict(record.mechanism_state),
            )
        except SettlementManualRequired as exc:
            return await self._finish_manual(record, "reclaim", worker_id, exc)
        except Exception as exc:
            await self._finish_retry(record, "reclaim", worker_id, exc, uncertain=True)
            raise
        await self._finish(
            record,
            "reclaim",
            worker_id,
            state="succeeded",
            receipt=result.receipt,
            mechanism_state=result.mechanism_state,
        )
        return self._outcome(record, "reclaim", "succeeded", result.receipt)

    async def _load(self, obligation_ref: str) -> SettlementObligationRecord:
        row = await self._repository.load_settlement_obligation(obligation_ref)
        if row is None:
            raise KeyError(f"unknown settlement obligation {obligation_ref!r}")
        return SettlementObligationRecord.model_validate(row)

    def _client(self, record: SettlementObligationRecord) -> ConditionalEscrowClient:
        mechanism = str(record.obligation.get("mechanism") or "")
        try:
            return self._clients[mechanism]
        except KeyError as exc:
            raise ValueError(f"no conditional escrow client for {mechanism!r}") from exc

    @staticmethod
    def _require_participant(
        record: SettlementObligationRecord,
        local_principal: Identity,
        *,
        operation: str,
    ) -> None:
        if not isinstance(local_principal, Identity):
            raise TypeError("local_principal must be a canonical marketplace identity")
        if (
            local_principal != record.payer_principal
            and local_principal != record.claimant_principal
        ):
            raise PermissionError(f"only an obligation participant may {operation} it")

    @staticmethod
    def _require_principal(
        record: SettlementObligationRecord,
        local_principal: Identity,
        field: Literal["payer", "claimant"],
    ) -> None:
        if not isinstance(local_principal, Identity):
            raise TypeError("local_principal must be a canonical marketplace identity")
        expected = (
            record.payer_principal if field == "payer" else record.claimant_principal
        )
        if local_principal != expected:
            raise PermissionError(
                f"only the obligation {field} may perform this operation"
            )

    @staticmethod
    def _require_mechanism_ref(record: SettlementObligationRecord) -> str:
        if not record.mechanism_ref:
            raise ValueError("obligation has no mechanism_ref")
        return record.mechanism_ref

    @staticmethod
    def _require_materialized(record: SettlementObligationRecord) -> str:
        if record.materialization_state != "materialized" or not record.mechanism_ref:
            raise ValueError("obligation is not materialized")
        return record.mechanism_ref

    @staticmethod
    def _require_fulfillment(record: SettlementObligationRecord) -> str:
        if not record.fulfillment_ref:
            raise ValueError("fulfillment_ref is required")
        return record.fulfillment_ref

    async def _reserve(
        self,
        record: SettlementObligationRecord,
        operation: str,
        worker_id: str,
        local_principal: Identity,
        *,
        request_values: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        now = self._clock()
        return await self._repository.reserve_settlement_operation(
            obligation_ref=record.obligation_ref,
            operation=operation,
            request_hash=_request_hash(
                record,
                operation,
                local_principal=local_principal,
                request_values=request_values,
            ),
            lease_owner=worker_id,
            now_unix=now,
            lease_until_unix=now + self._lease_seconds,
        )

    async def _finish(
        self,
        record: SettlementObligationRecord,
        operation: str,
        worker_id: str,
        **values: Any,
    ) -> None:
        saved = await self._repository.finish_settlement_operation(
            obligation_ref=record.obligation_ref,
            operation=operation,
            lease_owner=worker_id,
            **values,
        )
        if not saved:
            raise RuntimeError("settlement operation lease was lost")

    async def _finish_materialization(
        self,
        record: SettlementObligationRecord,
        worker_id: str,
        result: MaterializationOutcome,
        state: str,
    ) -> None:
        await self._finish(
            record,
            "materialize",
            worker_id,
            state=state,
            receipt=result.receipt,
            last_error=result.last_error,
            mechanism_ref=result.mechanism_ref,
            mechanism_status=result.status,
            mechanism_state=result.mechanism_state,
            buyer_action=result.buyer_action,
            condition_anchor=result.condition_anchor,
        )

    async def _finish_status(
        self,
        record: SettlementObligationRecord,
        worker_id: str,
        result: StatusOutcome,
        state: str,
    ) -> None:
        await self._finish(
            record,
            "status",
            worker_id,
            state=state,
            receipt=result.receipt,
            last_error=result.last_error,
            mechanism_ref=result.mechanism_ref,
            mechanism_status=result.status,
            mechanism_state=result.mechanism_state,
            buyer_action=result.buyer_action,
            condition_anchor=result.condition_anchor,
        )

    async def _finish_retry(
        self,
        record: SettlementObligationRecord,
        operation: str,
        worker_id: str,
        error: Exception,
        *,
        uncertain: bool,
    ) -> None:
        await self._finish(
            record,
            operation,
            worker_id,
            state="pending",
            last_error=f"{type(error).__name__}: {error}",
            uncertain_acknowledgement=uncertain,
        )

    async def _finish_manual(
        self,
        record: SettlementObligationRecord,
        operation: str,
        worker_id: str,
        error: Exception,
    ) -> SettlementOperationOutcome:
        await self._finish(
            record, operation, worker_id, state="manual_required", last_error=str(error)
        )
        return self._outcome(record, operation, "manual_required")

    @staticmethod
    def _terminal_outcome(
        record: SettlementObligationRecord, operation: str, reserved: dict[str, Any]
    ) -> SettlementOperationOutcome | None:
        if reserved["state"] not in ("succeeded", "manual_required"):
            return None
        return SettlementRuntime._outcome(
            record, operation, reserved["state"], reserved.get("receipt")
        )

    @staticmethod
    def _outcome(
        record: SettlementObligationRecord,
        operation: str,
        status: str,
        receipt: dict[str, Any] | None = None,
    ) -> SettlementOperationOutcome:
        return SettlementOperationOutcome.model_validate(
            {
                "obligation_ref": record.obligation_ref,
                "operation": operation,
                "status": status,
                "receipt": receipt,
            }
        )


def settlement_operation_ref(obligation_ref: str, operation: str) -> str:
    return f"arkhai:settlement:{obligation_ref}:{operation}"


def _request_hash(
    record: SettlementObligationRecord,
    operation: str,
    *,
    local_principal: Identity,
    request_values: Mapping[str, Any] | None = None,
) -> str:
    principal_binding: dict[str, Any]
    if operation == "status":
        principal_binding = {
            "payer": record.payer_principal.model_dump(mode="json"),
            "claimant": record.claimant_principal.model_dump(mode="json"),
        }
    else:
        principal_binding = local_principal.model_dump(mode="json")
    payload = {
        "protocol": "arkhai.settlement-operation.v2",
        "obligation_ref": record.obligation_ref,
        "obligation_hash": record.obligation_hash,
        "operation": operation,
        "principal": principal_binding,
        "request": dict(request_values or {}),
    }
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()
