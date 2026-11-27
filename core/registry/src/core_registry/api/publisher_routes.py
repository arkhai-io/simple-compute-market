"""Publisher discovery and principal-lifecycle routes.

Every route re-runs an exact retry. Rotation and retirement are keyed by the
rotation's nonce, so a retry after any later write finds the rotation it applied
and changes nothing; each answers that rotation before the checks that govern
applying a new intent, so a caller who lost its acknowledgement learns what
happened however late its retry arrives.
"""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Optional

import injected_time
from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from market_authenticated_requests import Admitted, RouteAdmission, path_resource
from market_identity import ExactRetry, Identity, RotationRequest, canonical_rotation_bytes, verify_rotation
from pydantic import ValidationError
from sqlalchemy import desc, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core_registry.api.admission import READ_ROLES, WRITE_ROLES, registry_core
from core_registry.api.api_key_auth import require_read_access, require_write_access
from core_registry.api.utils import (
    find_identity_binding,
    find_publisher_by_id,
    identity_is_active,
    instant_comparable_with,
    publisher_accepts_identity,
    publisher_to_dict,
)
from core_registry.config import settings
from core_registry.db.database import get_db
from core_registry.db.models import (
    Publisher,
    PublisherIdentity,
    PublisherIdentityRotation,
    utcnow,
)

router = APIRouter()
_MAX_ROTATION_OVERLAP_SECONDS = 86_400


def _rotation_resource(path_params: dict[str, str], body: bytes) -> str:
    """A rotation's identifier: its publisher and its nonce."""

    return f"{path_params['publisher_id']}:{path_params['nonce']}"


@router.get("/publishers")
async def list_publishers(
    request: Request,
    identifier: Optional[str] = Query(None),
    scheme: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    admitted: Admitted = Depends(
        RouteAdmission(registry_core, operation="publisher.list", roles=READ_ROLES, exact_retry=ExactRetry.RERUN)
    ),
    db: Session = Depends(get_db),
):
    """List stable publishers or resolve one exact canonical principal."""
    require_read_access(request, db)

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
            # Whole-second times tie; the publisher id is insertion order.
            .order_by(desc(Publisher.created_at), desc(Publisher.publisher_id))
            .offset(offset)
            .limit(limit)
            .all()
        )
        items = [publisher_to_dict(publisher) for publisher in publishers]
    return {"items": items, "count": len(items)}


@router.get("/publishers/{publisher_id}")
async def get_publisher(
    request: Request,
    publisher_id: int = Path(..., description="Stable publisher id"),
    admitted: Admitted = Depends(
        RouteAdmission(
            registry_core,
            operation="publisher.get",
            roles=READ_ROLES,
            exact_retry=ExactRetry.RERUN,
            resource=path_resource("publisher_id"),
        )
    ),
    db: Session = Depends(get_db),
):
    require_read_access(request, db)
    publisher = find_publisher_by_id(db, publisher_id)
    if publisher is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    return publisher_to_dict(publisher)


def _rotation_to_dict(rotation: PublisherIdentityRotation) -> dict:
    status = rotation.status
    deadline = rotation.retire_at
    instant = instant_comparable_with(deadline)
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
    admitted: Admitted = Depends(
        RouteAdmission(
            registry_core,
            operation="publisher.identity.rotate",
            roles=WRITE_ROLES,
            exact_retry=ExactRetry.RERUN,
            resource=path_resource("publisher_id"),
        )
    ),
    body: dict = Body(..., description="Two-proof rotation request"),
    db: Session = Depends(get_db),
):
    """Idempotently promote a replacement principal with bounded overlap."""

    require_write_access(request, db)
    if db.get_bind().dialect.name == "sqlite":
        # SQLite ignores SELECT ... FOR UPDATE. End the read transaction the
        # access check opened, then serialize the ownership transition before
        # reading the current primary.
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
    if admitted.request.principal != intent.current:
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

    # An applied intent is answered before the checks that govern applying one --
    # its proofs' expiry, the caller's primary status, an active overlap -- so its
    # exact retry, however late and after whatever later rotation, learns what
    # applied. Only the principal the intent names as current reaches here, and
    # only the very intent the registry verified matches its hash.
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
        return _rotation_to_dict(existing)

    if intent.overlap_seconds > _MAX_ROTATION_OVERLAP_SECONDS:
        raise HTTPException(status_code=400, detail="Rotation overlap exceeds registry bound")
    verification = verify_rotation(
        rotation_request,
        now=injected_time.now(),
    )
    if not verification.verified:
        raise HTTPException(status_code=401, detail="Invalid or expired rotation proofs")

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

    now = utcnow()
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
    db.commit()
    return response_body


@router.get(
    "/publishers/{publisher_id}/identity-rotations/{nonce}",
)
async def get_publisher_rotation(
    request: Request,
    publisher_id: int = Path(...),
    nonce: str = Path(...),
    admitted: Admitted = Depends(
        RouteAdmission(
            registry_core,
            operation="publisher.identity.rotation.read",
            roles=READ_ROLES,
            exact_retry=ExactRetry.RERUN,
            resource=_rotation_resource,
        )
    ),
    db: Session = Depends(get_db),
):
    require_read_access(request, db)
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
    return _rotation_to_dict(rotation)


@router.post(
    "/publishers/{publisher_id}/identity-rotations/{nonce}/retire",
)
async def retire_publisher_identity(
    request: Request,
    publisher_id: int = Path(...),
    nonce: str = Path(...),
    admitted: Admitted = Depends(
        RouteAdmission(
            registry_core,
            operation="publisher.identity.retire",
            roles=WRITE_ROLES,
            exact_retry=ExactRetry.RERUN,
            resource=_rotation_resource,
        )
    ),
    db: Session = Depends(get_db),
):
    """Retire the overlap principal after the replacement acknowledges authority."""

    require_write_access(request, db)
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
    if admitted.request.principal != replacement:
        raise HTTPException(status_code=403, detail="Only replacement principal may retire")
    # A retired rotation is answered as it stands, before the primary check that
    # governs retiring one, so a retirement's exact retry after the replacement
    # rotated again learns that it applied.
    if rotation.status == "retired":
        return _rotation_to_dict(rotation)
    publisher = rotation.publisher
    if not publisher_accepts_identity(publisher, replacement, primary_only=True):
        raise HTTPException(status_code=403, detail="Replacement principal is not primary")

    current = find_identity_binding(
        db,
        Identity(
            scheme=rotation.current_scheme,
            identifier=rotation.current_identifier,
        ),
    )
    if current is None or current.publisher_id != publisher_id:
        raise HTTPException(status_code=409, detail="Rotation current binding is incomplete")
    now = utcnow()
    current.status = "retired"
    current.active_until = now
    current.retired_at = now
    rotation.status = "retired"
    rotation.retired_at = now
    response_body = _rotation_to_dict(rotation)
    db.commit()
    return response_body
