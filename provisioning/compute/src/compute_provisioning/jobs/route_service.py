"""The job authority's routes, without a web framework.

``JobRouteService`` validates and performs the operator job routes and shapes
their responses; ``JobTestRouteService`` serves the job observation routes a
mock-profile deployment mounts for tests. Each reports a refusal as a
``ProvisioningRouteError`` that the service's binding turns into a response.
"""

from __future__ import annotations

import asyncio
from typing import Any

from compute_provisioning_contracts import (
    JobCredentialsResponse,
    JobListResponse,
    JobLogsResponse,
    JobStatusResponse,
)

from compute_provisioning.jobs.engine import JobEngine
from compute_provisioning.route_errors import ProvisioningRouteError

#: The statuses after which a job changes no more.
TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
_SORTS = frozenset({"created_at_asc", "created_at_desc"})

# How many jobs the observation routes read at once: a test deployment's whole
# history, not a page of production traffic.
_OBSERVATION_LIMIT = 1000


def _not_found(exc: LookupError) -> ProvisioningRouteError:
    return ProvisioningRouteError(404, str(exc))


class JobRouteService:
    def __init__(self, engine: JobEngine) -> None:
        self._engine = engine

    def list_jobs(
        self,
        *,
        offset: int = 0,
        limit: int = 20,
        status: str | None = None,
        sort: str = "created_at_desc",
        escrow_uid: str | None = None,
    ) -> JobListResponse:
        if offset < 0 or not 1 <= limit <= 100:
            raise ProvisioningRouteError(422, "offset must be >= 0 and limit between 1 and 100")
        if sort not in _SORTS:
            raise ProvisioningRouteError(422, f"sort must be one of {sorted(_SORTS)}")
        return self._engine.list_jobs(
            offset=offset, limit=limit, status_filter=status, sort=sort, escrow_uid=escrow_uid
        )

    def get_job(self, job_id: str) -> JobStatusResponse:
        try:
            return self._engine.get_job(job_id)
        except LookupError as exc:
            raise _not_found(exc) from exc

    def get_credentials(self, job_id: str) -> JobCredentialsResponse:
        try:
            return self._engine.get_credentials(job_id)
        except LookupError as exc:
            raise _not_found(exc) from exc

    def get_logs(self, job_id: str) -> JobLogsResponse:
        try:
            return self._engine.get_logs(job_id)
        except LookupError as exc:
            raise _not_found(exc) from exc

    async def cancel_job(self, job_id: str) -> dict[str, Any]:
        """Cancel a queued or running job; a running job's executor is asked to stop."""
        try:
            return await self._engine.cancel_job(job_id)
        except LookupError as exc:
            raise _not_found(exc) from exc


class JobTestRouteService:
    """Job observation for tests, mounted only under the mock profile."""

    def __init__(self, engine: JobEngine) -> None:
        self._engine = engine

    def _counts(self) -> tuple[dict[str, int], int]:
        result = self._engine.list_jobs(limit=_OBSERVATION_LIMIT)
        counts: dict[str, int] = {}
        for job in result.jobs:
            counts[job.status] = counts.get(job.status, 0) + 1
        return counts, result.total

    def summary(self) -> dict[str, Any]:
        """Counts of jobs by status: a non-blocking diagnostic snapshot."""
        counts, total = self._counts()
        terminal = sum(n for status, n in counts.items() if status in TERMINAL_STATUSES)
        return {
            "counts": counts,
            "total": total,
            "total_terminal": terminal,
            "total_active": sum(counts.values()) - terminal,
        }

    async def drain(self, timeout: float) -> dict[str, Any]:
        """Return once every job is terminal; refuse with 408 at the deadline.

        A drain watches jobs this process may not be running, so it re-reads
        their durable state rather than waiting on an in-process signal.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            counts, _total = self._counts()
            active = sum(n for status, n in counts.items() if status not in TERMINAL_STATUSES)
            if not active:
                return {"drained": True, "counts": counts}
            remaining = deadline - loop.time()
            if remaining <= 0:
                raise ProvisioningRouteError(
                    408, f"Drain timed out: {active} job(s) still active after {timeout}s"
                )
            await asyncio.sleep(min(0.25, remaining))

    async def wait(self, job_id: str, timeout: float) -> dict[str, Any]:
        """A job's final status once terminal; 404 if it never existed, 408 at the deadline."""
        try:
            job = await self._engine.wait_for_terminal(job_id, timeout)
        except LookupError as exc:
            raise ProvisioningRouteError(404, f"Job {job_id!r} not found") from exc
        except TimeoutError as exc:
            raise ProvisioningRouteError(408, str(exc)) from exc
        return {
            "job_id": job_id,
            "status": job.status,
            "result": job.result.model_dump(mode="json") if job.result is not None else None,
            "error": job.error,
        }


__all__ = ["JobRouteService", "JobTestRouteService", "TERMINAL_STATUSES"]
