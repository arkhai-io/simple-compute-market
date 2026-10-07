"""Periodic convergence of durable fulfillment provider operations."""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from market_fulfillment.ids import derive_provisioned_resource_id
from market_fulfillment import (
    Backoff,
    ProviderOperationState,
    SettlementRecordState,
    SettlementResource,
)
from market_core import VersionedEnvelope
from market_fulfillment.provider import ProviderConfigInvalidError
from market_fulfillment.db import SettlementRecord
from market_fulfillment.settlement_repository import begin_sqlite_write_transaction
from market_site.db import CapacityReservation, ReservationState
from market_site.ledger import CapacityConflictError

from compute_provisioning.job_fulfillment import fulfillment_executor_target

# Reservations a lease target is never recorded on: their lease is over.
_TERMINAL_RESERVATION_STATES = (
    ReservationState.released.value,
    ReservationState.force_released.value,
    ReservationState.provisioning_failed.value,
)

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

    def __init__(self, *, session_factory, repository, provider_registry, settings,
                 worker_id: str | None = None, capacity_ledger=None) -> None:
        self._session_factory = session_factory
        self._repository = repository
        # The site ledger the lease's target is recorded on when a fulfillment
        # becomes active; ``None`` where no site is composed, which records none.
        self._capacity_ledger = capacity_ledger
        self._providers = provider_registry
        self._settings = settings
        self._worker_id = worker_id or f"fulfillment-watchdog:{uuid.uuid4()}"
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
        # Timer gate, mirroring `LeaseLifecycleService`. Without one this
        # watchdog was the only lifecycle loop a caller could not stop, so a
        # test driving convergence explicitly still had a 30s timer claiming
        # the same rows underneath it.
        self._resume_event = asyncio.Event()
        self._resume_event.set()

    def pause(self) -> None:
        """Stop timer-driven cycles; explicit cycles still run."""
        self._resume_event.clear()
        logger.info(
            "[FULFILLMENT_CONVERGENCE] Watchdog paused — timer cycles will block"
        )

    def resume(self) -> None:
        self._resume_event.set()
        logger.info("[FULFILLMENT_CONVERGENCE] Watchdog resumed")

    @property
    def is_paused(self) -> bool:
        return not self._resume_event.is_set()

    async def advance_cycle(self) -> dict[str, object]:
        """Run one cycle guaranteed to reach this worker's own claimed rows.

        `run_cycle` alone is an advance *attempt*, not an advance. A row this
        worker claimed and left claimed -- which is what the `pending`
        branches deliberately do, so that the claim lease acts as the
        inter-poll backoff -- is invisible to `claim_pending` until that lease
        lapses. The first lease is
        `fulfillment_convergence_backoff_initial_seconds` (5s) and doubles per
        claim, so a caller asking for "one more cycle" straight after a
        pending poll got a cycle that could not touch the row at all.

        Releasing this worker's own claims first makes the cycle deterministic
        for a caller that has already stopped the timer. Refused while the
        timer is live: the lease also keeps a second cycle off a row whose
        provider call is still in flight, and this worker's own timer loop
        shares its `worker_id`, so bypassing it unpaused could dispatch one
        operation twice.
        """
        if not self.is_paused:
            raise RuntimeError(
                "advance_cycle requires the convergence watchdog to be paused: "
                "releasing claim leases while timer cycles are live risks "
                "acting twice on one in-flight operation"
            )
        with self._session_factory() as db:
            released = self._repository.release_worker_claims(
                db, worker_id=self._worker_id
            )
            db.commit()
        if released:
            logger.info(
                "[FULFILLMENT_CONVERGENCE] Released %d own claim(s) for an "
                "explicit advance",
                released,
            )
        return await self.run_cycle()

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
                if not self._resume_event.is_set():
                    logger.debug(
                        "[FULFILLMENT_CONVERGENCE] Cycle blocked — watchdog is paused"
                    )
                    await self._resume_event.wait()
                await self.run_cycle()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("[FULFILLMENT_CONVERGENCE] Cancelled, shutting down")
                return
            except Exception:
                logger.exception("[FULFILLMENT_CONVERGENCE] Unhandled cycle error")
                await asyncio.sleep(interval)

    async def run_cycle(self) -> dict[str, object]:
        """Run one production convergence cycle and return bounded diagnostics.

        Timer-driven and operator-triggered cycles use this same method.  The
        returned snapshots contain only aggregate lifecycle counts and claim
        ages; prepared operations, provider payloads, and credentials are never
        included.
        """
        before = self.diagnostics_snapshot()
        await self.requeue_teardown_failures()
        await self.dispatch_pending_creates()
        await self.converge_creates()
        await self.dispatch_pending_teardowns()
        await self.converge_teardowns()
        lease_targets = self._reconcile_lease_targets_logged()
        after = self.diagnostics_snapshot()
        self._log_diagnostics(after, lease_targets=lease_targets)
        return {"before": before, "after": after}

    def diagnostics_snapshot(self) -> dict[str, object]:
        """Return bounded operator-facing recovery diagnostics."""
        with self._session_factory() as db:
            return self._repository.recovery_diagnostics(db).as_log_fields()

    async def requeue_teardown_failures(self) -> None:
        """Move retryable ``teardown_failed`` rows back to
        ``teardown_dispatch_pending`` so ``dispatch_pending_teardowns``
        picks them up on this or a later cycle.

        ``teardown_failed`` is documented (``openspec/specs/fulfillment/spec.md``,
        and the corresponding state comment in ``db.py``) as not terminal --
        recovery may retry teardown. That documentation was correct in
        intent but nothing actually performed the retry: no handler ever
        claimed ``teardown_failed`` rows. The transition table only allows
        ``teardown_failed -> teardown_dispatch_pending`` (not directly to
        ``tearing_down``), so this is a distinct requeue step, not an
        additional source state on ``dispatch_pending_teardowns``.
        """
        for record in self._claim(SettlementRecordState.teardown_failed):
            self._apply_transition(
                record.capacity_reservation_id,
                SettlementRecordState.teardown_failed.value,
                SettlementRecordState.teardown_dispatch_pending.value,
            )

    def reconcile_lease_targets(self) -> dict[str, object] | None:
        """Record the target of every active fulfillment whose lease lacks one.

        Activation records a lease's target in its own transaction, and a
        target its data prevents recording does not fail the activation. This
        sweep keeps trying: for each active fulfillment on a reservation whose
        lease is not over, a missing target is recorded wherever the write now
        succeeds, for instance after the reservation's data was corrected.
        What it cannot record, and each reservation that records a different
        target, is counted for the cycle's diagnostics; a recorded target is
        never replaced. Nothing acts on the site's recorded target, since
        teardown reads the fulfillment's own metadata, so these are reporting
        gaps rather than lifecycle faults.

        Returns the counts, or ``None`` where no site ledger is composed.
        """
        if self._capacity_ledger is None:
            return None
        repaired = 0
        different = 0
        unrecordable = {"metadata": 0, "reservation_refused": 0, "no_reservation": 0}
        with self._session_factory() as db:
            begin_sqlite_write_transaction(db)
            rows = db.execute(
                select(
                    SettlementRecord.capacity_reservation_id,
                    SettlementRecord.provider_metadata,
                    CapacityReservation.executor_target,
                    CapacityReservation.state,
                )
                .outerjoin(
                    CapacityReservation,
                    CapacityReservation.capacity_reservation_id
                    == SettlementRecord.capacity_reservation_id,
                )
                .where(SettlementRecord.state == SettlementRecordState.active.value)
            ).all()
            for reservation_id, metadata, recorded, reservation_state in rows:
                if reservation_state is None:
                    unrecordable["no_reservation"] += 1
                    continue
                if reservation_state in _TERMINAL_RESERVATION_STATES:
                    continue
                try:
                    target = fulfillment_executor_target(dict(metadata or {}))
                except ProviderConfigInvalidError:
                    unrecordable["metadata"] += 1
                    continue
                if recorded is not None:
                    if recorded != target:
                        different += 1
                    continue
                try:
                    self._capacity_ledger.record_executor_target_in_session(
                        db, reservation_id, target
                    )
                except CapacityConflictError:
                    unrecordable["reservation_refused"] += 1
                    continue
                repaired += 1
            db.commit()
        return {
            "repaired": repaired,
            "unrecordable": unrecordable,
            "different_target_recorded": different,
        }

    def _reconcile_lease_targets_logged(self) -> dict[str, object] | None:
        try:
            return self.reconcile_lease_targets()
        except Exception:  # noqa: BLE001
            # A reporting pass must not make lifecycle progress appear to
            # fail; the next cycle sweeps again.
            logger.exception("[FULFILLMENT_CONVERGENCE] lease target sweep failed")
            return None

    def _log_diagnostics(
        self,
        diagnostics: dict[str, object] | None = None,
        *,
        lease_targets: dict[str, object] | None = None,
    ) -> None:
        try:
            diagnostics = diagnostics or self.diagnostics_snapshot()
            extra: dict[str, object] = {
                "event": "fulfillment_recovery_diagnostics",
                "recovery_diagnostics": diagnostics,
            }
            if lease_targets is not None:
                extra["lease_targets"] = lease_targets
            logger.info("[FULFILLMENT_CONVERGENCE] recovery diagnostics", extra=extra)
        except Exception:  # noqa: BLE001
            # Observability must not make lifecycle progress appear to
            # fail: the four operational passes above already completed
            # for this cycle by the time this runs.
            logger.exception("[FULFILLMENT_CONVERGENCE] diagnostics query failed")

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
        """Claim one bounded batch in its own short write transaction.

        A lock-contention error here means another worker's outcome
        application is mid-transaction (holding the write reservation
        _with_owned_record now acquires up front) -- expected, occasional
        contention under the fix that closed the stale-outcome race, not a
        cycle-aborting failure. Treated the same as "no eligible rows this
        attempt": the next cycle tries again.
        """
        with self._session_factory() as db:
            try:
                return self._repository.claim_pending(
                    db,
                    states=(state.value,),
                    limit=self._limit,
                    lease_seconds=self._backoff.delay_seconds,
                    worker_id=self._worker_id,
                )
            except OperationalError:
                logger.debug(
                    "[FULFILLMENT_CONVERGENCE] claim contended for state=%s, "
                    "deferring to next cycle",
                    state.value,
                )
                return []

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
        offering_mode = requirements.get("offering_mode")
        if not offering_mode:
            raise ValueError(
                "scheduled settlement has no explicit offering_mode"
            )
        return SettlementResource(
            settlement_resource_id=record.settlement_resource_id,
            pool_id=record.pool_id,
            offering_mode=str(offering_mode),
            resource_kind=str(requirements.get("resource_kind") or "compute"),
            provider=record.provider,
            attributes=dict(record.resource_attributes or {}),
            host_id=record.resource_host_id,
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
        def apply(db) -> None:
            self._repository.transition(db, reservation_id, target_state, **updates)

        self._with_owned_record(reservation_id, expected_state, apply)

    def _apply_create_success(self, reservation_id: str, refs: tuple[str, ...]) -> None:
        def apply(db) -> None:
            record = self._repository.get(db, reservation_id)
            if record is None or record.fulfillment_id is None:
                raise LookupError(reservation_id)
            for provider_output_key in refs:
                provisioned_resource_id = derive_provisioned_resource_id(
                    identity_scope=f"fulfillment:{record.fulfillment_id}",
                    provider_output_key=provider_output_key,
                )
                self._repository.add_provisioned_resource(
                    db,
                    capacity_reservation_id=reservation_id,
                    provisioned_resource_id=provisioned_resource_id,
                )
            self._repository.transition(
                db, reservation_id, SettlementRecordState.active.value
            )
            self._record_executor_target(db, reservation_id, record.provider_metadata)

        self._with_owned_record(
            reservation_id,
            SettlementRecordState.dispatching.value,
            apply,
        )

    def _record_executor_target(
        self, db, reservation_id: str, provider_metadata: dict[str, Any] | None
    ) -> None:
        """Record on the lease what the fulfillment that just became active acts on.

        Written in the activation's own transaction and session: that
        transaction holds SQLite's single writer slot, so a second session
        would wait out the busy timeout instead.

        A target the data prevents recording (metadata naming no job-backed
        target, or a reservation the site refuses) keeps the activation: the
        workload exists, teardown addresses the target in the fulfillment's
        own metadata, and ``reconcile_lease_targets`` keeps trying and reports
        it. Any other failure escapes, so the activation rolls back and the
        record stays ``dispatching`` for the next cycle to activate. Neither
        the decoding nor the ledger raises after a write.
        """
        if self._capacity_ledger is None:
            return
        try:
            target = fulfillment_executor_target(dict(provider_metadata or {}))
            recorded = self._capacity_ledger.record_executor_target_in_session(
                db, reservation_id, target
            )
        except (ProviderConfigInvalidError, CapacityConflictError):
            logger.exception(
                "[FULFILLMENT] Could not record the executor target of reservation %s; "
                "convergence keeps trying",
                reservation_id,
            )
            return
        if recorded is not None and recorded.get("executor_target") != target:
            logger.warning(
                "[FULFILLMENT] Reservation %s already records executor target %r; "
                "its fulfillment acts on %r, which is left unrecorded",
                reservation_id,
                recorded.get("executor_target"),
                target,
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
        """Apply one outcome only while this worker still owns the claim.

        Acquires SQLite's write reservation (BEGIN IMMEDIATE) before reading
        and checking ownership, not after: a plain SELECT does not open a
        SQLite-level transaction on its own (pysqlite only begins one before
        a DML statement), so checking ownership first and writing later
        left a real, empirically-confirmed gap -- a worker whose lease had
        already been reclaimed by another worker could still commit its
        stale outcome on top of the new owner's claim, silently clearing it.
        Reserving the write lock first closes that gap: once reserved, no
        other worker's claim_pending() can commit a reclaim until this
        transaction resolves, so the ownership check and the writes that
        follow it observe a consistent view.
        """
        with self._session_factory() as db:
            begin_sqlite_write_transaction(db)
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
