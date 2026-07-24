"""Periodic recovery for durable fulfillment provider commands."""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy.orm import Session, sessionmaker

from market_fulfillment import (
    ProviderOperationState,
    ProviderRegistry,
    SettlementRecord,
    SettlementRecordState,
    SettlementRepository,
    SettlementRequirement,
    SettlementResource,
    VersionedEnvelope,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ClaimedCommand:
    capacity_reservation_id: str
    state: str
    provider: str
    resource: SettlementResource
    prepared_create: VersionedEnvelope | None
    prepared_teardown: VersionedEnvelope | None
    provider_metadata: dict
    teardown_provider_metadata: dict
    owner_principal: str
    attempt_count: int


def _command(record: SettlementRecord) -> _ClaimedCommand:
    requirement = SettlementRequirement.model_validate(record.scheduling_requirements)
    resource = SettlementResource(
        settlement_resource_id=str(record.settlement_resource_id),
        pool_id=str(record.pool_id),
        resource_kind=requirement.resource_kind,
        provider=str(record.provider),
        attributes=dict(record.resource_attributes or {}),
    )
    prepared = (
        VersionedEnvelope.model_validate(record.prepared_create_operation)
        if record.prepared_create_operation is not None
        else None
    )
    prepared_teardown = (
        VersionedEnvelope.model_validate(record.prepared_teardown_operation)
        if record.prepared_teardown_operation is not None
        else None
    )
    return _ClaimedCommand(
        capacity_reservation_id=str(record.capacity_reservation_id),
        state=str(record.state),
        provider=str(record.provider),
        resource=resource,
        prepared_create=prepared,
        prepared_teardown=prepared_teardown,
        provider_metadata=dict(record.provider_metadata or {}),
        teardown_provider_metadata=dict(record.teardown_provider_metadata or {}),
        owner_principal=str(record.owner_principal),
        attempt_count=int(record.attempt_count or 0),
    )


class FulfillmentRecoveryService:
    """Claim, dispatch, and converge provider work without holding DB locks."""

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        repository: SettlementRepository,
        provider_registry: ProviderRegistry,
        capacity_ledger_service: Any | None = None,
        worker_id: str | None = None,
        lease_seconds: int = 30,
        batch_size: int = 20,
        poll_interval_seconds: float = 5.0,
        jitter: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._session_factory = session_factory
        self._repository = repository
        self._provider_registry = provider_registry
        self._capacity_ledger_service = capacity_ledger_service
        self._worker_id = worker_id or f"fulfillment-{uuid.uuid4()}"
        self._lease_seconds = lease_seconds
        self._batch_size = batch_size
        self._poll_interval_seconds = poll_interval_seconds
        self._jitter = jitter
        self._sweeps = 0
        self._claimed_total = 0
        self._provider_failures = 0
        self._last_sweep_at: datetime | None = None

    def _claim(self) -> list[_ClaimedCommand]:
        with self._session_factory() as db:
            rows = self._repository.claim_pending(
                db,
                states=(
                    SettlementRecordState.dispatch_pending.value,
                    SettlementRecordState.dispatching.value,
                    SettlementRecordState.teardown_dispatch_pending.value,
                    SettlementRecordState.tearing_down.value,
                    SettlementRecordState.teardown_failed.value,
                ),
                limit=self._batch_size,
                lease_seconds=self._lease_seconds,
                worker_id=self._worker_id,
            )
            commands = [_command(record) for record in rows]
            db.commit()
            return commands

    def _retry_at(self, attempt_count: int) -> datetime:
        base = min(300.0, float(2 ** max(0, min(attempt_count - 1, 8))))
        delay = self._jitter(base * 0.8, base * 1.2)
        return datetime.now(timezone.utc) + timedelta(seconds=delay)

    def _clear(self, command: _ClaimedCommand, *, retry: bool) -> None:
        with self._session_factory() as db:
            self._repository.clear_claim(
                db,
                command.capacity_reservation_id,
                worker_id=self._worker_id,
                retry_at=self._retry_at(command.attempt_count) if retry else None,
            )
            db.commit()

    async def _recover_submission(self, command: _ClaimedCommand) -> None:
        if command.prepared_create is None:
            raise ValueError("pending fulfillment has no prepared create operation")
        provider = self._provider_registry.require(
            command.provider,
            command.resource.resource_kind,
        )
        result = await provider.dispatch_create(command.prepared_create)
        with self._session_factory() as db:
            self._repository.transition(
                db,
                command.capacity_reservation_id,
                SettlementRecordState.dispatching.value,
                provider_metadata=dict(result.provider_metadata),
            )
            for domain_resource_ref in result.provisioned_resource_refs:
                self._repository.add_provisioned_resource(
                    db,
                    capacity_reservation_id=command.capacity_reservation_id,
                    domain_resource_ref=domain_resource_ref,
                )
            self._repository.clear_claim(
                db,
                command.capacity_reservation_id,
                worker_id=self._worker_id,
            )
            db.commit()

    async def _recover_status(self, command: _ClaimedCommand) -> None:
        provider = self._provider_registry.require(
            command.provider,
            command.resource.resource_kind,
        )
        status = await provider.get_status(
            command.capacity_reservation_id,
            command.resource,
            command.provider_metadata,
        )
        if status.state in {
            ProviderOperationState.pending,
            ProviderOperationState.unknown,
        }:
            self._clear(command, retry=True)
            return
        with self._session_factory() as db:
            if status.state is ProviderOperationState.succeeded:
                self._repository.transition(
                    db,
                    command.capacity_reservation_id,
                    SettlementRecordState.active.value,
                )
            else:
                self._provider_failures += 1
                self._repository.transition(
                    db,
                    command.capacity_reservation_id,
                    SettlementRecordState.failed.value,
                    failure_reason="provider_failed",
                    failure_message=status.detail,
                )
            self._repository.clear_claim(
                db,
                command.capacity_reservation_id,
                worker_id=self._worker_id,
            )
            db.commit()

    async def _recover_teardown_submission(
        self, command: _ClaimedCommand
    ) -> None:
        if command.prepared_teardown is None:
            raise ValueError("pending teardown has no prepared operation")
        provider = self._provider_registry.require(
            command.provider, command.resource.resource_kind
        )
        result = await provider.dispatch_teardown(command.prepared_teardown)
        with self._session_factory() as db:
            record = self._repository.get(db, command.capacity_reservation_id)
            if record is not None and record.state == (
                SettlementRecordState.teardown_failed.value
            ):
                self._repository.transition(
                    db,
                    command.capacity_reservation_id,
                    SettlementRecordState.teardown_dispatch_pending.value,
                )
            self._repository.transition(
                db,
                command.capacity_reservation_id,
                SettlementRecordState.tearing_down.value,
                teardown_provider_metadata=dict(result.provider_metadata),
            )
            self._repository.clear_claim(
                db,
                command.capacity_reservation_id,
                worker_id=self._worker_id,
            )
            db.commit()

    async def _recover_teardown_status(self, command: _ClaimedCommand) -> None:
        provider = self._provider_registry.require(
            command.provider, command.resource.resource_kind
        )
        status = await provider.get_status(
            command.capacity_reservation_id,
            command.resource,
            command.teardown_provider_metadata,
        )
        if status.state in {
            ProviderOperationState.pending,
            ProviderOperationState.unknown,
        }:
            self._clear(command, retry=True)
            return
        if status.state is ProviderOperationState.succeeded:
            if self._capacity_ledger_service is None:
                raise RuntimeError("capacity ledger is required for teardown convergence")
            released = self._capacity_ledger_service.release(
                capacity_reservation_id=command.capacity_reservation_id,
                owner_principal=command.owner_principal,
            )
            if released is None:
                raise RuntimeError("capacity reservation could not be released")
        with self._session_factory() as db:
            if status.state is ProviderOperationState.succeeded:
                self._repository.set_provisioned_resource_status(
                    db, command.capacity_reservation_id, "torn_down"
                )
                self._repository.transition(
                    db,
                    command.capacity_reservation_id,
                    SettlementRecordState.torn_down.value,
                )
            else:
                self._provider_failures += 1
                self._repository.transition(
                    db,
                    command.capacity_reservation_id,
                    SettlementRecordState.teardown_failed.value,
                    failure_reason="teardown_provider_failed",
                    failure_message=status.detail,
                )
            self._repository.clear_claim(
                db,
                command.capacity_reservation_id,
                worker_id=self._worker_id,
            )
            db.commit()

    def diagnostics(self) -> dict[str, object]:
        """Return safe counters and durable claim/lifecycle age metrics."""
        now = datetime.now(timezone.utc)
        terminal = {
            SettlementRecordState.active.value,
            SettlementRecordState.failed.value,
            SettlementRecordState.torn_down.value,
            SettlementRecordState.abandoned.value,
        }
        with self._session_factory() as db:
            all_rows = db.query(SettlementRecord).all()
        rows = [row for row in all_rows if row.state not in terminal]
        live_claims = 0
        stuck_claims = 0
        retrying = 0
        oldest_age = 0.0
        oldest_retry_age = 0.0
        for row in rows:
            created = row.created_at
            if created is not None:
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                oldest_age = max(oldest_age, (now - created).total_seconds())
        for row in all_rows:
            expires = row.claim_expires_at
            if expires is not None and expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if row.claimed_by is not None:
                if expires is not None and expires <= now:
                    stuck_claims += 1
                else:
                    live_claims += 1
            elif expires is not None and expires > now:
                retrying += 1
                updated = row.updated_at
                if updated is not None:
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    oldest_retry_age = max(
                        oldest_retry_age, (now - updated).total_seconds()
                    )
        return {
            "sweeps": self._sweeps,
            "claimed_total": self._claimed_total,
            "provider_failures": self._provider_failures,
            "last_sweep_at": (
                self._last_sweep_at.isoformat()
                if self._last_sweep_at is not None
                else None
            ),
            "live_claims": live_claims,
            "stuck_claims": stuck_claims,
            "retrying": retrying,
            "nonterminal": len(rows),
            "oldest_nonterminal_seconds": max(oldest_age, 0.0),
            "oldest_retry_seconds": max(oldest_retry_age, 0.0),
        }

    async def run_once(self) -> int:
        self._sweeps += 1
        self._last_sweep_at = datetime.now(timezone.utc)
        commands = self._claim()
        self._claimed_total += len(commands)
        for command in commands:
            try:
                if command.state == SettlementRecordState.dispatch_pending.value:
                    await self._recover_submission(command)
                elif command.state == SettlementRecordState.dispatching.value:
                    await self._recover_status(command)
                elif command.state in {
                    SettlementRecordState.teardown_dispatch_pending.value,
                    SettlementRecordState.teardown_failed.value,
                }:
                    await self._recover_teardown_submission(command)
                else:
                    await self._recover_teardown_status(command)
            except Exception:
                self._provider_failures += 1
                logger.exception(
                    "fulfillment recovery provider call failed",
                    extra={
                        "capacity_reservation_id": command.capacity_reservation_id,
                        "fulfillment_operation": command.state,
                        "provider": command.provider,
                        "resource_kind": command.resource.resource_kind,
                        "attempt_count": command.attempt_count,
                    },
                )
                try:
                    self._clear(command, retry=True)
                except Exception:
                    logger.exception(
                        "failed to release fulfillment recovery claim for %s",
                        command.capacity_reservation_id,
                    )
        return len(commands)

    async def run(self) -> None:
        while True:
            try:
                await self.run_once()
                await asyncio.sleep(self._poll_interval_seconds)
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("fulfillment recovery sweep failed")
                await asyncio.sleep(self._poll_interval_seconds)
