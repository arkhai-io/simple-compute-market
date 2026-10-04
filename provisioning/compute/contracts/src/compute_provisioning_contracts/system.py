"""Wire models of the provisioning service's aggregate health and version routes."""

from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = Field(description="'ok' when all checks pass, 'degraded' otherwise")
    checks: dict[str, str] = Field(description="Per-subsystem status strings")
    #: The storefront-to-provisioning contract major this service speaks, and
    #: the majors it admits. A cutover requires every participant to report
    #: its pin before mutations resume, and this is the only way to ask a
    #: running service for it.
    #:
    #: Declared here because this model governs what the route emits: a field
    #: the service puts in its status dict but this model does not name is
    #: dropped before any caller sees it. Optional so `GET /health`, which
    #: shares the model and reports neither, stays valid.
    provisioning_contract_version: str | None = Field(
        default=None,
        description="Contract major.minor this service speaks (status only)",
    )
    provisioning_contract_supported_majors: list[int] | None = Field(
        default=None,
        description="Contract majors this service admits (status only)",
    )


class VersionResponse(BaseModel):
    version: str = Field(description="Service version string")
    active_profiles: list[str] = Field(
        description="Dynaconf profiles currently active (from ACTIVE_PROFILES env var)"
    )


__all__ = ["HealthResponse", "VersionResponse"]
