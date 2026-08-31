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
    """Route release requests by reservation executor kind."""

    def __init__(
        self,
        executors: dict[str, ExecutorReleasePort],
    ) -> None:
        self._executors = dict(executors)

    async def submit_release(self, reservation: dict[str, Any]) -> str | None:
        executor_kind = reservation.get("executor_kind")
        executor = self._executors.get(str(executor_kind)) if executor_kind else None
        if executor is None:
            logger.warning(
                "[LEASE_LIFECYCLE] No release executor registered for executor_kind=%s",
                executor_kind,
            )
            return None
        return await executor.submit_release(reservation)


class ReleaseJobDispatcher:
    """Route release-job status reads by reservation executor kind.

    ``LeaseLifecycleService`` polls exactly one ``ReleaseJobPort`` today,
    even though what "job complete" means differs by executor kind:
    bare-metal submits one job to a shared job queue and polls it directly,
    while VM teardown is a durable, multi-step fulfillment aggregate with
    its own dispatch/convergence worker. This dispatcher keeps
    ``LeaseLifecycleService`` itself kind-agnostic -- it reads whichever
    port is registered for the reservation's ``executor_kind`` -- rather
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
        self, job_id: str, *, executor_kind: str | None = None
    ) -> Any:
        port = self._jobs.get(executor_kind)
        if port is None:
            raise LookupError(
                f"no release job port registered for executor_kind={executor_kind!r}"
            )
        return port.get_job(job_id)
