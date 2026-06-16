"""Marketplace listing API routes.

Listings are owned by a publisher (resolved from the signing identity).
Publishing is a signed POST /listings; the publisher is created lazily on
first publish. Mutations are owner-scoped: the signature must come from the
listing's publisher identity.
"""

import logging
import time
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Path, Body, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.db.database import get_db
from src.db.models import Listing, OrderStatusEnum
from src.api.api_key_auth import require_read_access, require_write_access
from src.api.filter_eval import FilterParamError, build_criteria, evaluate_all
from src.api.filter_spec import compute_etag, get_loaded_spec
from src.api.utils import (
    Identity,
    ensure_publisher_for_identity,
    find_publisher_by_identity,
    order_to_dict,
    validate_order_status,
    verify_order_signature,
)

_MAX_TIMESTAMP_SKEW = 300  # 5 minutes


def _check_timestamp(timestamp: int) -> None:
    if abs(int(time.time()) - timestamp) > _MAX_TIMESTAMP_SKEW:
        raise HTTPException(status_code=401, detail="Timestamp too old or too far in future (max 5 minutes)")


def _publisher_signer_identity(publisher) -> Optional[Identity]:
    """The eip191 identity a listing's publisher signs with."""
    row = next((i for i in publisher.identities if i.scheme == "eip191"), None)
    return Identity(scheme=row.scheme, identifier=row.identifier) if row else None


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/listings", status_code=201, dependencies=[Depends(require_write_access)])
async def publish_listing(
    body: dict = Body(..., description="Signed marketplace listing"),
    db: Session = Depends(get_db),
):
    """Publish a marketplace listing.

    The body carries the publishing identity (``scheme`` default ``eip191``,
    ``identifier`` = the signing wallet), the listing fields, and an EIP-191
    ``signature`` over ``create_listing:<identifier>:<timestamp>``. The
    signature is the trust anchor: a publisher row is created lazily after it
    verifies. ``storefront_url`` is the publisher's storefront URL.
    """
    signature = body.pop("signature", None)
    timestamp = body.pop("timestamp", None)
    scheme = body.pop("scheme", None) or "eip191"
    identifier = body.pop("identifier", None)

    if not isinstance(identifier, str) or not identifier:
        raise HTTPException(status_code=400, detail="identifier is required")
    identity = Identity(scheme=scheme, identifier=identifier)

    if not signature or timestamp is None:
        raise HTTPException(
            status_code=401, detail="Signature and timestamp required to publish",
        )
    _check_timestamp(timestamp)
    if not verify_order_signature(
        "create_listing", identity.identifier, timestamp, signature, identity,
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")

    listing_id = body.get("listing_id")
    if not listing_id:
        raise HTTPException(status_code=400, detail="listing_id is required")

    publisher = ensure_publisher_for_identity(
        db, identity, storefront_url=body.get("storefront_url"),
    )

    existing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if existing:
        if existing.publisher_id != publisher.publisher_id:
            raise HTTPException(
                status_code=403, detail="Listing is owned by another publisher",
            )
        update_fields = {
            "offer_resource": body.get("offer_resource"),
            "accepted_escrows": body.get("accepted_escrows"),
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
            demands=body.get("demands", []),
            max_duration_seconds=body.get("max_duration_seconds"),
            oracle_address=body.get("oracle_address"),
            status=validate_order_status(body.get("status", "open")),
        )
        db.add(listing)

    db.commit()
    db.refresh(listing)

    return {
        "listing_id": listing.listing_id,
        "publisher_id": publisher.publisher_id,
        "status": listing.status.value,
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat(),
    }


_RESERVED_QUERY_PARAMS = {"status", "limit", "offset", "publisher"}


@router.get("/listings", dependencies=[Depends(require_read_access)])
async def query_listings(
    request: Request,
    status: Optional[str] = Query("open", description="Filter by listing status"),
    publisher: Optional[str] = Query(None, description="Filter by publisher signing identifier (e.g. wallet address)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    if_match: Optional[str] = Header(None, alias="If-Match"),
    db: Session = Depends(get_db),
):
    """Query marketplace listings.

    Discovery vocabulary is driven by ``filter-spec.yaml`` — any query param
    other than the reserved ones must match a declared filter name. ``?publisher=``
    narrows to one publisher (resolved from a signing identifier). Optional
    ``If-Match: <etag>`` gates the query on the buyer-cached spec version
    (412 on mismatch).
    """
    spec = get_loaded_spec()
    current_etag = compute_etag(spec)

    if if_match is not None:
        normalized = if_match.strip().lstrip("W/").strip().strip('"')
        if normalized != current_etag:
            raise HTTPException(
                status_code=412,
                detail={"error": "filter-spec etag mismatch", "current_etag": current_etag},
            )

    query = db.query(Listing)
    if status:
        query = query.filter(Listing.status == validate_order_status(status))
    if publisher:
        pub = find_publisher_by_identity(db, Identity(scheme="eip191", identifier=publisher))
        if pub is None:
            return {"items": [], "count": 0, "total_after_filter": 0}
        query = query.filter(Listing.publisher_id == pub.publisher_id)

    filter_params = {
        k: v for k, v in request.query_params.items()
        if k not in _RESERVED_QUERY_PARAMS
    }
    try:
        criteria = build_criteria(spec, filter_params)
    except FilterParamError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    rows = query.order_by(desc(Listing.created_at)).all()
    matched = [order_to_dict(row) for row in rows if evaluate_all(order_to_dict(row), criteria)]
    page = matched[offset : offset + limit]

    return {
        "items": page,
        "count": len(page),
        "total_after_filter": len(matched),
    }


@router.put("/listings/{listing_id}", dependencies=[Depends(require_write_access)])
async def update_listing(
    listing_id: str = Path(..., description="Listing ID"),
    body: dict = Body(..., description="Listing updates"),
    db: Session = Depends(get_db),
):
    """Update a listing's lifecycle status (e.g. mark closed/expired).

    Owner-scoped: the signature must come from the listing's publisher
    identity, the same gate as delete.
    """
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    signature = body.pop("signature", None)
    timestamp = body.pop("timestamp", None)

    signer = _publisher_signer_identity(listing.publisher)
    if signer is not None:
        if not signature or timestamp is None:
            raise HTTPException(
                status_code=401,
                detail="Signature and timestamp required for authenticated listings",
            )
        _check_timestamp(timestamp)
        if not verify_order_signature("update_listing", listing_id, timestamp, signature, signer):
            raise HTTPException(status_code=401, detail="Invalid signature")

    if "status" in body:
        listing.status = validate_order_status(body["status"])
    if "oracle_address" in body:
        listing.oracle_address = body["oracle_address"]
    listing.updated_at = datetime.utcnow()

    try:
        db.commit()
        db.refresh(listing)
    except Exception as e:
        db.rollback()
        logger.error(f"[REGISTRY] Failed to update listing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update listing: {e}")

    return {
        "listing_id": listing.listing_id,
        "status": listing.status.value,
        "updated_at": listing.updated_at.isoformat(),
    }


@router.get("/listings/{listing_id}", dependencies=[Depends(require_read_access)])
async def get_listing(
    listing_id: str = Path(..., description="Listing ID"),
    db: Session = Depends(get_db),
):
    """Get a single listing by ID."""
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")
    return {"listing": order_to_dict(listing)}


@router.delete("/listings/{listing_id}", status_code=204, dependencies=[Depends(require_write_access)])
async def delete_listing(
    listing_id: str = Path(..., description="Listing ID"),
    signature: Optional[str] = Query(None, description="EIP-191 signature"),
    timestamp: Optional[int] = Query(None, description="Unix timestamp of signature"),
    db: Session = Depends(get_db),
):
    """Remove a listing. Owner-scoped: signature from the publisher identity."""
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    signer = _publisher_signer_identity(listing.publisher)
    if signer is not None:
        if not signature or timestamp is None:
            raise HTTPException(status_code=401, detail="Signature and timestamp required for authenticated listings")
        _check_timestamp(timestamp)
        if not verify_order_signature("delete_listing", listing_id, timestamp, signature, signer):
            raise HTTPException(status_code=401, detail="Invalid signature")

    db.delete(listing)
    db.commit()
    return None
