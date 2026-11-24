"""Dry-run validation routes for the registry service.

POST /api/v1/listings/validate-publish
    Authenticates a canonical v2 marketplace request, then checks whether
    a listing payload would be structurally accepted by POST /listings without
    writing listing or publisher state. Used by composition smoke tests before
    a storefront attempts publication.

Validation is driven by the registry's filter-spec ``listing_shape``
(JSON Schema, draft 2020-12) — the same schema buyers see at
GET /filter-spec and the publication route uses at admission.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from core_registry.api.filter_spec import compute_etag, get_loaded_spec
from core_registry.api.validate_model import ValidatePublishRequest, ValidatePublishResponse
from core_registry.api.api_key_auth import require_read_access
from core_registry.api.publisher_auth import (
    authenticate_publisher_request,
    cached_response,
    complete_authenticated_request,
    registry_authority_signer,
    signed_response,
    wire_body,
)
from core_registry.db.database import get_db
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/v1/listings", tags=["validate"])


@lru_cache(maxsize=1)
def _validator_for(etag: str) -> Draft202012Validator:
    """Cache only for the currently served schema identity."""
    return Draft202012Validator(get_loaded_spec().listing_shape)


def _validator() -> Draft202012Validator:
    return _validator_for(compute_etag(get_loaded_spec()))


def _reset_cache() -> None:
    """Drop the cached validator — for tests that hot-swap the spec."""
    _validator_for.cache_clear()


def reject_retired_listing_shape(body: Any) -> None:
    """Give configured retired names specific errors before general validation.

    The prohibitions, and the replacement each one's ``description`` names,
    come from the served schema, so another market's listing vocabulary needs
    no registry code change. A named replacement helps a publisher correct a
    name that would otherwise match no query.
    """
    if not isinstance(body, dict):
        return
    shape = get_loaded_spec().listing_shape
    retired: dict[str, str | None] = {
        key: replacement
        for key, replacement in _forbidden_properties(shape).items()
        if key in body
    }
    resource = body.get("listing_resource")
    nested = shape.get("properties", {}).get("listing_resource", {})
    if isinstance(resource, dict):
        retired.update(
            (f"listing_resource.{key}", replacement)
            for key, replacement in _forbidden_properties(nested).items()
            if key in resource
        )
    if retired:
        named = "; ".join(
            f"`{field}`: {replacement}"
            for field, replacement in sorted(retired.items())
            if replacement
        )
        raise HTTPException(
            status_code=422,
            detail={
                "error": "retired_listing_shape",
                "retired_fields": sorted(retired),
                "message": (
                    f"Retired names are refused ({named}). See GET /filter-spec."
                    if named
                    else "Retired names are refused. See GET /filter-spec."
                ),
            },
        )


RESERVED_LISTING_FIELDS = frozenset({
    "publisher_id", "publisher_principals", "created_at", "updated_at",
    "publisher_publication", "publisher_updates",
})


def listing_validation_errors(candidate: dict[str, Any]) -> list[str]:
    """Use the complete candidate, including opaque terms, without model defaults."""
    errors = [
        f"{name}: reserved registry metadata"
        for name in sorted(RESERVED_LISTING_FIELDS.intersection(candidate))
    ]
    errors.extend(
        f"{_format_path(err)}: {err.message}"
        for err in sorted(_validator().iter_errors(candidate), key=lambda e: str(e.absolute_path))
    )
    return errors


def validate_listing_publication(candidate: dict[str, Any]) -> None:
    reject_retired_listing_shape(candidate)
    errors = listing_validation_errors(candidate)
    if errors:
        raise HTTPException(status_code=422, detail={"error": "invalid_listing", "errors": errors})


def _forbidden_properties(schema: dict[str, Any]) -> dict[str, str | None]:
    """Property names a schema's ``not`` clause forbids by requiring them,
    each with the replacement its clause's ``description`` names, if any.

    Only a clause requiring exactly one name forbids that name on its own; a
    clause requiring several forbids them together, which is general
    validation's to report.
    """

    prohibition = schema.get("not")
    if not isinstance(prohibition, dict):
        return {}
    clauses = prohibition.get("anyOf")
    if not isinstance(clauses, list):
        clauses = [prohibition]
    names: dict[str, str | None] = {}
    for clause in clauses:
        if not isinstance(clause, dict):
            continue
        required = clause.get("required")
        if isinstance(required, list) and len(required) == 1:
            description = clause.get("description")
            names[required[0]] = description if isinstance(description, str) else None
    return names


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


@router.post(
    "/validate-publish",
    response_model=ValidatePublishResponse,
    summary="Validate a listing payload without writing (dry-run)",
    description=(
        "Validates a listing body against the registry's ``listing_shape`` "
        "JSON Schema (the same one served at GET /filter-spec). Authenticated "
        "through the ordinary registry exchange, without listing or publisher "
        "mutations. Returns valid=True when the complete payload satisfies "
        "publication's structural checks; ownership is checked at publication."
    ),
)
async def validate_publish(
    request: Request,
    body: ValidatePublishRequest,
    db: Session = Depends(get_db),
):
    # Both authentication and validation use the caller's complete document;
    # materializing model defaults would change the signed/admitted content.
    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="POST",
        operation="listing.validate",
        resource="listings",
        body=wire_body(await request.body()),
        allowed_roles=frozenset({"buyer", "seller", "service"}),
    )
    require_read_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay
    candidate = wire_body(await request.body())
    errors = listing_validation_errors(candidate)

    response_body = ValidatePublishResponse(
        valid=not errors,
        listing_id=body.listing_id,
        accepted_escrows_count=len(body.accepted_escrows),
        settlement_options_count=len(body.settlement_options),
        errors=errors,
    ).model_dump(mode="json")
    complete_authenticated_request(
        authenticated=authenticated,
        db=db,
        status=200,
        body=response_body,
    )
    db.commit()
    return signed_response(
        authenticated=authenticated,
        signer=signer,
        status=200,
        body=response_body,
    )
