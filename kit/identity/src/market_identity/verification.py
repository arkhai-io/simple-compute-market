"""Framework-neutral signature, skew, replay, and rotation verification."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from enum import Enum
from typing import Any

from pydantic import ValidationError

from market_identity.canonical import (
    EMPTY_BODY,
    canonical_body_hash,
    canonical_request_bytes,
    canonical_response_bytes,
    canonical_rotation_bytes,
    request_hash,
)
from market_identity.models import (
    REQUEST_PROTOCOL,
    RESPONSE_PROTOCOL,
    AuthenticatedRequest,
    AuthenticatedResponse,
    ContractModel,
    IdentityScheme,
    ReplayIdentity,
    ReplayReservation,
    RotationRequest,
    TrustedIdentitySet,
)
from market_identity.registry import get_identity_verifier


class VerificationCode(str, Enum):
    """Closed authentication classifications suitable for any transport."""

    VERIFIED = "verified"
    EXACT_RETRY = "exact_retry"
    CHANGED_REUSE = "changed_reuse"
    UNSUPPORTED_VERSION = "unsupported_version"
    UNKNOWN_SCHEME = "unknown_scheme"
    WRONG_PRINCIPAL = "wrong_principal"
    MALFORMED_ENVELOPE = "malformed_envelope"
    CONTEXT_MISMATCH = "context_mismatch"
    BODY_HASH_MISMATCH = "body_hash_mismatch"
    TIMESTAMP_SKEW = "timestamp_skew"
    INVALID_PROOF = "invalid_proof"


class ReplayCode(str, Enum):
    """Classification for a principal-scoped request ID lookup."""

    NEW = "new"
    EXACT_RETRY = "exact_retry"
    CHANGED_REUSE = "changed_reuse"


class VerificationResult(ContractModel):
    """Authentication result with an optional value ready for replay persistence."""

    code: VerificationCode
    reservation: ReplayReservation | None = None

    @property
    def verified(self) -> bool:
        return self.code in {VerificationCode.VERIFIED, VerificationCode.EXACT_RETRY}

    @property
    def dispatch_allowed(self) -> bool:
        return self.code == VerificationCode.VERIFIED


class ReplayResult(ContractModel):
    """Persistence-neutral comparison against an authority-owned replay row."""

    code: ReplayCode
    reservation: ReplayReservation


class RotationVerificationResult(ContractModel):
    """Independent verification outcome for both required rotation proofs."""

    current_valid: bool
    replacement_valid: bool
    expired: bool

    @property
    def verified(self) -> bool:
        return self.current_valid and self.replacement_valid and not self.expired


def verify_request(
    envelope: AuthenticatedRequest | Mapping[str, Any],
    *,
    body: Any = EMPTY_BODY,
    now: int,
    max_skew: int,
    expected_role: str,
    expected_method: str,
    expected_operation: str,
    expected_resource: str,
    expected_principals: TrustedIdentitySet,
    existing_replay: ReplayReservation | None = None,
) -> VerificationResult:
    """Verify request context and proof, then classify an optional replay lookup."""

    if max_skew < 0:
        raise ValueError("max_skew must not be negative")
    parsed, failure = _request(envelope)
    if failure is not None:
        return VerificationResult(code=failure)
    assert parsed is not None
    if not expected_principals.allows(parsed.principal):
        return VerificationResult(code=VerificationCode.WRONG_PRINCIPAL)

    expected_context = (
        expected_role,
        expected_method.upper(),
        expected_operation,
        expected_resource,
    )
    actual_context = (
        parsed.role,
        parsed.method,
        parsed.operation,
        parsed.resource,
    )
    if actual_context != expected_context:
        return VerificationResult(code=VerificationCode.CONTEXT_MISMATCH)
    if not hmac.compare_digest(parsed.body_hash, canonical_body_hash(body)):
        return VerificationResult(code=VerificationCode.BODY_HASH_MISMATCH)
    if abs(now - parsed.timestamp) > max_skew:
        return VerificationResult(code=VerificationCode.TIMESTAMP_SKEW)

    verifier = get_identity_verifier(parsed.principal.scheme)
    if not verifier.verify_signature(
        parsed.principal,
        canonical_request_bytes(parsed),
        parsed.proof.to_bytes(),
    ):
        return VerificationResult(code=VerificationCode.INVALID_PROOF)

    replay = classify_replay(parsed, existing_replay)
    if replay.code == ReplayCode.EXACT_RETRY:
        return VerificationResult(
            code=VerificationCode.EXACT_RETRY,
            reservation=replay.reservation,
        )
    if replay.code == ReplayCode.CHANGED_REUSE:
        return VerificationResult(
            code=VerificationCode.CHANGED_REUSE,
            reservation=replay.reservation,
        )
    return VerificationResult(
        code=VerificationCode.VERIFIED,
        reservation=replay.reservation,
    )


def verify_response(
    envelope: AuthenticatedResponse | Mapping[str, Any],
    *,
    body: Any = EMPTY_BODY,
    now: int,
    max_skew: int,
    expected_role: str,
    expected_principals: TrustedIdentitySet,
    expected_method: str,
    expected_operation: str,
    expected_resource: str,
    expected_request_id: str,
) -> VerificationResult:
    """Verify one response against the caller's pinned authority and request context."""

    if max_skew < 0:
        raise ValueError("max_skew must not be negative")
    parsed, failure = _response(envelope)
    if failure is not None:
        return VerificationResult(code=failure)
    assert parsed is not None
    if not expected_principals.allows(parsed.principal):
        return VerificationResult(code=VerificationCode.WRONG_PRINCIPAL)

    expected_context = (
        expected_role,
        expected_method.upper(),
        expected_operation,
        expected_resource,
        expected_request_id,
    )
    actual_context = (
        parsed.role,
        parsed.method,
        parsed.operation,
        parsed.resource,
        parsed.request_id,
    )
    if actual_context != expected_context:
        return VerificationResult(code=VerificationCode.CONTEXT_MISMATCH)
    if not hmac.compare_digest(parsed.body_hash, canonical_body_hash(body)):
        return VerificationResult(code=VerificationCode.BODY_HASH_MISMATCH)
    if abs(now - parsed.timestamp) > max_skew:
        return VerificationResult(code=VerificationCode.TIMESTAMP_SKEW)

    verifier = get_identity_verifier(parsed.principal.scheme)
    if not verifier.verify_signature(
        parsed.principal,
        canonical_response_bytes(parsed),
        parsed.proof.to_bytes(),
    ):
        return VerificationResult(code=VerificationCode.INVALID_PROOF)
    return VerificationResult(code=VerificationCode.VERIFIED)


def classify_replay(
    envelope: AuthenticatedRequest,
    existing: ReplayReservation | None,
) -> ReplayResult:
    """Compare one verified request with a replay row supplied by its authority."""

    reservation = ReplayReservation(
        identity=ReplayIdentity(
            principal=envelope.principal,
            request_id=envelope.request_id,
        ),
        request_hash=request_hash(envelope),
    )
    if existing is None:
        return ReplayResult(code=ReplayCode.NEW, reservation=reservation)
    if existing.identity != reservation.identity:
        raise ValueError("existing replay reservation belongs to a different identity")
    if hmac.compare_digest(existing.request_hash, reservation.request_hash):
        return ReplayResult(code=ReplayCode.EXACT_RETRY, reservation=existing)
    return ReplayResult(code=ReplayCode.CHANGED_REUSE, reservation=existing)


def verify_rotation(
    request: RotationRequest,
    *,
    now: int,
) -> RotationVerificationResult:
    """Verify current and replacement proofs over the same unmodified intent."""

    message = canonical_rotation_bytes(request.intent)
    current = get_identity_verifier(request.intent.current.scheme)
    replacement = get_identity_verifier(request.intent.replacement.scheme)
    return RotationVerificationResult(
        current_valid=current.verify_signature(
            request.intent.current,
            message,
            request.current_proof.to_bytes(),
        ),
        replacement_valid=replacement.verify_signature(
            request.intent.replacement,
            message,
            request.replacement_proof.to_bytes(),
        ),
        expired=now > request.intent.expires_at,
    )


def _request(
    envelope: AuthenticatedRequest | Mapping[str, Any],
) -> tuple[AuthenticatedRequest | None, VerificationCode | None]:
    if (
        isinstance(envelope, Mapping)
        and "protocol" in envelope
        and envelope["protocol"] != REQUEST_PROTOCOL
    ):
        return None, VerificationCode.UNSUPPORTED_VERSION
    if _has_unknown_scheme(envelope):
        return None, VerificationCode.UNKNOWN_SCHEME
    try:
        return AuthenticatedRequest.model_validate(envelope), None
    except ValidationError:
        return None, VerificationCode.MALFORMED_ENVELOPE


def _response(
    envelope: AuthenticatedResponse | Mapping[str, Any],
) -> tuple[AuthenticatedResponse | None, VerificationCode | None]:
    if (
        isinstance(envelope, Mapping)
        and "protocol" in envelope
        and envelope["protocol"] != RESPONSE_PROTOCOL
    ):
        return None, VerificationCode.UNSUPPORTED_VERSION
    if _has_unknown_scheme(envelope):
        return None, VerificationCode.UNKNOWN_SCHEME
    try:
        return AuthenticatedResponse.model_validate(envelope), None
    except ValidationError:
        return None, VerificationCode.MALFORMED_ENVELOPE


def _has_unknown_scheme(envelope: object) -> bool:
    if not isinstance(envelope, Mapping):
        return False
    principal = envelope.get("principal")
    if not isinstance(principal, Mapping) or "scheme" not in principal:
        return False
    try:
        IdentityScheme(principal["scheme"])
    except (TypeError, ValueError):
        return True
    return False
