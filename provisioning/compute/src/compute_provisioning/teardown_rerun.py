"""Whether a fulfillment's failed teardown is run again, and when.

A fulfillment's teardown is normally one job. A teardown job whose execution
never started — refused before its executor started anything that can act on
the host — left the host as it was, so running the teardown again under a new
job identity does exactly what the first should have. A teardown job whose
execution started, one that was cancelled, and one finished before starts were
recorded are not run again: what each did to the host is unknown, and an
operator verifies the host and force-releases it.

Rerun *n* is the reservation's *n*-th teardown job after its first, submitted
once the previous job has been finished for the job retry policy's delay after
*n* − 1 retries, up to ``teardown_rerun_limit`` reruns. One predicate,
:func:`teardown_rerun`, answers from every teardown job bound to the
reservation; dispatch acts on it, and the lease's release status reads it, so
the two cannot disagree about whether a rerun is pending. See the
physical-provisioning specification, "A teardown that never started is run
again under a new job identity, within a bound".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Union

from compute_provisioning.jobs.db import JobStatus
from compute_provisioning.jobs.engine import BoundJob
from compute_provisioning.jobs.executor import JobRetryPolicy


@dataclass(frozen=True)
class TeardownRerunPolicy:
    """How many times a never-started teardown is run again, and how often.

    ``teardown_rerun_limit`` bounds the reruns after a teardown's first job; 0
    disables them. The spacing is the job retry policy's, so a teardown waits
    between its reruns as a job waits between its retries.
    """

    teardown_rerun_limit: int
    retry_policy: JobRetryPolicy

    def __post_init__(self) -> None:
        if self.teardown_rerun_limit < 0:
            raise ValueError(
                "teardown_rerun_limit must not be negative "
                f"(got {self.teardown_rerun_limit}); 0 disables teardown reruns"
            )

    def delay_seconds(self, rerun: int) -> int:
        """Seconds rerun ``rerun`` waits after the previous teardown job finished."""
        return self.retry_policy.delay_seconds(rerun - 1)


NotRerunnableReason = Literal[
    "no_teardown_job",
    "cancelled",
    "started",
    "finished_before_starts_recorded",
    "reruns_disabled",
]


@dataclass(frozen=True)
class NotRerunnable:
    """No rerun will be run: the latest teardown job is not a never-started
    failure, or reruns are disabled."""

    reason: NotRerunnableReason
    reruns_spent: int


@dataclass(frozen=True)
class LatestJobUnsettled:
    """The latest teardown job has not failed — it is queued, running, or
    succeeded — so the teardown is still to be observed, and nothing is rerun."""

    status: str


@dataclass(frozen=True)
class RerunWaiting:
    """Rerun ``rerun`` is due at ``until``."""

    rerun: int
    until: datetime


@dataclass(frozen=True)
class RerunReady:
    """Rerun ``rerun`` may be submitted now."""

    rerun: int


@dataclass(frozen=True)
class RerunsSpent:
    """Every rerun the limit allows has been run, and the latest never started."""

    reruns_spent: int


RerunOutcome = Union[NotRerunnable, LatestJobUnsettled, RerunWaiting, RerunReady, RerunsSpent]


def teardown_rerun(
    jobs: Sequence[BoundJob], policy: TeardownRerunPolicy, now: datetime
) -> RerunOutcome:
    """Whether a reservation's teardown is run again, from its teardown jobs.

    ``jobs`` is every teardown job bound to the reservation, oldest first, so
    the latest decides; ``now`` is the process time source's instant.
    """
    if not jobs:
        return NotRerunnable("no_teardown_job", 0)
    latest = jobs[-1]
    spent = len(jobs) - 1
    if latest.status == JobStatus.cancelled.value:
        return NotRerunnable("cancelled", spent)
    if latest.status != JobStatus.failed.value:
        return LatestJobUnsettled(latest.status)
    if not latest.never_started:
        if latest.finished_at is None:
            return NotRerunnable("finished_before_starts_recorded", spent)
        return NotRerunnable("started", spent)
    if policy.teardown_rerun_limit == 0:
        return NotRerunnable("reruns_disabled", spent)
    rerun = len(jobs)
    if rerun > policy.teardown_rerun_limit:
        return RerunsSpent(spent)
    # A never-started job records its finish, so ``finished_at`` is set here.
    until = latest.finished_at + timedelta(seconds=policy.delay_seconds(rerun))
    if now < until:
        return RerunWaiting(rerun, until)
    return RerunReady(rerun)


def rerun_pending(outcome: RerunOutcome) -> bool:
    """Whether the teardown still has something to try: a rerun is waiting or
    ready, or its latest job has not failed and is yet to be observed."""
    return isinstance(outcome, (LatestJobUnsettled, RerunWaiting, RerunReady))


def never_started_account(outcome: RerunOutcome, policy: TeardownRerunPolicy) -> str | None:
    """What an operator reads of a never-started teardown no rerun will retry;
    ``None`` when the latest teardown job's execution started or is unknown."""
    if isinstance(outcome, RerunsSpent):
        return (
            "the teardown's execution never started, and "
            f"{outcome.reruns_spent} rerun(s) were spent; teardown_rerun_limit is "
            f"{policy.teardown_rerun_limit}"
        )
    if isinstance(outcome, NotRerunnable) and outcome.reason == "reruns_disabled":
        return (
            "the teardown's execution never started, and teardown reruns are "
            "disabled (teardown_rerun_limit is 0)"
        )
    return None


__all__ = [
    "LatestJobUnsettled",
    "NotRerunnable",
    "NotRerunnableReason",
    "RerunOutcome",
    "RerunReady",
    "RerunWaiting",
    "RerunsSpent",
    "TeardownRerunPolicy",
    "never_started_account",
    "rerun_pending",
    "teardown_rerun",
]
