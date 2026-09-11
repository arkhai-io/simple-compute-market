"""Executor-neutral release port and kind-based dispatcher."""

from __future__ import annotations

import logging
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class ExecutorReleasePort(Protocol):
    async def submit_release(self, reservation: dict[str, Any]) -> str | None:
        """Submit release work for an reservation and return its job id."""


class ReleaseJobPort(Protocol):
    def get_job(self, job_id: str) -> Any:
        """Read the current outcome of a previously submitted release job."""

class ExecutorReleaseDispatcher:
    """Route release requests by reservation offering mode."""

    def __init__(
        self,
        executors: dict[str, ExecutorReleasePort],
    ) -> None:
        self._executors = dict(executors)

    async def submit_release(self, reservation: dict[str, Any]) -> str | None:
        offering_mode = reservation.get("offering_mode")
        executor = self._executors.get(str(offering_mode)) if offering_mode else None
        if executor is None:
            logger.warning(
                "[LEASE_LIFECYCLE] No release executor registered for offering_mode=%s",
                offering_mode,
            )
            return None
        return await executor.submit_release(reservation)


class ReleaseJobDispatcher:
    """Route release-job status reads by reservation offering mode.

    ``LeaseLifecycleService`` polls exactly one ``ReleaseJobPort`` today,
    even though what "job complete" means differs by offering mode:
    bare-metal submits one job to a shared job queue and polls it directly,
    while VM teardown is a durable, multi-step fulfillment aggregate with
    its own dispatch/convergence worker. This dispatcher keeps
    ``LeaseLifecycleService`` itself kind-agnostic -- it reads whichever
    port is registered for the reservation's ``offering_mode`` -- rather
    than teaching the generic lease-lifecycle machinery either shape
    directly. Mirrors ``ExecutorReleaseDispatcher``'s existing
    submission-side routing.
    """

    def __init__(
        self,
        jobs: dict[str, ReleaseJobPort],
    ) -> None:
        self._jobs = dict(jobs)

    def get_job(
        self, job_id: str, *, offering_mode: str | None = None
    ) -> Any:
        port = self._jobs.get(offering_mode)
        if port is None:
            raise LookupError(
                f"no release job port registered for offering_mode={offering_mode!r}"
            )
        return port.get_job(job_id)
