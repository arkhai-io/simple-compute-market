"""Publisher discovery and principal-lifecycle routes."""

from __future__ import annotations

import hashlib
import time
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from market_identity import Identity, RotationRequest, canonical_rotation_bytes, verify_rotation
from pydantic import ValidationError
from sqlalchemy import desc, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.api_key_auth import require_read_access, require_write_access
from src.api.publisher_auth import (
    authenticate_publisher_request,
    cached_response,
    canonical_query_body,
    complete_authenticated_request,
    registry_authority_signer,
    signed_response,
)
from src.api.utils import (
    find_identity_binding,
    find_publisher_by_id,
    identity_is_active,
    publisher_accepts_identity,
    publisher_to_dict,
)
from src.config import settings
from src.db.database import get_db
from src.db.models import Publisher, PublisherIdentity, PublisherIdentityRotation

router = APIRouter()
_MAX_ROTATION_OVERLAP_SECONDS = 86_400


@router.get("/publishers")
async def list_publishers(
    request: Request,
    identifier: Optional[str] = Query(None),
    scheme: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
):
    """List stable publishers or resolve one exact canonical principal."""
    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="GET",
        operation="publisher.list",
        resource="publishers",
        body=canonical_query_body(request),
        allowed_roles=frozenset({"buyer", "seller", "service"}),
    )
    require_read_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay


    if (identifier is None) != (scheme is None):
        raise HTTPException(
            status_code=400,
            detail="scheme and identifier are required together",
        )
    if identifier is not None and scheme is not None:
        try:
            principal = Identity(scheme=scheme, identifier=identifier)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid publisher principal") from exc
        binding = find_identity_binding(db, principal)
        items = [publisher_to_dict(binding.publisher)] if binding is not None else []
    else:
        publishers = (
            db.query(Publisher)
            .order_by(desc(Publisher.created_at))
            .offset(offset)
            .limit(limit)
            .all()
        )
        items = [publisher_to_dict(publisher) for publisher in publishers]
    response_body = {"items": items, "count": len(items)}
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


@router.get("/publishers/{publisher_id}")
async def get_publisher(
    request: Request,
    publisher_id: int = Path(..., description="Stable publisher id"),
    db: Session = Depends(get_db),
):
    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="GET",
        operation="publisher.get",
        resource=str(publisher_id),
        body=canonical_query_body(request),
        allowed_roles=frozenset({"buyer", "seller", "service"}),
    )
    require_read_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay
    publisher = find_publisher_by_id(db, publisher_id)
    if publisher is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    response_body = publisher_to_dict(publisher)
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


def _rotation_to_dict(rotation: PublisherIdentityRotation) -> dict:
    status = rotation.status
    deadline = rotation.retire_at
    instant = (
        datetime.now(deadline.tzinfo)
        if deadline is not None and deadline.tzinfo is not None
        else datetime.utcnow()
    )
    if status == "overlap" and deadline is not None and deadline <= instant:
        status = "retired"
    return {
        "publisher_id": rotation.publisher_id,
        "nonce": rotation.nonce,
        "current": {
            "scheme": rotation.current_scheme,
            "identifier": rotation.current_identifier,
        },
        "replacement": {
            "scheme": rotation.replacement_scheme,
            "identifier": rotation.replacement_identifier,
        },
        "overlap_seconds": rotation.overlap_seconds,
        "expires_at": rotation.expires_at,
        "status": status,
        "applied_at": rotation.applied_at.isoformat(),
        "retire_at": (
            rotation.retire_at.isoformat()
            if rotation.retire_at is not None
            else None
        ),
        "retired_at": (
            rotation.retired_at.isoformat()
            if rotation.retired_at is not None
            else None
        ),
    }


@router.post(
    "/publishers/{publisher_id}/identity-rotations",
)
async def rotate_publisher_identity(
    request: Request,
    publisher_id: int = Path(..., description="Stable publisher id"),
    body: dict = Body(..., description="Two-proof rotation request"),
    db: Session = Depends(get_db),
):
    """Idempotently promote a replacement principal with bounded overlap."""

    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="POST",
        operation="publisher.identity.rotate",
        resource=str(publisher_id),
        body=body,
    )
    require_write_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay
    if db.get_bind().dialect.name == "sqlite":
        # SQLite ignores SELECT ... FOR UPDATE. End the replay lookup's read
        # transaction, then serialize the ownership transition before reading
        # the current primary.
        db.commit()
        db.execute(text("BEGIN IMMEDIATE"))
    publisher = (
        db.query(Publisher)
        .filter(Publisher.publisher_id == publisher_id)
        .with_for_update()
        .first()
    )
    if publisher is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    try:
        rotation_request = RotationRequest.model_validate(body)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Malformed rotation request") from exc

    intent = rotation_request.intent
    if authenticated.principal != intent.current:
        raise HTTPException(
            status_code=403,
            detail="Rotation caller is not current principal",
        )
    expected_authority = settings.registry_authority_id
    if expected_authority is None:
        raise HTTPException(status_code=503, detail="Registry authority unavailable")
    if (
        intent.subject != f"publisher:{publisher_id}"
        or intent.authority != expected_authority
    ):
        raise HTTPException(
            status_code=400,
            detail="Rotation authority or subject mismatch",
        )
    if intent.overlap_seconds > _MAX_ROTATION_OVERLAP_SECONDS:
        raise HTTPException(status_code=400, detail="Rotation overlap exceeds registry bound")
    verification = verify_rotation(
        rotation_request,
        now=int(time.time()),
    )
    if not verification.verified:
        raise HTTPException(status_code=401, detail="Invalid or expired rotation proofs")

    intent_hash = hashlib.sha256(canonical_rotation_bytes(intent)).hexdigest()
    existing = (
        db.query(PublisherIdentityRotation)
        .filter(
            PublisherIdentityRotation.publisher_id == publisher_id,
            PublisherIdentityRotation.nonce == intent.nonce,
        )
        .first()
    )
    if existing is not None:
        if existing.intent_hash != intent_hash:
            raise HTTPException(status_code=409, detail="Rotation nonce intent mismatch")
        response_body = _rotation_to_dict(existing)
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
    active_primaries = [
        binding
        for binding in publisher.identities
        if binding.status == "primary" and identity_is_active(binding)
    ]
    if len(active_primaries) != 1:
        raise HTTPException(
            status_code=409,
            detail="Publisher primary binding is invalid",
        )
    if any(
        binding.status == "overlap" and identity_is_active(binding)
        for binding in publisher.identities
    ):
        raise HTTPException(
            status_code=409,
            detail="Publisher already has an active identity overlap",
        )
    primary = active_primaries[0]
    if (
        primary.scheme != intent.current.scheme.value
        or primary.identifier != intent.current.identifier
    ):
        raise HTTPException(status_code=403, detail="Current principal is not primary")

    if not publisher_accepts_identity(
        publisher,
        intent.current,
        primary_only=True,
    ):
        raise HTTPException(status_code=403, detail="Current principal is not primary")
    if find_identity_binding(db, intent.replacement) is not None:
        raise HTTPException(status_code=409, detail="Replacement principal is already bound")

    current = find_identity_binding(db, intent.current)
    if current is None or current.publisher_id != publisher_id:
        raise HTTPException(status_code=403, detail="Current principal does not own publisher")

    now = datetime.utcnow()
    retire_at = now + timedelta(seconds=intent.overlap_seconds)
    if intent.overlap_seconds:
        current.status = "overlap"
        current.active_until = retire_at
    else:
        current.status = "retired"
        current.active_until = now
        current.retired_at = now

    replacement = PublisherIdentity(
        publisher_id=publisher_id,
        scheme=intent.replacement.scheme.value,
        identifier=intent.replacement.identifier,
        status="primary",
    )
    db.add(replacement)
    rotation = PublisherIdentityRotation(
        publisher_id=publisher_id,
        nonce=intent.nonce,
        intent_hash=intent_hash,
        current_scheme=intent.current.scheme.value,
        current_identifier=intent.current.identifier,
        replacement_scheme=intent.replacement.scheme.value,
        replacement_identifier=intent.replacement.identifier,
        overlap_seconds=intent.overlap_seconds,
        expires_at=intent.expires_at,
        status="overlap" if intent.overlap_seconds else "retired",
        applied_at=now,
        retire_at=retire_at,
        retired_at=now if not intent.overlap_seconds else None,
    )
    db.add(rotation)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Publisher rotation conflicts with an existing binding",
        ) from exc
    response_body = _rotation_to_dict(rotation)
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


@router.get(
    "/publishers/{publisher_id}/identity-rotations/{nonce}",
)
async def get_publisher_rotation(
    request: Request,
    publisher_id: int = Path(...),
    nonce: str = Path(...),
    db: Session = Depends(get_db),
):
    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="GET",
        operation="publisher.identity.rotation.read",
        resource=f"{publisher_id}:{nonce}",
        body=canonical_query_body(request),
        allowed_roles=frozenset({"buyer", "seller", "service"}),
    )
    require_read_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay
    rotation = (
        db.query(PublisherIdentityRotation)
        .filter(
            PublisherIdentityRotation.publisher_id == publisher_id,
            PublisherIdentityRotation.nonce == nonce,
        )
        .first()
    )
    if rotation is None:
        raise HTTPException(status_code=404, detail="Publisher rotation not found")
    response_body = _rotation_to_dict(rotation)
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


@router.post(
    "/publishers/{publisher_id}/identity-rotations/{nonce}/retire",
)
async def retire_publisher_identity(
    request: Request,
    publisher_id: int = Path(...),
    nonce: str = Path(...),
    db: Session = Depends(get_db),
):
    """Retire the overlap principal after the replacement acknowledges authority."""

    authenticated = authenticate_publisher_request(
        request=request,
        db=db,
        method="POST",
        operation="publisher.identity.retire",
        resource=f"{publisher_id}:{nonce}",
    )
    require_write_access(request, db)
    signer = registry_authority_signer(request)
    replay = cached_response(authenticated, signer=signer)
    if replay is not None:
        return replay

    rotation = (
        db.query(PublisherIdentityRotation)
        .filter(
            PublisherIdentityRotation.publisher_id == publisher_id,
            PublisherIdentityRotation.nonce == nonce,
        )
        .first()
    )
    if rotation is None:
        raise HTTPException(status_code=404, detail="Publisher rotation not found")
    replacement = Identity(
        scheme=rotation.replacement_scheme,
        identifier=rotation.replacement_identifier,
    )
    if authenticated.principal != replacement:
        raise HTTPException(status_code=403, detail="Only replacement principal may retire")
    publisher = rotation.publisher
    if not publisher_accepts_identity(publisher, replacement, primary_only=True):
        raise HTTPException(status_code=403, detail="Replacement principal is not primary")

    if rotation.status != "retired":
        current = find_identity_binding(
            db,
            Identity(
                scheme=rotation.current_scheme,
                identifier=rotation.current_identifier,
            ),
        )
        if current is None or current.publisher_id != publisher_id:
            raise HTTPException(status_code=409, detail="Rotation current binding is incomplete")
        now = datetime.utcnow()
        current.status = "retired"
        current.active_until = now
        current.retired_at = now
        rotation.status = "retired"
        rotation.retired_at = now

    response_body = _rotation_to_dict(rotation)
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
