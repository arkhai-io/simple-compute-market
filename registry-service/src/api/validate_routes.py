"""Dry-run validation routes for the registry service.

POST /api/v1/listings/validate-publish
    Checks whether a listing payload would be accepted by
    POST /agents/{agent_id}/listings without writing anything to the
    database or requiring auth.  Used by the e2e test suite (stage 03a)
    to confirm a listing is structurally publishable before calling
    resume on the storefront.

Validation is driven by the registry's filter-spec ``listing_shape``
(JSON Schema, draft 2020-12) — the same schema buyers see at
GET /filter-spec.  Hardcoded compute/token heuristics are gone; what
counts as a valid listing is now whatever the YAML says.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from src.api.filter_spec import get_loaded_spec
from src.api.validate_model import ValidatePublishRequest, ValidatePublishResponse

router = APIRouter(prefix="/api/v1/listings", tags=["validate"])


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    """Validator built once from the loaded listing_shape."""
    return Draft202012Validator(get_loaded_spec().listing_shape)


def _reset_cache() -> None:
    """Drop the cached validator — for tests that hot-swap the spec."""
    _validator.cache_clear()


def _format_path(err: ValidationError) -> str:
    """Render a jsonschema error's absolute_path as a JSONPath-ish string."""
    if not err.absolute_path:
        return "<root>"
    parts: list[str] = []
    for p in err.absolute_path:
        if isinstance(p, int):
            parts.append(f"[{p}]")
        else:
            parts.append("." + p if parts else p)
    return "".join(parts)


def _derive_offer_resource_type(offer_resource: dict[str, Any]) -> str | None:
    """Best-effort resource-type tag for the response body.

    Cosmetic — the actual accept/reject decision is the schema's, not
    this function's.  Kept for back-compat with registry-client's
    ``ValidatePublishResponse.offer_resource_type``; will be dropped
    when the client updates in a1b-4.
    """
    if not offer_resource:
        return None
    if "gpu_model" in offer_resource or "region" in offer_resource:
        return "compute"
    if "token" in offer_resource:
        return "token"
    return None


@router.post(
    "/validate-publish",
    response_model=ValidatePublishResponse,
    summary="Validate a listing payload without writing (dry-run)",
    description=(
        "Validates a listing body against the registry's ``listing_shape`` "
        "JSON Schema (the same one served at GET /filter-spec).  No database "
        "writes, no authentication required.  Returns ``valid=True`` when the "
        "payload would be accepted by POST /agents/{agent_id}/listings (modulo "
        "agent registration and auth)."
    ),
)
async def validate_publish(body: ValidatePublishRequest) -> ValidatePublishResponse:
    candidate: dict[str, Any] = {
        "listing_id": body.listing_id,
        "storefront_url": body.storefront_url,
        "offer_resource": body.offer_resource,
        "accepted_escrows": body.accepted_escrows,
        "max_duration_seconds": body.max_duration_seconds,
    }

    errors = [
        f"{_format_path(err)}: {err.message}"
        for err in sorted(_validator().iter_errors(candidate), key=lambda e: list(e.absolute_path))
    ]

    return ValidatePublishResponse(
        valid=not errors,
        listing_id=body.listing_id,
        offer_resource_type=_derive_offer_resource_type(body.offer_resource),
        accepted_escrows_count=len(body.accepted_escrows),
        errors=errors,
    )
