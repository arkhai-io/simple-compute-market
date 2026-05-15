"""Dry-run validation routes for the registry service.

POST /api/v1/listings/validate-publish
    Checks whether a listing payload would be accepted by
    POST /agents/{agent_id}/listings without writing anything to the
    database or requiring auth.  Used by the e2e test suite (stage 03a)
    to confirm a listing is structurally publishable before calling
    resume on the storefront.
"""

from __future__ import annotations

from fastapi import APIRouter

from src.api.validate_model import ValidatePublishRequest, ValidatePublishResponse

router = APIRouter(prefix="/api/v1/listings", tags=["validate"])


def _get_resource_type(resource: dict) -> str:
    """Classify a resource dict as 'compute', 'token', or 'unknown'."""
    if not resource:
        return "unknown"
    if "token" in resource:
        return "token"
    if "gpu_model" in resource or "region" in resource or "sla" in resource:
        return "compute"
    return "unknown"


def _accepted_escrow_errors(entries: list[dict]) -> list[str]:
    """Return one error string per malformed accepted_escrows entry."""
    errors: list[str] = []
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"accepted_escrows[{i}] must be an object")
            continue
        if not entry.get("chain_name"):
            errors.append(f"accepted_escrows[{i}].chain_name is required")
        if not entry.get("escrow_address"):
            errors.append(f"accepted_escrows[{i}].escrow_address is required")
    return errors


@router.post(
    "/validate-publish",
    response_model=ValidatePublishResponse,
    summary="Validate a listing payload without writing (dry-run)",
    description=(
        "Checks that a listing body is structurally valid for publication: "
        "listing_id present, offer_resource recognisable, accepted_escrows "
        "non-empty with required keys on each entry. "
        "No database writes, no authentication required. "
        "Returns valid=True when the payload would be accepted by "
        "POST /agents/{agent_id}/listings (modulo agent registration and auth)."
    ),
)
async def validate_publish(body: ValidatePublishRequest) -> ValidatePublishResponse:
    errors: list[str] = []

    if not body.listing_id or not body.listing_id.strip():
        errors.append("listing_id must be a non-empty string")

    offer_type = _get_resource_type(body.offer_resource)
    if offer_type == "unknown":
        errors.append(
            "offer_resource not recognisable as compute (needs gpu_model/region/sla) "
            "or token (needs 'token' key)"
        )

    if not body.accepted_escrows:
        errors.append(
            "accepted_escrows must be a non-empty list of escrow tuples"
        )
    else:
        errors.extend(_accepted_escrow_errors(body.accepted_escrows))

    if body.max_duration_seconds is not None and body.max_duration_seconds <= 0:
        errors.append(
            f"max_duration_seconds must be positive when provided, "
            f"got {body.max_duration_seconds}"
        )

    return ValidatePublishResponse(
        valid=len(errors) == 0,
        listing_id=body.listing_id,
        offer_resource_type=offer_type if offer_type != "unknown" else None,
        accepted_escrows_count=len(body.accepted_escrows),
        errors=errors,
    )
