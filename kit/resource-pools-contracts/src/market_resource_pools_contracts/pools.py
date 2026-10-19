"""Executor-neutral resource-pool wire models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from .asking_rates import validate_asking_rates
from .hints import (
    validate_hold_preference,
    validate_listing_shapes,
    validate_pool_declarations,
    validate_pricing_rates,
    validate_sla_preference,
)


def _require_valid_policy_tags(policy_tags: dict[str, Any]) -> None:
    """Validate declarations and domain-neutral hint structure before dispatch.

    Required declarations state what a pool can advertise and what backs it.
    Optional hints are checked only for structure; the reading domain owns
    their vocabulary and provider handlers own configuration semantics.
    """
    problems = (
        validate_pool_declarations(policy_tags)
        + validate_hold_preference(policy_tags)
        + validate_sla_preference(policy_tags)
        + validate_listing_shapes(policy_tags)
        + validate_asking_rates(policy_tags)
        + validate_pricing_rates(policy_tags)
    )
    if problems:
        raise ValueError("; ".join(problems))


class PoolCreate(BaseModel):
    """Body accepted by ``POST /api/v1/pools``."""

    id: str = Field(description="Operator-chosen pool slug, e.g. 'hetzner-eu-central'.")
    label: str = Field(description="Human-readable pool name.")
    provider: str = Field(description="Fulfillment provider kind, e.g. 'vm.ansible'.")
    enabled: bool = True
    policy_tags: dict[str, Any] = Field(
        description=(
            "Pool policy tags. Must declare advertisable_modes and "
            "capacity_backing; other tags are free-form."
        ),
    )
    provider_config: dict[str, Any] = Field(
        default_factory=dict,
        description="Provider-owned configuration validated by the selected handler.",
    )

    @model_validator(mode="after")
    def _policy_tag_hints(self) -> "PoolCreate":
        _require_valid_policy_tags(self.policy_tags)
        return self


class PoolReplace(BaseModel):
    """Complete replacement body accepted by ``PUT /api/v1/pools/{pool_id}``."""

    label: str
    provider: str
    enabled: bool
    policy_tags: dict[str, Any]
    provider_config: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _policy_tag_hints(self) -> "PoolReplace":
        _require_valid_policy_tags(self.policy_tags)
        return self


class PoolUpdate(BaseModel):
    """Partial update body accepted by ``PATCH /api/v1/pools/{pool_id}``."""

    label: str | None = None
    provider: str | None = Field(
        default=None,
        description=(
            "Must equal the pool's provider, which is fixed at creation. "
            "Restating it has no effect and does not rewrite configuration."
        ),
    )
    enabled: bool | None = None
    policy_tags: dict[str, Any] | None = None
    provider_config: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _policy_tag_hints(self) -> "PoolUpdate":
        # A patch supplying policy tags replaces the whole map, so it must
        # restate both declarations; one that leaves the map alone does not.
        if self.policy_tags is not None:
            _require_valid_policy_tags(self.policy_tags)
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
