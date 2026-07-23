"""Executor-neutral resource-pool wire models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PoolCreate(BaseModel):
    """Body accepted by ``POST /api/v1/pools``."""

    id: str = Field(description="Operator-chosen pool slug, e.g. 'hetzner-eu-central'.")
    label: str = Field(description="Human-readable pool name.")
    provider: str = Field(description="Fulfillment provider kind, e.g. 'ansible'.")
    enabled: bool = True
    policy_tags: dict[str, Any] = Field(
        default_factory=dict,
        description="Free-form tags for policy-driven pool lookup.",
    )
    provider_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-owned configuration validated by the selected handler.",
    )


class PoolReplace(BaseModel):
    """Complete replacement body accepted by ``PUT /api/v1/pools/{pool_id}``."""

    label: str
    provider: str
    enabled: bool
    policy_tags: dict[str, Any] = Field(default_factory=dict)
    provider_config: dict[str, Any] = Field(default_factory=dict)


class PoolUpdate(BaseModel):
    """Partial update body accepted by ``PATCH /api/v1/pools/{pool_id}``."""

    label: str | None = None
    provider: str | None = None
    enabled: bool | None = None
    policy_tags: dict[str, Any] | None = None
    provider_config: dict[str, Any] | None = None


class PoolResponse(BaseModel):
    """Serialized pool row returned by all pool endpoints."""

    id: str
    label: str
    provider: str
    enabled: bool
    policy_tags: dict[str, Any]
    provider_config: dict[str, Any]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PoolListResponse(BaseModel):
    pools: list[PoolResponse]
    total: int


class PoolImportRequest(BaseModel):
    yaml_text: str = Field(
        description="Authoritative resource-pool YAML with a top-level 'pools' list."
    )


class PoolImportDiff(BaseModel):
    """Reconciliation diff produced for a valid authoritative document."""

    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    disabled: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)


class PoolValidationProblem(BaseModel):
    """One problem found while validating an authoritative pool document."""

    path: str
    code: str
    message: str


class PoolImportResponse(BaseModel):
    diff: PoolImportDiff
    applied: bool


class PoolValidateResponse(BaseModel):
    valid: bool
    problems: list[PoolValidationProblem] = Field(default_factory=list)
    diff: PoolImportDiff | None = None
