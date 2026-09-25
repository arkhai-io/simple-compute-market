"""Pool override records: what an administrator writes, and the responses.

An override is the storefront's own statement of terms and listing shapes for one
pool at one site, in one offering mode. The kit validates only the record's
structure; what its shapes and terms may say is the market's, checked by the
contribution registered for its offering mode. Physical facts about the pool —
region and capacity backing — are the site's, so a record has no field for them
and refuses one it is given.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator, model_validator


def _address_component(value: str) -> str:
    if "\x00" in value:
        raise ValueError("must not contain NUL")
    return value


class PoolOverrideAddress(BaseModel):
    """Which override: a site, one of its pools, and an offering mode.

    Pool identifiers are site-local, and one pool may be sold in several offering
    modes, each by its own market, so all three are needed and none is defaulted.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    site_id: StrictStr = Field(min_length=1)
    pool_id: StrictStr = Field(min_length=1)
    offering_mode: StrictStr = Field(min_length=1)

    @field_validator("site_id", "pool_id", "offering_mode")
    @classmethod
    def _no_nul(cls, value: str) -> str:
        return _address_component(value)


class PoolOverrideRecord(PoolOverrideAddress):
    """One override as written: its address, then what it states.

    ``listing_shapes`` and ``settlements`` each replace the lower tier's list as a
    whole, so an empty list would be a second, less visible way to stop selling
    the pool; a seller stops selling by closing its listings. ``terms`` is the
    market's own commercial vocabulary, opaque here.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    listing_shapes: list[dict[str, Any]] | None = None
    settlements: list[dict[str, Any]] | None = None
    terms: dict[str, Any] | None = None

    @field_validator("listing_shapes", "settlements")
    @classmethod
    def _non_empty(cls, value: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if value is not None and not value:
            raise ValueError("must be omitted or a non-empty list")
        return value

    @model_validator(mode="after")
    def _states_something(self) -> "PoolOverrideRecord":
        if self.listing_shapes is None and self.settlements is None and not self.terms:
            raise ValueError("an override must state listing shapes, settlements, or terms")
        return self

    @property
    def address(self) -> PoolOverrideAddress:
        return PoolOverrideAddress(
            site_id=self.site_id, pool_id=self.pool_id, offering_mode=self.offering_mode
        )


class PoolOverride(PoolOverrideRecord):
    """A stored override, with its storage timestamps."""

    created_at: str
    updated_at: str


class ShapeFeasibility(BaseModel):
    """Whether any member of the live projection is feasible for one shape."""

    shape_digest: str
    shape: dict[str, Any]
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


class PoolOverrideDeleteResponse(PoolOverrideAddress):
    """Response to deleting an override; ``deleted`` is false when none existed."""

    deleted: bool


__all__ = [
    "PoolOverride",
    "PoolOverrideAddress",
    "PoolOverrideDeleteResponse",
    "PoolOverrideListResponse",
    "PoolOverrideRecord",
    "PoolOverrideResponse",
    "PoolOverrideWriteResponse",
    "ProjectionGeneration",
    "ShapeFeasibility",
]
