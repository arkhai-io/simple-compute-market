"""Wire models of the provisioning service's health, status, and version routes."""

from __future__ import annotations

from typing import Any

from market_core import VersionedEnvelope
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


__all__ = [
    "ExecutionStatus",
    "ExecutorStatus",
    "HealthResponse",
    "SystemStatusComponent",
    "SystemStatusResponse",
    "VersionResponse",
]
