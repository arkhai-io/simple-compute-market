"""Publisher read routes.

A publisher is the principal that owns listings, identified by one or more
signing identities. These endpoints expose the entity itself
(storefront_url + identities); listings are read via the listing routes.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Path
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.db.database import get_db
from src.db.models import Publisher, PublisherIdentity
from src.api.api_key_auth import require_read_access
from src.api.utils import find_publisher_by_id, publisher_to_dict

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/publishers", dependencies=[Depends(require_read_access)])
async def list_publishers(
    identifier: Optional[str] = Query(None, description="Resolve a publisher by a signing identifier (e.g. wallet address)"),
    scheme: Optional[str] = Query(None, description="Restrict the identifier match to a scheme (default eip191 semantics)"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """List publishers, or resolve one by a signing identity.

    With ``?identifier=`` the result is the publisher owning that identity
    (eip191 identifiers are matched case-insensitively); without it, a
    paginated list of publishers.
    """
    if identifier is not None:
        ident = identifier.lower() if (scheme or "eip191") == "eip191" else identifier
        q = db.query(PublisherIdentity).filter(PublisherIdentity.identifier == ident)
        if scheme:
            q = q.filter(PublisherIdentity.scheme == scheme)
        row = q.first()
        items = [publisher_to_dict(row.publisher)] if row is not None else []
        return {"items": items, "count": len(items)}

    publishers = (
        db.query(Publisher)
        .order_by(desc(Publisher.created_at))
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [publisher_to_dict(p) for p in publishers]
    return {"items": items, "count": len(items)}


@router.get("/publishers/{publisher_id}", dependencies=[Depends(require_read_access)])
async def get_publisher(
    publisher_id: int = Path(..., description="Surrogate publisher id"),
    db: Session = Depends(get_db),
):
    """Get a publisher entity: storefront_url + identities + created_at."""
    publisher = find_publisher_by_id(db, publisher_id)
    if not publisher:
        raise HTTPException(status_code=404, detail="Publisher not found")
    return publisher_to_dict(publisher)
