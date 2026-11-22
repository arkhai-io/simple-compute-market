"""HTTP adaptation, signed responses, and durable replay leases."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import timedelta

from typing import Any
import uuid

import injected_time
from fastapi import HTTPException, Request, Response
from market_identity import (
    EMPTY_BODY,
    AuthenticatedRequest,
    CanonicalizationError,
    Identity,
    ReplayIdentity,
    ReplayReservation,
    Signer,
    TrustedIdentitySet,
    VerificationCode,
    classify_replay,
    verify_request,
)
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core_registry.api.market_auth import request_signature_fields, signed_context_response
from core_registry.db.models import PublisherReplayReservation, utcnow

_MAX_TIMESTAMP_SKEW = 300
_REPLAY_LEASE_SECONDS = 30
_MARKETPLACE_ROLES = frozenset({"buyer", "seller", "service"})


@dataclass(frozen=True)
class AuthenticatedPublisherRequest:
    request: AuthenticatedRequest
    replay: PublisherReplayReservation
    exact_retry: bool
    attempt_owner: str | None

    @property
    def principal(self) -> Identity:
        return self.request.principal


def _remember_authenticated(
    request: Request,
    db: Session,
    authenticated: AuthenticatedPublisherRequest,
) -> AuthenticatedPublisherRequest:
    request.state.authenticated_registry_request = authenticated
    request.state.authenticated_registry_db = db
    return authenticated


def _authorize_authenticated(
    request: Request,
    db: Session,
    authenticated: AuthenticatedPublisherRequest,
    allowed_roles: frozenset[str],
) -> AuthenticatedPublisherRequest:
    _remember_authenticated(request, db, authenticated)
    if authenticated.request.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="role_not_authorized")
    return authenticated


def normalize_if_match(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().removeprefix("W/").strip().strip('"')


def canonical_query_body(request: Request) -> dict[str, Any]:
    body: dict[str, Any] = {
        "query": sorted([list(item) for item in request.query_params.multi_items()])
    }
    if_match = normalize_if_match(request.headers.get("If-Match"))
    if if_match is not None:
        body["if_match"] = if_match
    return body


def authenticate_publisher_request(
    *,
    request: Request,
    db: Session,
    method: str,
    operation: str,
    resource: str,
    body: Any = EMPTY_BODY,
    allowed_roles: frozenset[str] = frozenset({"seller"}),
) -> AuthenticatedPublisherRequest:
    try:
        envelope_data = request_signature_fields(
            request.headers, method=method, operation=operation, resource=resource, body=body
        )
    except CanonicalizationError as exc:
        raise HTTPException(status_code=400, detail="Body is not canonical JSON") from exc
    role = envelope_data["role"]
    if role not in _MARKETPLACE_ROLES:
        raise HTTPException(status_code=401, detail="context_mismatch")
    try:
        claimed = Identity.model_validate(envelope_data["principal"])
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="malformed_envelope") from exc
    replay_row = db.query(PublisherReplayReservation).filter(
        PublisherReplayReservation.principal_scheme == claimed.scheme.value,
        PublisherReplayReservation.principal_identifier == claimed.identifier,
        PublisherReplayReservation.request_id == envelope_data["request_id"],
    ).first()
    verification_now = injected_time.now()
    result = verify_request(
        envelope_data,
        body=body,
        now=verification_now,
        max_skew=_MAX_TIMESTAMP_SKEW,
        expected_role=role,
        expected_method=method,
        expected_operation=operation,
        expected_resource=resource,
        expected_principals=TrustedIdentitySet(identities=(claimed,)),
    )
    if result.code != VerificationCode.VERIFIED or result.reservation is None:
        raise HTTPException(status_code=401, detail=result.code.value)

    authenticated = AuthenticatedRequest.model_validate(envelope_data)
    attempt_owner = uuid.uuid4().hex
    now = utcnow()
    lease_expires_at = now + timedelta(seconds=_REPLAY_LEASE_SECONDS)
    if replay_row is None:
        replay_row = PublisherReplayReservation(
            principal_scheme=authenticated.principal.scheme.value,
            principal_identifier=authenticated.principal.identifier,
            request_id=authenticated.request_id,
            request_hash=result.reservation.request_hash,
            lease_owner=attempt_owner,
            lease_expires_at=lease_expires_at,
        )
        db.add(replay_row)
        try:
            db.commit()
            db.refresh(replay_row)
            return _authorize_authenticated(
                request,
                db,
                AuthenticatedPublisherRequest(authenticated, replay_row, False, attempt_owner),
                allowed_roles,
            )
        except IntegrityError:
            db.rollback()
            replay_row = db.query(PublisherReplayReservation).filter(
                PublisherReplayReservation.principal_scheme == authenticated.principal.scheme.value,
                PublisherReplayReservation.principal_identifier == authenticated.principal.identifier,
                PublisherReplayReservation.request_id == authenticated.request_id,
            ).one()

    existing = ReplayReservation(
        identity=ReplayIdentity(principal=authenticated.principal, request_id=replay_row.request_id),
        request_hash=replay_row.request_hash,
    )
    replay = classify_replay(authenticated, existing)
    if replay.code.value == "changed_reuse":
        _remember_authenticated(request, db, AuthenticatedPublisherRequest(authenticated, replay_row, False, None))
        raise HTTPException(status_code=409, detail="changed_reuse")
    if replay_row.completed_at is not None:
        return _authorize_authenticated(
            request,
            db,
            AuthenticatedPublisherRequest(authenticated, replay_row, True, None),
            allowed_roles,
        )

    acquired = db.query(PublisherReplayReservation).filter(
        PublisherReplayReservation.id == replay_row.id,
        PublisherReplayReservation.completed_at.is_(None),
        or_(PublisherReplayReservation.lease_expires_at.is_(None), PublisherReplayReservation.lease_expires_at <= now),
    ).update(
        {
            PublisherReplayReservation.lease_owner: attempt_owner,
            PublisherReplayReservation.lease_expires_at: lease_expires_at,
        },
        synchronize_session=False,
    )
    if acquired != 1:
        _remember_authenticated(request, db, AuthenticatedPublisherRequest(authenticated, replay_row, False, None))
        db.rollback()
        raise HTTPException(status_code=409, detail="request_in_progress")
    db.commit()
    replay_row = db.query(PublisherReplayReservation).filter(PublisherReplayReservation.id == replay_row.id).one()
    return _authorize_authenticated(
        request,
        db,
        AuthenticatedPublisherRequest(authenticated, replay_row, False, attempt_owner),
        allowed_roles,
    )


async def retained_request_evidence(
    request: Request, authenticated: AuthenticatedPublisherRequest
) -> dict[str, Any]:
    """Retain transport bytes and the envelope that binds their canonical JSON hash."""
    return {
        "body_base64": base64.b64encode(await request.body()).decode("ascii"),
        "request": authenticated.request.model_dump(mode="json"),
    }


def signed_response(*, authenticated: AuthenticatedPublisherRequest, signer: Signer, status: int, body: dict[str, Any] | None) -> Response:
    request = authenticated.request
    return signed_context_response(
        method=request.method, operation=request.operation,
        resource=request.resource, request_id=request.request_id,
        signer=signer, status=status, body=body,
    )


def cached_response(authenticated: AuthenticatedPublisherRequest, *, signer: Signer) -> Response | None:
    if not authenticated.exact_retry:
        return None
    status = authenticated.replay.response_status
    if status is None:
        raise HTTPException(status_code=409, detail="request_in_progress")
    return signed_response(authenticated=authenticated, signer=signer, status=status, body=authenticated.replay.response_body)


def complete_authenticated_request(*, authenticated: AuthenticatedPublisherRequest, db: Session, status: int, body: dict[str, Any] | None) -> None:
    if authenticated.attempt_owner is None:
        raise HTTPException(status_code=409, detail="request_lease_lost")
    updated = db.query(PublisherReplayReservation).filter(
        PublisherReplayReservation.id == authenticated.replay.id,
        PublisherReplayReservation.completed_at.is_(None),
        PublisherReplayReservation.lease_owner == authenticated.attempt_owner,
    ).update(
        {
            PublisherReplayReservation.response_status: status,
            PublisherReplayReservation.response_body: body,
            PublisherReplayReservation.completed_at: utcnow(),
            PublisherReplayReservation.lease_owner: None,
            PublisherReplayReservation.lease_expires_at: None,
        },
        synchronize_session=False,
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="request_lease_lost")


def complete_authenticated_error(*, authenticated: AuthenticatedPublisherRequest, db: Session, error: HTTPException) -> None:
    if not 400 <= error.status_code < 500 or authenticated.attempt_owner is None:
        return
    db.rollback()
    updated = db.query(PublisherReplayReservation).filter(
        PublisherReplayReservation.id == authenticated.replay.id,
        PublisherReplayReservation.completed_at.is_(None),
        PublisherReplayReservation.lease_owner == authenticated.attempt_owner,
    ).update(
        {
            PublisherReplayReservation.response_status: error.status_code,
            PublisherReplayReservation.response_body: {"detail": error.detail},
            PublisherReplayReservation.completed_at: utcnow(),
            PublisherReplayReservation.lease_owner: None,
            PublisherReplayReservation.lease_expires_at: None,
        },
        synchronize_session=False,
    )
    if updated == 1:
        db.commit()
    else:
        db.rollback()
