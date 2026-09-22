"""Executor-neutral resource-pool wire models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .hints import validate_pool_declarations


def _require_pool_declarations(policy_tags: dict[str, Any]) -> None:
    """Refuse a pool write whose advertisement or backing declarations are invalid.

    Both declarations are required rather than defaulted: a default backing
    would assert whether anything stands behind a listing, and a default
    advertisable set would widen or silently narrow what a pool may sell.
    The service reapplies the same check to what it persists.
    """
    problems = validate_pool_declarations(policy_tags)
    if problems:
        raise ValueError("; ".join(problems))


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

    @model_validator(mode="after")
    def _declarations(self) -> "PoolCreate":
        _require_pool_declarations(self.policy_tags)
        return self


class PoolReplace(BaseModel):
    """Complete replacement body accepted by ``PUT /api/v1/pools/{pool_id}``."""

    label: str
    provider: str
    enabled: bool
    policy_tags: dict[str, Any] = Field(default_factory=dict)
    provider_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _declarations(self) -> "PoolReplace":
        _require_pool_declarations(self.policy_tags)
        return self


class PoolUpdate(BaseModel):
    """Partial update body accepted by ``PATCH /api/v1/pools/{pool_id}``."""

    label: str | None = None
    provider: str | None = None
    enabled: bool | None = None
    policy_tags: dict[str, Any] | None = None
    provider_config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _declarations(self) -> "PoolUpdate":
        # A patch supplying policy tags replaces the whole map, so it must
        # restate both declarations; one that leaves the map alone does not.
        if self.policy_tags is not None:
            _require_pool_declarations(self.policy_tags)
        return self


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
