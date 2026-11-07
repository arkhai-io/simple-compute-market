"""Wire models of the provisioning service's health, status, version, worker
control, and identity rotation routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from market_core import VersionedEnvelope
from market_identity import Identity
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Local liveness: the checks a probe can afford, with no outbound call."""

    status: str = Field(description="'ok' when all checks pass, 'degraded' otherwise")
    checks: dict[str, str] = Field(description="Per-subsystem status strings")


class ExecutorStatus(BaseModel):
    """Whether the executors composed for one offering mode are the mock."""

    offering_mode: str
    mocked: bool


class ExecutionStatus(BaseModel):
    """What runs provisioning jobs, as composed.

    ``mocked`` is true only when executors are composed and every one of them
    is the mock, so a deployment that would run real work never reports it.
    """

    mocked: bool
    executors: list[ExecutorStatus] = Field(default_factory=list)


class SystemStatusComponent(BaseModel):
    """One contributed readiness component.

    ``detail`` is the contributing implementation's own payload, identified by
    its kind and schema version so a reader recognizes it before reading it.
    """

    name: str = Field(min_length=1)
    ready: bool
    detail: VersionedEnvelope[dict[str, Any]]


class SystemStatusResponse(BaseModel):
    """Operational status: reachability, workers, contract, and execution.

    ``checks.execution`` is ``ok`` when every component is ready and
    ``degraded`` otherwise; a degraded status is answered with 503 and this
    same body.
    """

    status: str = Field(description="'ok' when all checks pass, 'degraded' otherwise")
    checks: dict[str, str] = Field(description="Per-subsystem status strings")
    #: The storefront-to-provisioning contract major this service speaks, and
    #: the majors it admits. A cutover requires every participant to report
    #: its pin before mutations resume, and this is the only way to ask a
    #: running service for it.
    provisioning_contract_version: str = Field(
        description="Contract major.minor this service speaks"
    )
    provisioning_contract_supported_majors: list[int] = Field(
        description="Contract majors this service admits"
    )
    execution: ExecutionStatus
    components: list[SystemStatusComponent] = Field(default_factory=list)

    def component(self, name: str) -> SystemStatusComponent | None:
        """The component named ``name``, or ``None`` when none is reported."""
        return next((c for c in self.components if c.name == name), None)


class VersionResponse(BaseModel):
    version: str = Field(description="Service version string")
    active_profiles: list[str] = Field(
        description="Dynaconf profiles currently active (from ACTIVE_PROFILES env var)"
    )


class WorkerPauseResponse(BaseModel):
    """A timer-driven worker's pause state, as its pause and resume routes answer.

    ``paused`` is whether the timer is held. ``at_gate`` is whether the worker
    is held at its gate with no timer cycle running, so none can run until it
    is resumed: a cycle that began before the pause finishes first, and a
    caller that needs the worker held repeats the pause until this is true.
    """

    paused: bool
    at_gate: bool


class LeaseCheckResponse(BaseModel):
    """What one lease lifecycle cycle did, as ``check-leases`` answers.

    ``checked`` leases began releasing; ``released`` and ``release_failed``
    count the releases that completed or failed; ``skipped`` counts leases the
    cycle left as they were.
    """

    checked: int = Field(ge=0)
    released: int = Field(ge=0)
    release_failed: int = Field(ge=0)
    skipped: int = Field(ge=0)


class ConvergenceStateCounts(BaseModel):
    """Recovery health for one non-terminal fulfillment state."""

    total: int = Field(ge=0)
    actively_claimed: int = Field(ge=0)
    expired_claims: int = Field(ge=0)
    oldest_row_age_seconds: float | None = None
    max_attempt_count: int = Field(ge=0)


class ConvergenceDiagnostics(BaseModel):
    """Bounded fulfillment-convergence diagnostics: counts and ages only,
    never a prepared operation, provider payload, or credential."""

    per_state: dict[str, ConvergenceStateCounts]
    failed_count: int = Field(ge=0)
    teardown_failed_count: int = Field(ge=0)


class ConvergenceCycleResponse(BaseModel):
    """One fulfillment-convergence cycle, as ``run-cycle`` and
    ``advance-cycle`` answer: the diagnostics before and after it."""

    before: ConvergenceDiagnostics
    after: ConvergenceDiagnostics


class PrincipalRotationResponse(BaseModel):
    """A trusted caller principal's rotation, as the rotation route answers.

    ``replacement`` is trusted from ``generation`` on; the principal it
    replaces stays trusted until ``current_valid_until``.
    """

    role: Literal["admin", "seller"]
    generation: int = Field(ge=1)
    current_valid_until: datetime
    replacement: Identity


__all__ = [
    "ConvergenceCycleResponse",
    "ConvergenceDiagnostics",
    "ConvergenceStateCounts",
    "ExecutionStatus",
    "ExecutorStatus",
    "HealthResponse",
    "LeaseCheckResponse",
    "PrincipalRotationResponse",
    "SystemStatusComponent",
    "SystemStatusResponse",
    "VersionResponse",
    "WorkerPauseResponse",
]
