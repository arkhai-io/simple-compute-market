"""Periodic convergence of durable fulfillment provider operations."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from market_fulfillment import (
    Backoff,
    ProviderOperationState,
    SettlementRecordState,
    SettlementResource,
    VersionedEnvelope,
)
from market_fulfillment.provider import ProviderConfigInvalidError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DispatchPlan:
    source_state: SettlementRecordState
    target_state: SettlementRecordState
    prepared_field: str
    provider_method: str
    metadata_field: str


class FulfillmentConvergenceWatchdog:
    """Claim durable work, perform provider I/O, and commit guarded outcomes."""

    def __init__(self, *, session_factory, repository, provider_registry, settings) -> None:
        self._session_factory = session_factory
        self._repository = repository
        self._providers = provider_registry
        self._settings = settings
        self._worker_id = f"fulfillment-watchdog:{uuid.uuid4()}"
        self._limit = int(getattr(settings, "fulfillment_convergence_batch_size", 50))
        self._backoff = Backoff(
            initial_seconds=float(
                getattr(settings, "fulfillment_convergence_backoff_initial_seconds", 5.0)
            ),
            multiplier=float(
                getattr(settings, "fulfillment_convergence_backoff_multiplier", 2.0)
            ),
            max_seconds=float(
                getattr(settings, "fulfillment_convergence_backoff_max_seconds", 300.0)
            ),
            jitter_fraction=float(
                getattr(settings, "fulfillment_convergence_backoff_jitter_fraction", 0.1)
            ),
        )

    async def run(self) -> None:
        interval = float(
            getattr(
                self._settings,
                "fulfillment_convergence_watchdog_poll_interval_seconds",
                30,
            )
        )
        logger.info("[FULFILLMENT_CONVERGENCE] Started (interval=%ss)", interval)
        while True:
            try:
                await self.run_cycle()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("[FULFILLMENT_CONVERGENCE] Cancelled, shutting down")
                return
            except Exception:
                logger.exception("[FULFILLMENT_CONVERGENCE] Unhandled cycle error")
                await asyncio.sleep(interval)

    async def run_cycle(self) -> None:
        await self.dispatch_pending_creates()
        await self.converge_creates()
        await self.dispatch_pending_teardowns()
        await self.converge_teardowns()
        self._log_diagnostics()

    def _log_diagnostics(self) -> None:
        with self._session_factory() as db:
            diagnostics = self._repository.recovery_diagnostics(db)
        logger.info("[FULFILLMENT_CONVERGENCE] diagnostics: %s", diagnostics)

    async def dispatch_pending_creates(self) -> None:
        await self._dispatch_claimed_records(
            _DispatchPlan(
                source_state=SettlementRecordState.dispatch_pending,
                target_state=SettlementRecordState.dispatching,
                prepared_field="prepared_create_operation",
                provider_method="dispatch_create",
                metadata_field="provider_metadata",
            )
        )

    async def dispatch_pending_teardowns(self) -> None:
        await self._dispatch_claimed_records(
            _DispatchPlan(
                source_state=SettlementRecordState.teardown_dispatch_pending,
                target_state=SettlementRecordState.tearing_down,
                prepared_field="prepared_teardown_operation",
                provider_method="dispatch_teardown",
                metadata_field="teardown_provider_metadata",
            )
        )

    async def converge_creates(self) -> None:
        for record in self._claim(SettlementRecordState.dispatching):
            await self._converge_create_record(record)

    async def converge_teardowns(self) -> None:
        for record in self._claim(SettlementRecordState.tearing_down):
            await self._converge_teardown_record(record)

    def _claim(self, state: SettlementRecordState):
        """Claim one bounded batch in its own short write transaction."""
        with self._session_factory() as db:
            return self._repository.claim_pending(
                db,
                states=(state.value,),
                limit=self._limit,
                lease_seconds=self._backoff.delay_seconds,
                worker_id=self._worker_id,
            )

    async def _dispatch_claimed_records(self, plan: _DispatchPlan) -> None:
        for record in self._claim(plan.source_state):
            await self._dispatch_record(record, plan)

    async def _dispatch_record(self, record, plan: _DispatchPlan) -> None:
        try:
            provider = self._providers.require(record.provider)
            prepared = self._prepared_operation(record, plan.prepared_field)
            result = await getattr(provider, plan.provider_method)(prepared)
            self._apply_transition(
                record.capacity_reservation_id,
                plan.source_state.value,
                plan.target_state.value,
                **{plan.metadata_field: dict(result.provider_metadata)},
            )
        except Exception as exc:
            self._log_retry(plan.provider_method, record.capacity_reservation_id, exc)

    async def _converge_create_record(self, record) -> None:
        try:
            status = await self._provider_status(record, "provider_metadata")
            if status.state is ProviderOperationState.pending:
                return
            if status.state is ProviderOperationState.succeeded:
                provider = self._providers.require(record.provider)
                try:
                    refs = provider.resolve_provisioned_resources(
                        dict(record.provider_metadata or {})
                    )
                except ProviderConfigInvalidError as exc:
                    # The provider reported success but persisted metadata
                    # cannot be resolved to a resource identity. This is not
                    # retryable: the metadata that failed to resolve is
                    # already durable and will not change on the next cycle,
                    # so falling through to the general retry path below
                    # would back off forever behind diagnostics
                    # indistinguishable from a healthy in-progress row,
                    # never actually converging. Applied directly, not via
                    # _apply_provider_failure, since this is a distinct
                    # failure category from a provider-reported failure --
                    # ours, not the provider's -- and needs its own
                    # failure_reason for operator diagnostics.
                    self._apply_transition(
                        record.capacity_reservation_id,
                        SettlementRecordState.dispatching.value,
                        SettlementRecordState.failed.value,
                        failure_reason="invalid_provisioned_resource_metadata",
                        failure_message=str(exc),
                    )
                    return
                self._apply_create_success(record.capacity_reservation_id, refs)
                return
            if status.state is ProviderOperationState.failed:
                self._apply_provider_failure(
                    record.capacity_reservation_id,
                    SettlementRecordState.dispatching,
                    SettlementRecordState.failed,
                    status.detail,
                )
        except Exception as exc:
            self._log_retry("create status", record.capacity_reservation_id, exc)

    async def _converge_teardown_record(self, record) -> None:
        try:
            status = await self._provider_status(record, "teardown_provider_metadata")
            if status.state is ProviderOperationState.pending:
                return
            if status.state is ProviderOperationState.succeeded:
                self._apply_teardown_success(record.capacity_reservation_id)
                return
            if status.state is ProviderOperationState.failed:
                self._apply_provider_failure(
                    record.capacity_reservation_id,
                    SettlementRecordState.tearing_down,
                    SettlementRecordState.teardown_failed,
                    status.detail,
                )
        except Exception as exc:
            self._log_retry("teardown status", record.capacity_reservation_id, exc)

    async def _provider_status(self, record, metadata_field: str):
        provider = self._providers.require(record.provider)
        return await provider.get_status(
            record.capacity_reservation_id,
            self._settlement_resource(record),
            dict(getattr(record, metadata_field) or {}),
        )

    @staticmethod
    def _prepared_operation(record, field_name: str) -> VersionedEnvelope:
        value = getattr(record, field_name)
        if value is None:
            raise ValueError(
                f"{field_name} is missing for capacity reservation "
                f"{record.capacity_reservation_id!r}"
            )
        return VersionedEnvelope.model_validate(value)

    @staticmethod
    def _settlement_resource(record) -> SettlementResource:
        requirements = dict(record.scheduling_requirements or {})
        return SettlementResource(
            settlement_resource_id=record.settlement_resource_id,
            pool_id=record.pool_id,
            resource_kind=str(requirements.get("resource_kind") or "compute"),
            provider=record.provider,
            attributes=dict(record.resource_attributes or {}),
        )

    def _apply_provider_failure(
        self,
        reservation_id: str,
        source_state: SettlementRecordState,
        target_state: SettlementRecordState,
        detail: str | None,
    ) -> None:
        self._apply_transition(
            reservation_id,
            source_state.value,
            target_state.value,
            failure_reason="provider_reported_failure",
            failure_message=detail,
        )

    def _apply_transition(
        self,
        reservation_id: str,
        expected_state: str,
        target_state: str,
        **updates: Any,
    ) -> None:
        self._with_owned_record(
            reservation_id,
            expected_state,
            lambda db: self._repository.transition(
                db, reservation_id, target_state, **updates
            ),
        )

    def _apply_create_success(self, reservation_id: str, refs: tuple[str, ...]) -> None:
        def apply(db) -> None:
            for ref in refs:
                self._repository.add_provisioned_resource(
                    db,
                    capacity_reservation_id=reservation_id,
                    domain_resource_ref=ref,
                )
            self._repository.transition(
                db, reservation_id, SettlementRecordState.active.value
            )

        self._with_owned_record(
            reservation_id,
            SettlementRecordState.dispatching.value,
            apply,
        )

    def _apply_teardown_success(self, reservation_id: str) -> None:
        def apply(db) -> None:
            self._repository.mark_provisioned_resources_torn_down(db, reservation_id)
            self._repository.transition(
                db, reservation_id, SettlementRecordState.torn_down.value
            )

        self._with_owned_record(
            reservation_id,
            SettlementRecordState.tearing_down.value,
            apply,
        )

    def _with_owned_record(
        self,
        reservation_id: str,
        expected_state: str,
        apply: Callable[[Any], None],
    ) -> bool:
        """Apply one outcome only while this worker still owns the claim."""
        with self._session_factory() as db:
            record = self._repository.get(db, reservation_id)
            if (
                record is None
                or record.state != expected_state
                or record.claimed_by != self._worker_id
            ):
                return False
            apply(db)
            self._repository.clear_claim(
                db, reservation_id, worker_id=self._worker_id
            )
            db.commit()
            return True

    @staticmethod
    def _log_retry(operation: str, reservation_id: str, exc: Exception) -> None:
        logger.warning(
            "[FULFILLMENT_CONVERGENCE] %s retry deferred for %s: %s",
            operation,
            reservation_id,
            exc,
        )
