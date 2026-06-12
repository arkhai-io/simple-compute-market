"""API-tokens listing resource schema.

The listing's ``offer_resource`` is opaque to the registry and
schema-typed by the domain plugin (design-api-tokens-domain.md, "The
market shape"). ``resource_id`` names the quota resource in the tokens
service's ledger that the listing derives from — seller-internal
bookkeeping the reconciler and quota guard key on; buyers ignore it.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

API_TOKENS_KIND = "api_tokens.v1"


class ApiTokensResource(BaseModel):
    """``offer_resource`` payload for an API-token listing."""

    kind: str = Field(default=API_TOKENS_KIND, pattern="^api_tokens\\.v1$")
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


def resource_is_api_tokens(resource: Any) -> bool:
    """True when the resource is an API-tokens offering."""
    if isinstance(resource, ApiTokensResource):
        return True
    coerced = coerce_resource_dict(resource)
    return coerced.get("kind") == API_TOKENS_KIND
