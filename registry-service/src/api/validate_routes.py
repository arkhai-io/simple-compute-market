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


@router.post(
    "/validate-publish",
    response_model=ValidatePublishResponse,
    summary="Validate a listing payload without writing (dry-run)",
    description=(
        "Checks that a listing body is structurally valid for publication: "
        "listing_id present, offer/demand recognisable as compute or token. "
        "No database writes, no authentication required. "
        "Returns valid=True when the payload would be accepted by "
        "POST /agents/{agent_id}/listings (modulo agent registration and auth)."
    ),
)
async def validate_publish(body: ValidatePublishRequest) -> ValidatePublishResponse:
    errors: list[str] = []

    # listing_id must be non-empty (enforced by Pydantic min_length would also
    # work, but an explicit message is more useful in test output)
    if not body.listing_id or not body.listing_id.strip():
        errors.append("listing_id must be a non-empty string")

    offer_type = _get_resource_type(body.offer_resource)
    demand_type = _get_resource_type(body.demand_resource)

    if offer_type == "unknown":
        errors.append(
            "offer_resource not recognisable as compute (needs gpu_model/region/sla) "
            "or token (needs 'token' key)"
        )
    if demand_type == "unknown":
        errors.append(
            "demand_resource not recognisable as compute (needs gpu_model/region/sla) "
            "or token (needs 'token' key)"
        )

    # A valid listing must be one compute side and one token side
    if offer_type != "unknown" and demand_type != "unknown":
        if offer_type == demand_type:
            errors.append(
                f"offer_resource and demand_resource must be different types "
                f"(one compute, one token); both are '{offer_type}'"
            )

    if body.max_duration_seconds is not None and body.max_duration_seconds <= 0:
        errors.append(
            f"max_duration_seconds must be positive when provided, "
            f"got {body.max_duration_seconds}"
        )

    return ValidatePublishResponse(
        valid=len(errors) == 0,
        listing_id=body.listing_id,
        offer_resource_type=offer_type if offer_type != "unknown" else None,
        demand_resource_type=demand_type if demand_type != "unknown" else None,
        errors=errors,
    )
