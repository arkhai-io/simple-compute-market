"""Typed models for the site-authority capacity-administration surface.

The capacity-definition import models mirror ``market_site.capacity_definitions``
for the same reason, and ``kit/site``'s route parity test compares the two.

Deliberately independent of ``kit/site``'s own server-side
``ResourceRegisterRequest`` (``market_site.http_models``), even though
the shape mirrors it exactly: importing the server package here would
pull in its full SQLAlchemy-backed implementation for something that
only needs to serialize a small HTTP request body. Keep the two shapes
in sync by hand when either changes -- there are only two fields sets to
compare, so the duplication cost is low next to the dependency cost of
sharing the type.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ResourceRegistration(BaseModel):
    """Request body for registering or updating a capacity resource.

    Mirrors ``market_site.http_models.ResourceRegisterRequest`` (the
    server-side model for ``PUT /api/v1/capacity/resources/{resource_id}``).
    """

    total_units: Optional[int] = Field(default=None, ge=0)
    resource_type: str = Field(default="compute.gpu")
    pool_id: str = Field(min_length=1)
    host_id: Optional[str] = Field(default=None)
    resource_subtype: Optional[str] = Field(default=None)
    attributes: dict[str, Any] = Field(default_factory=dict)
    capacity: Optional[dict[str, Any]] = Field(default=None)
    enabled: bool = Field(default=True)


class CapacityDefinitionProblem(BaseModel):
    """One problem found in a capacity-definitions document."""

    path: str
    code: str
    message: str


class CapacityDefinitionsDiff(BaseModel):
    """What reconciling a document changes, by resource id.

    There is no ``disabled`` list: a document never removes or disables a
    declaration it does not name.
    """

    created: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)


class CapacityDefinitionsImportRequest(BaseModel):
    yaml_text: str = Field(
        description="Capacity-definitions YAML with a top-level 'resources' list."
    )
    validate_only: bool = Field(
        default=False,
        description=(
            "Report the problems and the planned changes without applying "
            "either."
        ),
    )


class CapacityDefinitionsImportResponse(BaseModel):
    applied: bool
    diff: CapacityDefinitionsDiff
    problems: list[CapacityDefinitionProblem] = Field(default_factory=list)
