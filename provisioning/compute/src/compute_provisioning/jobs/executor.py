"""The contract between the job authority and whatever runs a job.

An executor is one complete executable: given a job's opaque parameters and the
host the job runs against, it runs the job and reports one outcome. It owns how
the job runs and what its output means; the job authority owns the job's
durable state. The split that follows from that:

- The executor decides whether a failure is retryable, because only it knows
  what the failure means. The job authority decides whether and when a retry
  happens, from a ``JobRetryPolicy``.
- The executor redacts everything it reports. Logs and outcomes reach durable
  state exactly as reported.
- The executor reports an opaque cancellation handle once it has one, and is
  later handed that same value to cancel the job. The job authority stores the
  handle without interpreting it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, Union

from compute_provisioning_contracts import CredentialEnvelope, ResultEnvelope
from pydantic import BaseModel, Field

from compute_provisioning.hosts.execution import ExecutionHost


class ProvisioningErrorEnvelope(BaseModel):
    """Why a job failed, as its executor classified it.

    ``retryable`` is the executor's judgement, the only one that knows what the
    failure means; whether and when a retry happens is the job authority's.
    """

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class JobRun:
    """One attempt at a job, as handed to its executor."""

    job_id: str
    offering_mode: str
    action: str
    host: ExecutionHost
    parameters: Mapping[str, Any]
    # Called once the executor can be cancelled, with the handle ``cancel``
    # will later receive.
    report_handle: Callable[[Mapping[str, Any]], None]
    # Called with the job's redacted output so far, as often as it changes.
    report_logs: Callable[[str], None]


@dataclass(frozen=True)
class JobSuccess:
    result: ResultEnvelope | None
    credentials: tuple[CredentialEnvelope, ...] = ()
    logs: str = ""


@dataclass(frozen=True)
class JobFailure:
    """An execution failure the executor anticipated and classified.

    ``error.retryable`` says whether running the job again could succeed; an
    executor raising instead reports a failure it did not anticipate, which is
    never retried.
    """

    error: ProvisioningErrorEnvelope
    logs: str = ""


JobOutcome = Union[JobSuccess, JobFailure]


class JobExecutor(Protocol):
    async def execute(self, run: JobRun) -> JobOutcome:
        """Run one attempt of a job and report its outcome."""

    async def cancel(self, handle: Mapping[str, Any]) -> None:
        """Request cancellation of the execution ``handle`` identifies.

        A handle whose execution has already ended is not an error.
        """


@dataclass(frozen=True)
class JobRetryPolicy:
    """How many times, and how often, a retryable failure is tried again."""

    default_max_retries: int = 3
    backoff_initial_seconds: float = 60.0
    backoff_multiplier: float = 2.0
    backoff_max_seconds: float = 3600.0

    def __post_init__(self) -> None:
        if self.default_max_retries < 0:
            raise ValueError("default_max_retries must not be negative")
        if self.backoff_initial_seconds < 0 or self.backoff_max_seconds < 0:
            raise ValueError("backoff durations must not be negative")
        if self.backoff_multiplier < 1:
            raise ValueError("backoff_multiplier must be at least 1")

    def delay_seconds(self, retry_count: int) -> int:
        """Seconds to wait before the retry following ``retry_count`` retries."""
        delay = self.backoff_initial_seconds * (self.backoff_multiplier ** retry_count)
        return min(int(delay), int(self.backoff_max_seconds))


__all__ = [
    "JobExecutor",
    "JobFailure",
    "JobOutcome",
    "JobRetryPolicy",
    "JobRun",
    "JobSuccess",
]
