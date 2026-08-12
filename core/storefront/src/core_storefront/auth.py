"""Framework-neutral storefront authentication over the marketplace v2 contract."""

from __future__ import annotations

import time
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol, runtime_checkable

from market_identity import (
    EMPTY_BODY,
    REQUEST_PROTOCOL,
    RESPONSE_PROTOCOL,
    AuthenticatedRequest,
    AuthenticatedResponse,
    Identity,
    ReplayReservation,
    ResponseEnvelope,
    SignatureProof,
    TrustedIdentitySet,
    Signer,
    VerificationCode,
    canonical_body_hash,
    sign_response,
    verify_request,
    verify_response,
)

DEFAULT_MAX_TIMESTAMP_SKEW = 300
DEFAULT_REPLAY_LEASE_SECONDS = 300

SIGNATURE_VERSION_HEADER = "X-Market-Signature-Version"
IDENTITY_SCHEME_HEADER = "X-Market-Identity-Scheme"
IDENTITY_IDENTIFIER_HEADER = "X-Market-Identity-Identifier"
ROLE_HEADER = "X-Market-Role"
REQUEST_ID_HEADER = "X-Market-Request-ID"
TIMESTAMP_HEADER = "X-Market-Timestamp"
SIGNATURE_HEADER = "X-Market-Signature"


@dataclass
class AuthError(ValueError):
    """Authentication failure with an HTTP-friendly status code."""

    detail: str
    status_code: int = 403

    def __str__(self) -> str:
        return self.detail



@dataclass(frozen=True)
class ReplayClaim:
    """Atomic replay-row claim made after cryptographic verification."""

    state: Literal["dispatch", "pending", "completed", "changed"]
    reservation: ReplayReservation
    attempt_token: str | None = None
    recorded_outcome: tuple[int, Any] | None = None

@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Verified request identity and replay classification for route dispatch."""

    principal: Identity
    role: str
    request_id: str
    timestamp: int
    reservation: ReplayReservation
    recorded_outcome: tuple[int, Any] | None
    exact_retry: bool
    attempt_token: str | None

    @property
    def dispatch_allowed(self) -> bool:
        return not self.exact_retry and self.attempt_token is not None


@runtime_checkable
class ReplayStore(Protocol):
    """Authority-owned atomic replay persistence used before route dispatch."""

    async def get_replay_reservation(
        self,
        principal: Identity,
        request_id: str,
    ) -> ReplayReservation | None: ...

    async def claim_replay(
        self,
        reservation: ReplayReservation,
        *,
        now: int,
        lease_seconds: int,
    ) -> ReplayClaim:
        """Atomically reserve, recover, or classify one verified request."""



def _required_header(headers: Mapping[str, str], name: str) -> str:
    value = headers.get(name)
    if not isinstance(value, str) or not value:
        raise AuthError(f"Missing {name} header", status_code=401)
    return value


def _timestamp(headers: Mapping[str, str]) -> int:
    raw = _required_header(headers, TIMESTAMP_HEADER)
    try:
        return int(raw)
    except ValueError as exc:
        raise AuthError(f"Invalid {TIMESTAMP_HEADER} header", status_code=400) from exc


def _request_from_headers(
    *,
    headers: Mapping[str, str],
    method: str,
    operation: str,
    resource: str,
    body: Any,
) -> AuthenticatedRequest:
    protocol = _required_header(headers, SIGNATURE_VERSION_HEADER)
    if protocol != REQUEST_PROTOCOL:
        raise AuthError("Unsupported marketplace request signature version", status_code=401)
    try:
        principal = Identity(
            scheme=_required_header(headers, IDENTITY_SCHEME_HEADER),
            identifier=_required_header(headers, IDENTITY_IDENTIFIER_HEADER),
        )
        return AuthenticatedRequest(
            protocol=protocol,
            role=_required_header(headers, ROLE_HEADER),
            principal=principal,
            method=method,
            operation=operation,
            resource=resource,
            request_id=_required_header(headers, REQUEST_ID_HEADER),
            timestamp=_timestamp(headers),
            body_hash=canonical_body_hash(body),
            proof=SignatureProof(
                scheme=principal.scheme,
                value=_required_header(headers, SIGNATURE_HEADER),
            ),
        )
    except AuthError:
        raise
    except (TypeError, ValueError) as exc:
        raise AuthError("Malformed marketplace request authentication", status_code=400) from exc




async def authenticate_request(
    *,
    headers: Mapping[str, str],
    method: str,
    operation: str,
    resource: str,
    body: Any = EMPTY_BODY,
    expected_role: str,
    replay_store: ReplayStore,
    expected_principal: Identity | None = None,
    allowed_principals: Collection[Identity] | None = None,
    now: int | None = None,
    max_timestamp_skew: int = DEFAULT_MAX_TIMESTAMP_SKEW,
    replay_lease_seconds: int = DEFAULT_REPLAY_LEASE_SECONDS,
) -> AuthenticatedPrincipal:
    """Verify an exact role/principal binding and reserve replay before dispatch.

    Authorities must supply either one expected principal or the complete active
    principal set for a rotating subject. An exact retry is authenticated but has
    ``dispatch_allowed == False`` so a route can return its recorded outcome
    without executing the mutation again.
    """

    if (expected_principal is None) == (allowed_principals is None):
        raise ValueError("supply exactly one principal trust binding")
    if replay_lease_seconds <= 0:
        raise ValueError("replay lease must be positive")
    envelope = _request_from_headers(
        headers=headers,
        method=method,
        operation=operation,
        resource=resource,
        body=body,
    )
    if expected_principal is not None:
        expected_principals = TrustedIdentitySet(
            identities=(expected_principal,)
        )
    else:
        assert allowed_principals is not None
        if envelope.principal not in allowed_principals:
            raise AuthError("Marketplace principal is not active for this subject")
        expected_principals = TrustedIdentitySet(
            identities=(envelope.principal,)
        )

    # Verify every arriving proof, including retries, against current freshness.
    # Replay identity deliberately excludes timestamp and proof so a caller can
    # safely re-sign the same semantic request after process restart.
    signature_result = verify_request(
        envelope,
        body=body,
        now=int(time.time()) if now is None else now,
        max_skew=max_timestamp_skew,
        expected_role=expected_role,
        expected_method=method,
        expected_operation=operation,
        expected_resource=resource,
        expected_principals=expected_principals,
    )
    if not signature_result.verified or signature_result.reservation is None:
        raise _verification_error(signature_result.code)
    reservation = signature_result.reservation

    existing = await replay_store.get_replay_reservation(
        envelope.principal,
        envelope.request_id,
    )
    if existing is not None and existing.request_hash != reservation.request_hash:
        raise AuthError(
            "Request ID was reused with changed signed content",
            status_code=409,
        )
    claim = await replay_store.claim_replay(
        reservation,
        now=int(time.time()) if now is None else now,
        lease_seconds=replay_lease_seconds,
    )
    if claim.state == "changed":
        raise AuthError(
            "Request ID was reused with changed signed content",
            status_code=409,
        )
    exact_retry = claim.state in {"pending", "completed"}
    recorded_outcome = claim.recorded_outcome

    return AuthenticatedPrincipal(
        principal=envelope.principal,
        role=envelope.role,
        request_id=envelope.request_id,
        timestamp=envelope.timestamp,
        reservation=claim.reservation,
        recorded_outcome=recorded_outcome,
        attempt_token=claim.attempt_token,
        exact_retry=exact_retry,
    )


def signed_response_headers(
    *,
    signer: Signer,
    role: str,
    method: str,
    operation: str,
    resource: str,
    request_id: str,
    status: int,
    body: Any = EMPTY_BODY,
    timestamp: int | None = None,
) -> dict[str, str]:
    """Sign a response for a caller that pins this authority principal."""

    envelope = ResponseEnvelope(
        role=role,
        principal=signer.identity,
        method=method,
        operation=operation,
        resource=resource,
        request_id=request_id,
        timestamp=int(time.time()) if timestamp is None else timestamp,
        status=status,
        body_hash=canonical_body_hash(body),
    )
    authenticated = sign_response(signer=signer, envelope=envelope)
    return _response_headers(authenticated)


def verify_authenticated_response(
    *,
    headers: Mapping[str, str],
    expected_principals: TrustedIdentitySet,
    expected_role: str,
    method: str,
    operation: str,
    resource: str,
    request_id: str,
    status: int,
    body: Any = EMPTY_BODY,
    now: int | None = None,
    max_timestamp_skew: int = DEFAULT_MAX_TIMESTAMP_SKEW,
) -> None:
    """Verify a signed response against an exact configured authority trust pin."""

    protocol = _required_header(headers, SIGNATURE_VERSION_HEADER)
    if protocol != RESPONSE_PROTOCOL:
        raise AuthError("Unsupported marketplace response signature version", status_code=401)
    try:
        principal = Identity(
            scheme=_required_header(headers, IDENTITY_SCHEME_HEADER),
            identifier=_required_header(headers, IDENTITY_IDENTIFIER_HEADER),
        )
        envelope = AuthenticatedResponse(
            protocol=protocol,
            role=_required_header(headers, ROLE_HEADER),
            principal=principal,
            method=method,
            operation=operation,
            resource=resource,
            request_id=_required_header(headers, REQUEST_ID_HEADER),
            timestamp=_timestamp(headers),
            status=status,
            body_hash=canonical_body_hash(body),
            proof=SignatureProof(
                scheme=principal.scheme,
                value=_required_header(headers, SIGNATURE_HEADER),
            ),
        )
    except AuthError:
        raise
    except (TypeError, ValueError) as exc:
        raise AuthError("Malformed marketplace response authentication", status_code=400) from exc

    result = verify_response(
        envelope,
        body=body,
        now=int(time.time()) if now is None else now,
        max_skew=max_timestamp_skew,
        expected_role=expected_role,
        expected_principals=expected_principals,
        expected_method=method,
        expected_operation=operation,
        expected_resource=resource,
        expected_request_id=request_id,
    )
    if not result.verified:
        raise _verification_error(result.code)


def _response_headers(envelope: AuthenticatedResponse) -> dict[str, str]:
    return {
        SIGNATURE_VERSION_HEADER: envelope.protocol,
        IDENTITY_SCHEME_HEADER: envelope.principal.scheme.value,
        IDENTITY_IDENTIFIER_HEADER: envelope.principal.identifier,
        ROLE_HEADER: envelope.role,
        REQUEST_ID_HEADER: envelope.request_id,
        TIMESTAMP_HEADER: str(envelope.timestamp),
        SIGNATURE_HEADER: envelope.proof.value,
    }


def _verification_error(code: VerificationCode) -> AuthError:
    if code == VerificationCode.CHANGED_REUSE:
        return AuthError("Request ID was reused with changed signed content", status_code=409)
    if code == VerificationCode.WRONG_PRINCIPAL:
        return AuthError("Marketplace principal is not trusted for this authority")
    if code in {
        VerificationCode.MALFORMED_ENVELOPE,
        VerificationCode.UNSUPPORTED_VERSION,
    }:
        return AuthError("Unsupported or malformed marketplace authentication", status_code=401)
    if code == VerificationCode.TIMESTAMP_SKEW:
        return AuthError("Marketplace authentication timestamp is outside the allowed skew")
    if code == VerificationCode.BODY_HASH_MISMATCH:
        return AuthError("Marketplace authentication does not match the request body")
    if code == VerificationCode.CONTEXT_MISMATCH:
        return AuthError("Marketplace authentication role, principal, or route does not match")
    return AuthError("Invalid marketplace signature")
