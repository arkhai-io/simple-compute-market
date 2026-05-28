"""Marketplace listing API routes.

Wire vocabulary and DB column names are now in sync (post-Slice 4):
``listing_id`` / ``seller`` / ``buyer`` / ``seller_attestation`` /
``buyer_attestation``. No translation layer.
"""

import logging
import time
from typing import Any, Optional
from datetime import datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Path, Body, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.db.database import get_db
from src.db.models import Agent, Listing, OrderStatusEnum
from src.api.api_key_auth import require_read_access, require_write_access
from src.api.filter_eval import FilterParamError, build_criteria, evaluate_all
from src.api.filter_spec import compute_etag, get_loaded_spec
from src.api.utils import (
    Identity,
    ensure_agent_for_eip191,
    find_agent_by_id,
    find_agent_by_identity,
    order_to_dict,
    validate_order_status,
    verify_order_signature,
)


def _looks_like_eip191_address(s: str) -> bool:
    """A raw 0x-prefixed 42-character hex string is an EVM address."""
    if not s.startswith("0x") or len(s) != 42:
        return False
    try:
        int(s, 16)
    except ValueError:
        return False
    return True

_MAX_TIMESTAMP_SKEW = 300  # 5 minutes


def _check_timestamp(timestamp: int) -> None:
    if abs(int(time.time()) - timestamp) > _MAX_TIMESTAMP_SKEW:
        raise HTTPException(status_code=401, detail="Timestamp too old or too far in future (max 5 minutes)")

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post(
    "/agents/{agent_id}/listings",
    status_code=201,
    dependencies=[Depends(require_write_access)],
)
async def publish_listing(
    agent_id: str = Path(..., description="EIP-191 wallet address (0x...)"),
    body: dict = Body(..., description="Marketplace listing data"),
    db: Session = Depends(get_db),
):
    """Publish a marketplace listing to the registry.

    ``agent_id`` is an EIP-191 wallet address. The signed publication
    itself is the trust anchor — a missing row is created lazily after
    the signature verifies (no on-chain lookup needed).
    """
    signature = body.pop("signature", None)
    timestamp = body.pop("timestamp", None)

    if _looks_like_eip191_address(agent_id):
        # EIP-191 path: signature recovery is the trust anchor; row is
        # created lazily after the signature verifies.
        identity = Identity(scheme="eip191", identifier=agent_id)
        if not signature or timestamp is None:
            raise HTTPException(
                status_code=401,
                detail="Signature and timestamp required for authenticated agents",
            )
        _check_timestamp(timestamp)
        if not verify_order_signature(
            "create_listing", identity.identifier, timestamp, signature, identity,
        ):
            raise HTTPException(status_code=401, detail="Invalid signature")
        agent = ensure_agent_for_eip191(db, identity.identifier)
    else:
        # Legacy back-compat: agents pre-Phase-4 backfilled rows carry an
        # eip155:... canonical agent_id. Look up by that column and verify
        # against the cached owner.
        agent = find_agent_by_id(db, agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        if agent.owner:
            if not signature or timestamp is None:
                raise HTTPException(
                    status_code=401,
                    detail="Signature and timestamp required for authenticated agents",
                )
            _check_timestamp(timestamp)
            if not verify_order_signature(
                "create_listing", agent.agent_id, timestamp, signature, agent.owner,
            ):
                raise HTTPException(status_code=401, detail="Invalid signature")

    # Listings FK on the ``agents.agent_id`` column. Lazy-created eip191
    # rows get a synthetic ``eip191:<identifier>`` value so the FK holds.
    if agent.agent_id is None:
        agent.agent_id = f"eip191:{agent.identifier}"
        db.commit()
        db.refresh(agent)

    agent_id_for_listing = agent.agent_id

    listing_id = body.get("listing_id")
    if not listing_id:
        raise HTTPException(status_code=400, detail="listing_id is required")

    existing = db.query(Listing).filter(Listing.listing_id == listing_id).first()

    if existing:
        update_fields = {
            "seller": body.get("seller"),
            "offer_resource": body.get("offer_resource"),
            "accepted_escrows": body.get("accepted_escrows"),
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
        status_str = body.get("status", "open")
        listing = Listing(
            listing_id=listing_id,
            agent_id=agent_id_for_listing,
            seller=body.get("seller", ""),
            buyer=body.get("buyer"),
            offer_resource=body.get("offer_resource", {}),
            accepted_escrows=body.get("accepted_escrows", []),
            max_duration_seconds=body.get("max_duration_seconds"),
            oracle_address=body.get("oracle_address"),
            status=validate_order_status(status_str),
        )
        db.add(listing)

    db.commit()
    db.refresh(listing)

    return {
        "listing_id": listing.listing_id,
        "agentId": agent.agent_id,
        "status": listing.status.value,
        "created_at": listing.created_at.isoformat(),
        "updated_at": listing.updated_at.isoformat(),
    }


@router.get("/agents/{agent_id}/listings", dependencies=[Depends(require_read_access)])
async def get_agent_listings(
    agent_id: str = Path(..., description="EIP-191 wallet address (0x...) or legacy canonical ID"),
    status: Optional[str] = Query(None, description="Filter by listing status"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """List marketplace listings for a specific agent."""
    agent = find_agent_by_id(db, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    query = db.query(Listing).filter(Listing.agent_id == agent.agent_id)

    if status:
        status_enum = validate_order_status(status)
        query = query.filter(Listing.status == status_enum)

    listings = query.order_by(desc(Listing.created_at)).offset(offset).limit(limit).all()

    return {
        "items": [order_to_dict(listing) for listing in listings],
        "count": len(listings),
    }


_RESERVED_QUERY_PARAMS = {"status", "limit", "offset"}


@router.get("/listings", dependencies=[Depends(require_read_access)])
async def query_listings(
    request: Request,
    status: Optional[str] = Query("open", description="Filter by listing status"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    if_match: Optional[str] = Header(None, alias="If-Match"),
    db: Session = Depends(get_db),
):
    """Query marketplace listings.

    Discovery vocabulary is driven by ``filter-spec.yaml`` — any other
    query param must match a declared filter name.  Unknown params get
    a 400 with the offending name.  Optional ``If-Match: <etag>`` gates
    the query on the buyer-cached spec version (412 on mismatch, with
    the current etag in the response body so the buyer can refresh).
    """
    spec = get_loaded_spec()
    current_etag = compute_etag(spec)

    if if_match is not None:
        # RFC 7232 allows quoted etags ("abc...") and W/-prefixed weak forms.
        # Strip surrounding quotes for the comparison.
        normalized = if_match.strip().lstrip("W/").strip().strip('"')
        if normalized != current_etag:
            raise HTTPException(
                status_code=412,
                detail={
                    "error": "filter-spec etag mismatch",
                    "current_etag": current_etag,
                },
            )

    filter_params = {
        k: v for k, v in request.query_params.items()
        if k not in _RESERVED_QUERY_PARAMS
    }
    try:
        criteria = build_criteria(spec, filter_params)
    except FilterParamError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    query = db.query(Listing)
    if status:
        query = query.filter(Listing.status == validate_order_status(status))

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
    """Update a listing's lifecycle status (e.g. mark accepted/closed).

    Owner-scoped: when the seller agent has an owner, the signature must
    come from that owner wallet — the same gate as delete. Listings are
    fungible and buyers attach to negotiation threads rather than to a
    listing, so there is no buyer-side update path.
    """
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()

    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    signature = body.pop("signature", None)
    timestamp = body.pop("timestamp", None)

    seller_agent = find_agent_by_id(db, listing.agent_id)
    if seller_agent and seller_agent.owner:
        if not signature or timestamp is None:
            raise HTTPException(
                status_code=401,
                detail="Signature and timestamp required for authenticated listings",
            )
        _check_timestamp(timestamp)
        if not verify_order_signature("update_listing", listing_id, timestamp, signature, seller_agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    if "status" in body:
        listing.status = validate_order_status(body["status"])
    if "buyer" in body:
        listing.buyer = body["buyer"]
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

    return {
        "listing": order_to_dict(listing),
    }


@router.delete(
    "/listings/{listing_id}",
    status_code=204,
    dependencies=[Depends(require_write_access)],
)
async def delete_listing(
    listing_id: str = Path(..., description="Listing ID"),
    signature: Optional[str] = Query(None, description="EIP-191 signature"),
    timestamp: Optional[int] = Query(None, description="Unix timestamp of signature"),
    db: Session = Depends(get_db),
):
    """Remove a listing from the registry. Requires signature from the listing seller's owner."""
    listing = db.query(Listing).filter(Listing.listing_id == listing_id).first()

    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    seller_agent = find_agent_by_id(db, listing.agent_id)
    if seller_agent and seller_agent.owner:
        if not signature or timestamp is None:
            raise HTTPException(status_code=401, detail="Signature and timestamp required for authenticated listings")
        _check_timestamp(timestamp)
        if not verify_order_signature("delete_listing", listing_id, timestamp, signature, seller_agent.owner):
            raise HTTPException(status_code=401, detail="Invalid signature")

    db.delete(listing)
    db.commit()

    return None
