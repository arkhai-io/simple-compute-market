"""Durable due-work servicing over the canonical operation journal."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .models import SettlementObligationRecord
from .ports import SettlementServicingRepository
from .runtime import SettlementRuntime

logger = logging.getLogger(__name__)
EventCallback = Callable[[str, dict[str, Any]], Any]
TerminalCallback = Callable[[SettlementObligationRecord, str, str | None], Any]
ReadyCallback = Callable[[SettlementObligationRecord, str], Awaitable[None] | None]


class _ServicingStepError(RuntimeError):
    def __init__(self, operation: str, error: Exception) -> None:
        super().__init__(f"{type(error).__name__}: {error}")
        self.operation = operation


class SettlementServicingWorker:
    def __init__(
        self,
        runtime: SettlementRuntime,
        repository: SettlementServicingRepository,
        *,
        worker_id: str,
        interval_seconds: float,
        on_event: EventCallback | None = None,
        on_terminal: TerminalCallback | None = None,
        on_ready: ReadyCallback | None = None,
    ) -> None:
        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._runtime = runtime
        self._repository = repository
        self._worker_id = worker_id
        self._interval_seconds = interval_seconds
        self._on_event = on_event
        self._on_terminal = on_terminal
        self._on_ready = on_ready

    async def run_once(self, limit: int = 50) -> int:
        now = time.time()
        rows = await self._repository.list_due_settlement_obligations(
            now_unix=now,
            limit=limit,
        )
        processed = 0
        for row in rows:
            record = SettlementObligationRecord.model_validate(row)
            try:
                await self._service(record, now)
            except _ServicingStepError as exc:
                operation = exc.operation
                try:
                    await self._schedule(
                        record.obligation_ref,
                        operation,
                        now,
                        f"{type(exc).__name__}: {exc}",
                    )
                except Exception:
                    logger.exception(
                        "could not schedule settlement retry for %s",
                        record.obligation_ref,
                    )
                await self._emit(
                    "settlement_retry",
                    {
                        "obligation_ref": record.obligation_ref,
                        "operation": operation,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
            except Exception as exc:
                logger.exception(
                    "settlement servicing rejected %s",
                    record.obligation_ref,
                )
                await self._terminal(
                    record,
                    "manual_required",
                    f"{type(exc).__name__}: {exc}",
                )
            processed += 1
        return processed

    async def run(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval_seconds)
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("settlement servicing sweep failed")

    async def wake(self, obligation_ref: str) -> None:
        await self._repository.wake_settlement_obligation(obligation_ref)
        await self._emit(
            "settlement_woken",
            {"obligation_ref": obligation_ref},
        )

    async def _service(
        self,
        initial: SettlementObligationRecord,
        now: float,
    ) -> None:
        claimant_principal = initial.claimant_principal
        try:
            status = await self._runtime.reconcile_status(
                obligation_ref=initial.obligation_ref,
                local_principal=claimant_principal,
                worker_id=self._worker_id,
            )
        except Exception as exc:
            raise _ServicingStepError("status", exc) from exc
        if status.status == "busy":
            return
        record = await self._reload(initial.obligation_ref)
        if (
            record.mechanism_status == "failed"
            and record.fulfillment_ref is not None
            and record.collection_state != "succeeded"
        ):
            await self._cleanup(record, record.last_error)
            return
        if record.mechanism_status in {
            "reclaimed",
            "expired",
            "failed",
            "manual_required",
        }:
            await self._terminal(
                record,
                record.mechanism_status,
                record.last_error,
            )
            return
        if status.status == "terminal":
            await self._terminal(
                record,
                record.mechanism_status or status.status,
                record.last_error,
            )
            return
        if record.collection_state == "succeeded":
            if not record.mechanism_state.get("terminal_risk_monitoring"):
                await self._terminal(record, "collected", None)
                return
            await self._schedule(record.obligation_ref, "status", now)
            await self._emit(
                "settlement_terminal_risk_monitored",
                {"obligation_ref": record.obligation_ref},
            )
            return
        if record.mechanism_status != "ready":
            await self._schedule(record.obligation_ref, "status", now)
            await self._emit(
                "settlement_status_pending",
                {"obligation_ref": record.obligation_ref},
            )
            return
        if record.fulfillment_ref is None:
            if self._on_ready is None:
                await self._schedule(record.obligation_ref, "fulfill", now)
                return
            try:
                ready_result = self._on_ready(record, self._worker_id)
                if inspect.isawaitable(ready_result):
                    await ready_result
            except Exception as exc:
                raise _ServicingStepError("fulfill", exc) from exc
            record = await self._reload(record.obligation_ref)
            if record.fulfillment_ref is None:
                await self._schedule(record.obligation_ref, "fulfill", now)
                return
        if record.condition_state == "pending":
            try:
                checked = await self._runtime.check(
                    obligation_ref=record.obligation_ref,
                    local_principal=claimant_principal,
                    worker_id=self._worker_id,
                )
            except Exception as exc:
                raise _ServicingStepError("check", exc) from exc
            record = await self._reload(record.obligation_ref)
            if checked.status == "busy":
                return
            if checked.status == "pending":
                await self._schedule(record.obligation_ref, "check", now)
                await self._emit(
                    "settlement_conditions_pending",
                    {"obligation_ref": record.obligation_ref},
                )
                return
            if checked.status in {"manual_required", "terminal"}:
                await self._terminal(
                    record,
                    record.condition_state,
                    record.last_error,
                )
                return
        if record.condition_state != "ready":
            return
        try:
            collected = await self._runtime.collect(
                obligation_ref=record.obligation_ref,
                local_principal=claimant_principal,
                worker_id=self._worker_id,
            )
        except Exception as exc:
            raise _ServicingStepError("collect", exc) from exc
        record = await self._reload(record.obligation_ref)
        if collected.status == "succeeded":
            await self._emit(
                "settlement_collected",
                {"obligation_ref": record.obligation_ref},
            )
            await self._terminal(record, "collected", None)
        elif collected.status == "manual_required":
            await self._terminal(record, "manual_required", record.last_error)

    async def _cleanup(
        self,
        record: SettlementObligationRecord,
        reason: str | None,
    ) -> None:
        reserved = await self._runtime.reserve_cleanup(
            record.obligation_ref,
            local_principal=record.claimant_principal,
            worker_id=self._worker_id,
        )
        if reserved.status in {"busy", "succeeded"}:
            return
        try:
            if self._on_terminal is not None:
                result = self._on_terminal(record, "failed", reason)
                if inspect.isawaitable(result):
                    await result
            await self._runtime.complete_cleanup(
                record.obligation_ref,
                local_principal=record.claimant_principal,
                worker_id=self._worker_id,
            )
        except Exception as exc:
            await self._runtime.retry_cleanup(
                record.obligation_ref,
                exc,
                local_principal=record.claimant_principal,
                worker_id=self._worker_id,
            )
            raise _ServicingStepError("cleanup", exc) from exc
        await self._emit(
            "settlement_cleanup_complete",
            {"obligation_ref": record.obligation_ref},
        )

    async def _reload(self, obligation_ref: str) -> SettlementObligationRecord:
        row = await self._repository.load_settlement_obligation(obligation_ref)
        if row is None:
            raise KeyError(f"unknown settlement obligation {obligation_ref!r}")
        return SettlementObligationRecord.model_validate(row)

    async def _schedule(
        self,
        obligation_ref: str,
        operation: str,
        now: float,
        error: str | None = None,
    ) -> None:
        row = await self._repository.load_settlement_operation(
            obligation_ref,
            operation,
        )
        if row is None or row.get("state") != "pending":
            return
        attempts = max(1, int(row.get("attempts") or 1))
        backoff = min(30.0 * (2 ** (attempts - 1)), 1800.0)
        await self._repository.schedule_settlement_retry(
            obligation_ref=obligation_ref,
            operation=operation,
            next_attempt_unix=now + backoff,
            last_error=error,
        )

    @staticmethod
    def _operation_for(record: SettlementObligationRecord) -> str:
        if record.collection_state == "succeeded":
            return "status"
        if record.condition_state == "ready":
            return "collect"
        if record.mechanism_status == "ready":
            return "fulfill" if record.fulfillment_ref is None else "check"
        return "status"

    async def _emit(self, event: str, fields: dict[str, Any]) -> None:
        if self._on_event is None:
            return
        try:
            result = self._on_event(event, dict(fields))
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception("settlement event callback failed for %s", event)

    async def _terminal(
        self,
        record: SettlementObligationRecord,
        outcome: str,
        reason: str | None,
    ) -> None:
        if self._on_terminal is None:
            return
        try:
            result = self._on_terminal(record, outcome, reason)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.exception(
                "settlement terminal callback failed for %s",
                record.obligation_ref,
            )
