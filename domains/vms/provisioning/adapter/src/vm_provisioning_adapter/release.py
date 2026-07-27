"""VM release adapter for leased site reservations.

Submission and completion polling are split across two different owners.
This module only submits: it resolves the durable fulfillment aggregate for
a reservation and asks it to begin teardown. `FulfillmentConvergenceWatchdog`
(``compute_provisioning_service.services.fulfillment_convergence``) owns
everything from there -- dispatch, retry, and status convergence through to
``torn_down``/``teardown_failed``. Completion is read back through
``VmFulfillmentReleaseJobPort`` (``release_job_port.py``), not by polling an
Ansible job the way this module used to submit one directly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from market_fulfillment import SettlementEntityNotFoundError, SettlementRecordState

logger = logging.getLogger(__name__)
VM_EXECUTOR_KIND = "vm"


class VmReleaseExecutor:
    """Initiates durable fulfillment teardown for a leased VM reservation.

    Resolution only: this class does not perform provider I/O itself and
    does not wait for teardown to finish. ``LeaseLifecycleService`` treats
    its return value as a job id to poll later through a
    ``ReleaseJobPort`` -- here, that id is the durable ``fulfillment_id``,
    resolved by ``VmFulfillmentReleaseJobPort.get_job`` against the
    fulfillment aggregate's own teardown state, not against a job queue.
    """

    def __init__(
        self,
        *,
        settlement_repository,
        session_factory: Callable[[], Any],
        fulfillment_service_provider: Callable[[], Any],
    ) -> None:
        self._settlement_repository = settlement_repository
        self._session_factory = session_factory
        self._fulfillment_service_provider = fulfillment_service_provider

    async def submit_release(self, reservation: dict[str, Any]) -> str | None:
        capacity_reservation_id = reservation.get("capacity_reservation_id")
        if not capacity_reservation_id:
            logger.warning(
                "[LEASE_LIFECYCLE] Reservation has no capacity_reservation_id; "
                "cannot resolve a fulfillment to tear down"
            )
            return None

        fulfillment_id = self._resolve_fulfillment_id(capacity_reservation_id)
        if fulfillment_id is None:
            logger.warning(
                "[LEASE_LIFECYCLE] No fulfillment aggregate found for reservation "
                "%s; cannot begin teardown",
                capacity_reservation_id,
            )
            return None

        try:
            fulfillment_service = self._fulfillment_service_provider()
            acceptance = await fulfillment_service.begin_fulfillment_teardown(
                fulfillment_id
            )
            return acceptance.fulfillment_id
        except Exception as exc:
            logger.warning(
                "[LEASE_LIFECYCLE] Failed to begin fulfillment teardown for %s "
                "(fulfillment_id=%s): %s",
                capacity_reservation_id,
                fulfillment_id,
                exc,
            )
            return None

    def _resolve_fulfillment_id(self, capacity_reservation_id: str) -> str | None:
        with self._session_factory() as db:
            record = self._settlement_repository.get(db, capacity_reservation_id)
            return record.fulfillment_id if record is not None else None


@dataclass(frozen=True)
class _FulfillmentReleaseJob:
    """The subset of job-status shape ``LeaseLifecycleService`` reads.

    Matches the informal ``status``/``error`` interface the shared job
    queue's own job objects already expose (``ReleaseJobPort``), so
    ``LeaseLifecycleService``'s polling loop needs no VM-specific branch.
    """

    status: str
    error: str | None = None


class VmFulfillmentReleaseJobPort:
    """Answers release-job status reads from the fulfillment aggregate's
    own teardown state, not a polled Ansible job.

    ``job_id`` here is a durable ``fulfillment_id``, the value
    ``VmReleaseExecutor.submit_release`` returns. Terminal
    ``torn_down``/``teardown_failed`` map to ``succeeded``/``failed``;
    every other state (including the aggregate not existing yet, which
    cannot happen for a job id this port itself produced, but is handled
    rather than assumed impossible) is reported as still running so the
    caller keeps polling.
    """

    def __init__(self, fulfillment_service_provider: Callable[[], Any]) -> None:
        self._fulfillment_service_provider = fulfillment_service_provider

    def get_job(self, job_id: str) -> Any:
        fulfillment_service = self._fulfillment_service_provider()
        try:
            status = fulfillment_service.get_fulfillment_status(job_id)
        except SettlementEntityNotFoundError:
            return _FulfillmentReleaseJob(
                status="failed", error=f"no fulfillment {job_id!r}"
            )

        if status.state == SettlementRecordState.torn_down.value:
            return _FulfillmentReleaseJob(status="succeeded")
        if status.state == SettlementRecordState.teardown_failed.value:
            return _FulfillmentReleaseJob(
                status="failed",
                error=status.failure_message or status.failure_reason or "teardown failed",
            )
        return _FulfillmentReleaseJob(status="running")
