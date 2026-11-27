"""Principal-authenticated marketplace listing routes.

Each route admits its request through the registry's admission core, which
verifies it, reserves it, resolves an exact retry as the route declares, and
signs whatever the route answers. Publication, update and deletion are recorded:
each sets or deletes what a later write may supersede, so an exact retry is
answered with the recorded outcome and never runs again. The reads re-run.
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse, Response
from market_authenticated_requests import Admitted, RouteAdmission, path_resource
from market_identity import ExactRetry, Identity
from sqlalchemy import desc
from sqlalchemy.orm import Session

from core_registry.api.admission import READ_ROLES, WRITE_ROLES, registry_core
from core_registry.api.api_key_auth import require_read_access, require_write_access
from core_registry.api.filter_eval import FilterParamError, build_criteria, evaluate_all
from core_registry.api.filter_spec import compute_etag, get_loaded_spec
from core_registry.api.validate_routes import validate_listing_publication
from core_registry.api.utils import (
    active_identities,
    ensure_publisher_for_identity,
    find_publisher_by_identity,
    order_to_dict,
    publisher_accepts_identity,
    validate_order_status,
)
from core_registry.db.database import get_db
from core_registry.db.models import Listing, utcnow

logger = logging.getLogger(__name__)
router = APIRouter()

#: The listing read's query parameter naming the filter-spec ETag its filters were
#: compiled under; the request's signature covers it, as it covers the whole query.
FILTER_SPEC_ETAG_PARAM = "filter_spec_etag"


def publication_evidence(admitted: Admitted) -> dict[str, Any]:
    """The seller's signed request as the registry keeps it: the exact body bytes,
    and the record of every value the seller's signature covers."""

    return {
        "body_base64": base64.b64encode(admitted.body).decode("ascii"),
        "request": admitted.record.model_dump(mode="json"),
    }


@router.post("/listings", status_code=201)
async def publish_listing(
    request: Request,
    admitted: Admitted = Depends(
        RouteAdmission(
            registry_core, operation="listing.publish", roles=WRITE_ROLES, exact_retry=ExactRetry.RECORDED
        )
    ),
    body: dict = Body(..., description="Marketplace listing"),
    db: Session = Depends(get_db),
):
    """Publish after verifying a body-bound proof by the complete principal."""

    require_write_access(request, db)
    validate_listing_publication(body)
    evidence = publication_evidence(admitted)
    listing_id = body.get("listing_id")
    if not isinstance(listing_id, str) or not listing_id:
        raise HTTPException(status_code=400, detail="listing_id is required")

    status = validate_order_status(body.get("status", "open"))
    publisher = ensure_publisher_for_identity(
        db,
        admitted.request.principal,
        storefront_url=body.get("storefront_url"),
    )
    existing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if existing:
        if existing.publisher_id != publisher.publisher_id:
            raise HTTPException(
                status_code=403,
                detail="Listing is owned by another publisher",
            )
        existing.published_document = dict(body)
        existing.publication = evidence
        updates = dict(existing.updates or {})
        updates.pop("oracle_address", None)
        if "status" in body:
            existing.status = status
            updates.pop("status", None)
        existing.updates = updates
        existing.updated_at = utcnow()
        listing = existing
    else:
        listing = Listing(
            listing_id=listing_id,
            publisher_id=publisher.publisher_id,
            published_document=dict(body),
            publication=evidence,
            updates={},
            listing_resource={},
            status=status,
        )
        db.add(listing)
    db.flush()
    response_body = {
        "listing_id": listing.listing_id,
        "publisher_id": publisher.publisher_id,
        "publisher_principals": active_identities(publisher).model_dump(mode="json"),
        "status": listing.status.value,
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat(),
    }
    db.commit()
    return JSONResponse(status_code=201, content=response_body)


_RESERVED_QUERY_PARAMS = {
    "status",
    "limit",
    "offset",
    "publisher_scheme",
    "publisher_identifier",
    FILTER_SPEC_ETAG_PARAM,
}


@router.get("/listings")
async def query_listings(
    request: Request,
    admitted: Admitted = Depends(
        RouteAdmission(registry_core, operation="listing.list", roles=READ_ROLES, exact_retry=ExactRetry.RERUN)
    ),
    status: Optional[str] = Query("open", description="Filter by listing status"),
    publisher_scheme: Optional[str] = Query(None),
    publisher_identifier: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    filter_spec_etag: Optional[str] = Query(
        None,
        description=(
            "The filter-spec ETag the query's filters were compiled under; a stale "
            "value is refused with 412"
        ),
    ),
    if_match: Optional[str] = Header(None, alias="If-Match"),
    db: Session = Depends(get_db),
):
    """Query listings with optional exact-principal owner filtering."""

    require_read_access(request, db)
    if if_match is not None:
        # The ETag travels as the signed query parameter; a header the signature
        # does not cover is refused rather than read or left unchecked.
        raise HTTPException(
            status_code=400,
            detail=f"If-Match is not read on a listing query; send the ETag as {FILTER_SPEC_ETAG_PARAM}",
        )

    spec = get_loaded_spec()
    current_etag = compute_etag(spec)
    if filter_spec_etag is not None and filter_spec_etag != current_etag:
        raise HTTPException(
            status_code=412,
            detail={
                "error": "filter-spec etag mismatch",
                "current_etag": current_etag,
            },
        )

    if (publisher_scheme is None) != (publisher_identifier is None):
        raise HTTPException(
            status_code=400,
            detail="publisher_scheme and publisher_identifier are required together",
        )

    query = db.query(Listing)
    if status:
        query = query.filter(Listing.status == validate_order_status(status))
    if publisher_scheme is not None and publisher_identifier is not None:
        try:
            principal = Identity(
                scheme=publisher_scheme,
                identifier=publisher_identifier,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid publisher principal") from exc
        publisher = find_publisher_by_identity(db, principal)
        if publisher is None:
            query = query.filter(Listing.publisher_id == -1)
        else:
            query = query.filter(Listing.publisher_id == publisher.publisher_id)

    filter_params = {
        key: value
        for key, value in request.query_params.items()
        if key not in _RESERVED_QUERY_PARAMS
    }
    try:
        criteria = build_criteria(spec, filter_params)
    except FilterParamError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Times are whole seconds, so listings stored in one second tie on
    # ``created_at``; the listing id keeps their order stable between reads.
    rows = query.order_by(desc(Listing.created_at), Listing.listing_id).all()
    matched = [
        order_to_dict(row)
        for row in rows
        if evaluate_all(order_to_dict(row), criteria)
    ]
    page = matched[offset : offset + limit]
    return {
        "items": page,
        "count": len(page),
        "total_after_filter": len(matched),
    }


@router.put("/listings/{listing_id}")
async def update_listing(
    request: Request,
    admitted: Admitted = Depends(
        RouteAdmission(
            registry_core,
            operation="listing.update",
            roles=WRITE_ROLES,
            exact_retry=ExactRetry.RECORDED,
            resource=path_resource("listing_id"),
        )
    ),
    listing_id: str = Path(..., description="Listing ID"),
    body: dict = Body(..., description="Listing updates"),
    db: Session = Depends(get_db),
):
    """Mutate one listing after exact-principal owner authorization."""

    require_write_access(request, db)
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not publisher_accepts_identity(listing.publisher, admitted.request.principal):
        raise HTTPException(status_code=403, detail="Publisher principal does not own listing")

    unsupported = sorted(set(body) - {"status", "oracle_address"})
    if unsupported:
        raise HTTPException(status_code=422, detail={"unsupported_update_fields": unsupported})
    evidence = publication_evidence(admitted)
    listing.updates = {
        **(listing.updates or {}),
        **{name: evidence for name in body},
    }
    if "status" in body:
        listing.status = validate_order_status(body["status"])
    if "oracle_address" in body:
        listing.oracle_address = body["oracle_address"]
    listing.updated_at = utcnow()
    db.flush()
    response_body = {
        "listing_id": listing.listing_id,
        "status": listing.status.value,
        "updated_at": listing.updated_at.isoformat(),
    }
    db.commit()
    return response_body


@router.get("/listings/{listing_id}")
async def get_listing(
    request: Request,
    admitted: Admitted = Depends(
        RouteAdmission(
            registry_core,
            operation="listing.get",
            roles=READ_ROLES,
            exact_retry=ExactRetry.RERUN,
            resource=path_resource("listing_id"),
        )
    ),
    listing_id: str = Path(..., description="Listing ID"),
    db: Session = Depends(get_db),
):
    require_read_access(request, db)
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"listing": order_to_dict(listing)}


@router.delete(
    "/listings/{listing_id}",
    status_code=204,
)
async def delete_listing(
    request: Request,
    admitted: Admitted = Depends(
        RouteAdmission(
            registry_core,
            operation="listing.delete",
            roles=WRITE_ROLES,
            exact_retry=ExactRetry.RECORDED,
            resource=path_resource("listing_id"),
        )
    ),
    listing_id: str = Path(..., description="Listing ID"),
    db: Session = Depends(get_db),
):
    """Delete one listing after exact-principal owner authorization."""

    require_write_access(request, db)
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not publisher_accepts_identity(listing.publisher, admitted.request.principal):
        raise HTTPException(status_code=403, detail="Publisher principal does not own listing")

    db.delete(listing)
    db.commit()
    return Response(status_code=204)
