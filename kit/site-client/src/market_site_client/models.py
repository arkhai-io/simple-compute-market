"""Typed models for the site-authority capacity-administration surface.

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

    total_units: int = Field(
        ge=0,
        description="Unit count this resource contributes (e.g. GPUs).",
    )
    resource_type: str = Field(default="compute.gpu")
    pool_id: Optional[str] = Field(default=None)
    resource_subtype: Optional[str] = Field(default=None)
    attributes: dict[str, Any] = Field(default_factory=dict)
    capacity: Optional[dict[str, Any]] = Field(default=None)
    enabled: bool = Field(default=True)
