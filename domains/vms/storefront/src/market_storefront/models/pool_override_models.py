"""Storefront pool overrides: the record an administrator writes, and responses.

An override states the storefront's own terms for one pool at one site. Every
field but the site and pool is optional: an unset field states nothing and the
next precedence tier supplies it. Physical facts — region, offering mode,
capacity backing — are the site's, so the record has no field for them and
refuses one it is given.

See openspec/specs/storefront-publication/spec.md, "Storefront pool overrides
are site-scoped and durable".
"""

from __future__ import annotations

from typing import Any

from arkhai_vms import vm_shape_problems
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
)


class PoolOverrideRecord(BaseModel):
    """One site's pool override, as written and stored."""

    model_config = ConfigDict(extra="forbid")

    site_id: StrictStr = Field(min_length=1)
    pool_id: StrictStr = Field(min_length=1)
    sla: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    min_price: StrictStr | None = None
    token: StrictStr | None = None
    max_duration_seconds: StrictInt | None = Field(default=None, gt=0)
    settlements: list[dict[str, Any]] | None = None
    listing_shapes: list[dict[str, Any]] | None = None

    @field_validator("site_id", "pool_id")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("must not contain NUL")
        return value

    @field_validator("settlements")
    @classmethod
    def _settlements_non_empty(
        cls, value: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        # An empty list would leave every listing of the pool with no settlement
        # option: a second, less visible way to stop selling it. A seller stops
        # selling by closing its listings.
        if value is not None and not value:
            raise ValueError("must be omitted or a non-empty list of clauses")
        return value

    @field_validator("listing_shapes")
    @classmethod
    def _shapes_in_vocabulary(
        cls, value: list[dict[str, Any]] | None
    ) -> list[dict[str, Any]] | None:
        if value is None:
            return value
        if not value:
            raise ValueError("must be omitted or a non-empty list of shapes")
        problems = [
            f"[{index}] {problem}"
            for index, shape in enumerate(value)
            for problem in vm_shape_problems(shape)
        ]
        if problems:
            raise ValueError("; ".join(problems))
        return value


class PoolOverride(PoolOverrideRecord):
    """A stored override, with its storage timestamps."""

    created_at: str
    updated_at: str


class ShapeFeasibility(BaseModel):
    """Whether any member of the live projection is feasible for one shape."""

    shape_digest: str
    shape: dict[str, dict[str, Any]]
    feasible: bool


class ProjectionGeneration(BaseModel):
    """The site projection generation a write was checked against."""

    revision: int
    digest: str


class PoolOverrideWriteResponse(BaseModel):
    """Response to replacing an override."""

    override: PoolOverride
    feasibility: list[ShapeFeasibility]
    projection: ProjectionGeneration


class PoolOverrideResponse(BaseModel):
    """Response to reading one override."""

    override: PoolOverride


class PoolOverrideListResponse(BaseModel):
    """Response to listing overrides."""

    overrides: list[PoolOverride]


class PoolOverrideDeleteResponse(BaseModel):
    """Response to deleting an override; ``deleted`` is false when none existed."""

    site_id: str
    pool_id: str
    deleted: bool
