"""Operator-facing storefront identity rotation and status services."""

from __future__ import annotations

from urllib.parse import quote, urlencode

from market_identity import Identity, RotationRequest

from core_storefront.identity_authority import (
    ADMINISTRATOR_AUTHORITY,
    SERVICE_PEER_AUTHORITY,
    IdentityAuthorityError,
    IdentitySubjectStatus,
    StorefrontIdentityAuthority,
)
from core_storefront.models.system_models import (
    IdentityBindingResponse,
    IdentityRetirementRequest,
    IdentityStatusResponse,
)

_ALLOWED_AUTHORITIES = frozenset(
    {ADMINISTRATOR_AUTHORITY, SERVICE_PEER_AUTHORITY}
)
_EXPECTED_ROLES = {
    ADMINISTRATOR_AUTHORITY: "admin",
    SERVICE_PEER_AUTHORITY: "service",
}


def identity_subject_resource(authority: str, subject: str) -> str:
    """Return the unambiguous canonical resource for a subject mutation."""

    _require_authority(authority)
    if not isinstance(subject, str) or not subject or "\x00" in subject:
        raise IdentityAuthorityError("identity subject is malformed")
    return f"{quote(authority, safe='')}/{quote(subject, safe='')}"


def identity_status_resource(authority: str, subject: str) -> str:
    """Return the canonical effective-query resource for status inspection."""

    _require_authority(authority)
    if not isinstance(subject, str) or not subject or "\x00" in subject:
        raise IdentityAuthorityError("identity subject is malformed")
    query = urlencode(
        sorted({"authority": authority, "subject": subject}.items()),
        quote_via=quote,
        safe="",
    )
    return f"identity-status?{query}"


def rotate_identity(
    authority_store: StorefrontIdentityAuthority,
    *,
    request: RotationRequest,
    operator: Identity,
    now: int,
) -> IdentityStatusResponse:
    """Apply one bounded canonical two-proof rotation."""

    _require_subject(
        authority_store,
        authority=request.intent.authority,
        subject=request.intent.subject,
    )
    status = authority_store.apply_rotation(request, operator=operator, now=now)
    return identity_status_response(status, now=now)


def retire_rotated_identity(
    authority_store: StorefrontIdentityAuthority,
    *,
    request: IdentityRetirementRequest,
    operator: Identity,
    now: int,
) -> IdentityStatusResponse:
    """Retire only the old principal from the named applied rotation."""

    _require_subject(
        authority_store,
        authority=request.authority,
        subject=request.subject,
    )
    status = authority_store.complete_rotation(
        authority=request.authority,
        subject=request.subject,
        rotation_nonce=request.rotation_nonce,
        principal=request.principal,
        operator=operator,
        now=now,
    )
    return identity_status_response(status, now=now)


def inspect_identity(
    authority_store: StorefrontIdentityAuthority,
    *,
    authority: str,
    subject: str,
    now: int,
) -> IdentityStatusResponse:
    """Inspect one supported administrator or service-peer subject."""

    status = _require_subject(
        authority_store,
        authority=authority,
        subject=subject,
    )
    return identity_status_response(status, now=now)


def identity_status_response(
    status: IdentitySubjectStatus,
    *,
    now: int,
) -> IdentityStatusResponse:
    """Freeze durable status with activity evaluated at one instant."""

    primary = status.primary
    if primary is None:
        raise IdentityAuthorityError("identity subject has no primary principal")
    return IdentityStatusResponse(
        authority=status.authority,
        subject=status.subject,
        role=status.role,
        bindings=tuple(
            IdentityBindingResponse(
                principal=binding.principal,
                status=binding.status,
                overlap_until=binding.overlap_until,
                active=binding.active_at(now),
            )
            for binding in status.bindings
        ),
        primary=primary,
        observed_at=now,
    )


def _require_subject(
    authority_store: StorefrontIdentityAuthority,
    *,
    authority: str,
    subject: str,
) -> IdentitySubjectStatus:
    _require_authority(authority)
    try:
        status = authority_store.status(authority=authority, subject=subject)
    except KeyError as exc:
        raise IdentityAuthorityError("identity subject is not registered") from exc
    if status.role != _EXPECTED_ROLES[authority]:
        raise IdentityAuthorityError("identity subject role conflicts with its authority")
    return status


def _require_authority(authority: str) -> None:
    if authority not in _ALLOWED_AUTHORITIES:
        raise IdentityAuthorityError("identity authority is not operator-manageable")
