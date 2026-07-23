"""API-credits listing resource schema.

The listing's ``offer_resource`` is opaque to the registry and
schema-typed by the domain plugin (ARCHITECTURE.md, "API-credits market
domain — Market shape"). ``resource_id`` names the quota resource in the tokens
service's ledger that the listing derives from — seller-internal
bookkeeping the reconciler and quota guard key on; buyers ignore it.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

API_CREDITS_KIND = "api_credits.v1"


class ApiCreditsResource(BaseModel):
    """``offer_resource`` payload for an API-credit listing."""

    kind: str = Field(default=API_CREDITS_KIND, pattern="^api_credits\\.v1$")
    service_name: str
    description: str | None = None
    openapi_url: str | None = None
    base_url: str | None = None
    resource_id: str | None = Field(
        default=None,
        description="Quota resource this listing derives from (seller-side).",
    )


def coerce_resource_dict(value: Any) -> dict[str, Any]:
    """Best-effort dict view of an offer_resource (SQLite stores JSON text)."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def resource_is_api_credits(resource: Any) -> bool:
    """True when the resource is an API-credits offering."""
    if isinstance(resource, ApiCreditsResource):
        return True
    coerced = coerce_resource_dict(resource)
    return coerced.get("kind") == API_CREDITS_KIND
