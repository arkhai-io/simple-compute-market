"""Principal-authenticated marketplace listing routes."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path, Query, Request
from market_identity import Identity
from sqlalchemy import desc
from sqlalchemy.orm import Session

from src.api.api_key_auth import require_read_access, require_write_access
from src.api.filter_eval import FilterParamError, build_criteria, evaluate_all
from src.api.filter_spec import compute_etag, get_loaded_spec
from src.api.publisher_auth import (
    authenticate_publisher_request,
    cached_response,
    canonical_query_body,
    normalize_if_match,
    complete_authenticated_request,
    registry_authority_signer,
    signed_response,
)
from src.api.utils import (
    active_identities,
    ensure_publisher_for_identity,
    find_publisher_by_identity,
    order_to_dict,
    publisher_accepts_identity,
    validate_order_status,
)
from src.db.database import get_db
from src.db.models import Listing

logger = logging.getLogger(__name__)
router = APIRouter()

@router.post("/listings", status_code=201)
async def publish_listing(
    request: Request,
    body: dict = Body(..., description="Marketplace listing"),
    db: Session = Depends(get_db),
):
    """Publish after verifying a body-bound proof by the complete principal."""

    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="POST",
        operation="listing.publish",
        resource="listings",
        body=body,
    )
    require_write_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay

    listing_id = body.get("listing_id")
    if not isinstance(listing_id, str) or not listing_id:
        raise HTTPException(status_code=400, detail="listing_id is required")

    publisher = ensure_publisher_for_identity(
        db,
        authenticated.principal,
        storefront_url=body.get("storefront_url"),
    )
    existing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if existing:
        if existing.publisher_id != publisher.publisher_id:
            raise HTTPException(
                status_code=403,
                detail="Listing is owned by another publisher",
            )
        update_fields = {
            "offer_resource": body.get("offer_resource"),
            "accepted_escrows": body.get("accepted_escrows"),
            "settlement_options": body.get("settlement_options"),
            "demands": body.get("demands"),
            "max_duration_seconds": body.get("max_duration_seconds"),
            "oracle_address": body.get("oracle_address"),
        }
        for field, value in update_fields.items():
            if value is not None:
                setattr(existing, field, value)
        if "status" in body:
            existing.status = validate_order_status(body["status"])
        existing.updated_at = datetime.utcnow()
        listing = existing
    else:
        listing = Listing(
            listing_id=listing_id,
            publisher_id=publisher.publisher_id,
            offer_resource=body.get("offer_resource", {}),
            accepted_escrows=body.get("accepted_escrows", []),
            settlement_options=body.get("settlement_options", []),
            demands=body.get("demands", []),
            max_duration_seconds=body.get("max_duration_seconds"),
            oracle_address=body.get("oracle_address"),
            status=validate_order_status(body.get("status", "open")),
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
    complete_authenticated_request(
        authenticated=authenticated,
        db=db,
        status=201,
        body=response_body,
    )
    db.commit()
    return signed_response(
        authenticated=authenticated,
        signer=signer,
        status=201,
        body=response_body,
    )


_RESERVED_QUERY_PARAMS = {
    "status",
    "limit",
    "offset",
    "publisher_scheme",
    "publisher_identifier",
}


@router.get("/listings")
async def query_listings(
    request: Request,
    status: Optional[str] = Query("open", description="Filter by listing status"),
    publisher_scheme: Optional[str] = Query(None),
    publisher_identifier: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    if_match: Optional[str] = Header(None, alias="If-Match"),
    db: Session = Depends(get_db),
):
    """Query listings with optional exact-principal owner filtering."""
    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="GET",
        operation="listing.list",
        resource="listings",
        body=canonical_query_body(request),
        allowed_roles=frozenset({"buyer", "seller", "service"}),
    )
    require_read_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay


    spec = get_loaded_spec()
    current_etag = compute_etag(spec)
    if if_match is not None:
        normalized = normalize_if_match(if_match)
        if normalized != current_etag:
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

    rows = query.order_by(desc(Listing.created_at)).all()
    matched = [
        order_to_dict(row)
        for row in rows
        if evaluate_all(order_to_dict(row), criteria)
    ]
    page = matched[offset : offset + limit]
    response_body = {
        "items": page,
        "count": len(page),
        "total_after_filter": len(matched),
    }
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


@router.put("/listings/{listing_id}")
async def update_listing(
    request: Request,
    listing_id: str = Path(..., description="Listing ID"),
    body: dict = Body(..., description="Listing updates"),
    db: Session = Depends(get_db),
):
    """Mutate one listing after exact-principal owner authorization."""

    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="PUT",
        operation="listing.update",
        resource=listing_id,
        body=body,
    )
    require_write_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay

    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not publisher_accepts_identity(listing.publisher, authenticated.principal):
        raise HTTPException(status_code=403, detail="Publisher principal does not own listing")

    if "status" in body:
        listing.status = validate_order_status(body["status"])
    if "oracle_address" in body:
        listing.oracle_address = body["oracle_address"]
    listing.updated_at = datetime.utcnow()
    db.flush()
    response_body = {
        "listing_id": listing.listing_id,
        "status": listing.status.value,
        "updated_at": listing.updated_at.isoformat(),
    }
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


@router.get("/listings/{listing_id}")
async def get_listing(
    request: Request,
    listing_id: str = Path(..., description="Listing ID"),
    db: Session = Depends(get_db),
):
    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="GET",
        operation="listing.get",
        resource=listing_id,
        body=canonical_query_body(request),
        allowed_roles=frozenset({"buyer", "seller", "service"}),
    )
    require_read_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    response_body = {"listing": order_to_dict(listing)}
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


@router.delete(
    "/listings/{listing_id}",
    status_code=204,
)
async def delete_listing(
    request: Request,
    listing_id: str = Path(..., description="Listing ID"),
    db: Session = Depends(get_db),
):
    """Delete one listing after exact-principal owner authorization."""

    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="DELETE",
        operation="listing.delete",
        resource=listing_id,
    )
    require_write_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay

    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if not publisher_accepts_identity(listing.publisher, authenticated.principal):
        raise HTTPException(status_code=403, detail="Publisher principal does not own listing")

    db.delete(listing)
    complete_authenticated_request(
        authenticated=authenticated,
        db=db,
        status=204,
        body=None,
    )
    db.commit()
    return signed_response(
        authenticated=authenticated,
        signer=signer,
        status=204,
        body=None,
    )
