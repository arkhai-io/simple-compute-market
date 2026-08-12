"""Canonical JSON hashing, length-delimited envelopes, and signing helpers."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import rfc8785
from pydantic import BaseModel

from market_identity.models import (
    AuthenticatedRequest,
    AuthenticatedResponse,
    RequestEnvelope,
    ResponseEnvelope,
    RotationIntent,
    RotationRequest,
    SignatureProof,
)
from market_identity.registry import Signer

_MAX_CANONICAL_FIELD_BYTES = 4096


class _EmptyBody:
    __slots__ = ()

    def __repr__(self) -> str:
        return "EMPTY_BODY"


EMPTY_BODY = _EmptyBody()


class CanonicalizationError(ValueError):
    """Raised when a value cannot be represented by the canonical contract."""


def canonical_json(value: Any) -> bytes:
    """Return RFC 8785 JSON bytes without dropping explicit null fields."""

    if value is EMPTY_BODY:
        raise CanonicalizationError("an empty body is not a JSON value")
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=False)
    try:
        return bytes(rfc8785.dumps(value))
    except (TypeError, ValueError) as exc:
        raise CanonicalizationError("body is not canonicalizable JSON") from exc


def canonical_body_hash(value: Any = EMPTY_BODY) -> str:
    """Return the lowercase SHA-256 digest of canonical JSON or the empty body."""

    payload = b"" if value is EMPTY_BODY else canonical_json(value)
    return hashlib.sha256(payload).hexdigest()


def canonical_request_bytes(envelope: RequestEnvelope) -> bytes:
    """Encode all semantic request fields as one collision-free byte sequence."""

    return _frame(
        (
            envelope.protocol,
            envelope.role,
            envelope.principal.scheme.value,
            envelope.principal.identifier,
            envelope.method,
            envelope.operation,
            envelope.resource,
            envelope.request_id,
            str(envelope.timestamp),
            envelope.body_hash,
        )
    )


def canonical_response_bytes(envelope: ResponseEnvelope) -> bytes:
    """Encode all semantic response fields as one collision-free byte sequence."""

    return _frame(
        (
            envelope.protocol,
            envelope.role,
            envelope.principal.scheme.value,
            envelope.principal.identifier,
            envelope.method,
            envelope.operation,
            envelope.resource,
            envelope.request_id,
            str(envelope.timestamp),
            str(envelope.status),
            envelope.body_hash,
        )
    )


def canonical_rotation_bytes(intent: RotationIntent) -> bytes:
    """Encode the shared old/new possession intent signed during rotation."""

    return _frame(
        (
            intent.protocol,
            intent.current.scheme.value,
            intent.current.identifier,
            intent.replacement.scheme.value,
            intent.replacement.identifier,
            intent.subject,
            intent.authority,
            intent.nonce,
            str(intent.overlap_seconds),
            str(intent.expires_at),
        )
    )


def request_hash(envelope: RequestEnvelope) -> str:
    """Fingerprint replay semantics, excluding freshness and the lookup key."""

    semantic_bytes = _frame(
        (
            envelope.protocol,
            envelope.principal.scheme.value,
            envelope.principal.identifier,
            envelope.role,
            envelope.method,
            envelope.operation,
            envelope.resource,
            envelope.body_hash,
        )
    )
    return hashlib.sha256(semantic_bytes).hexdigest()


def sign_request(*, signer: Signer, envelope: RequestEnvelope) -> AuthenticatedRequest:
    """Sign a prepared request envelope with its declared identity."""

    if signer.identity != envelope.principal:
        raise ValueError("signer identity must match request principal")
    proof = SignatureProof.from_bytes(
        signer.identity.scheme,
        signer.sign(canonical_request_bytes(envelope)),
    )
    return AuthenticatedRequest(**envelope.model_dump(mode="python"), proof=proof)


def sign_response(*, signer: Signer, envelope: ResponseEnvelope) -> AuthenticatedResponse:
    """Sign a prepared response envelope with its declared identity."""

    if signer.identity != envelope.principal:
        raise ValueError("signer identity must match response principal")
    proof = SignatureProof.from_bytes(
        signer.identity.scheme,
        signer.sign(canonical_response_bytes(envelope)),
    )
    return AuthenticatedResponse(**envelope.model_dump(mode="python"), proof=proof)


def sign_rotation(
    *,
    current_signer: Signer,
    replacement_signer: Signer,
    intent: RotationIntent,
) -> RotationRequest:
    """Create the required two proofs over exactly one rotation intent."""

    if current_signer.identity != intent.current:
        raise ValueError("current signer identity must match rotation intent")
    if replacement_signer.identity != intent.replacement:
        raise ValueError("replacement signer identity must match rotation intent")
    message = canonical_rotation_bytes(intent)
    return RotationRequest(
        intent=intent,
        current_proof=SignatureProof.from_bytes(
            intent.current.scheme,
            current_signer.sign(message),
        ),
        replacement_proof=SignatureProof.from_bytes(
            intent.replacement.scheme,
            replacement_signer.sign(message),
        ),
    )


def _frame(fields: Sequence[str]) -> bytes:
    framed = bytearray()
    for field in fields:
        if not isinstance(field, str):
            raise CanonicalizationError("canonical fields must be text")
        encoded = field.encode("utf-8")
        if len(encoded) > _MAX_CANONICAL_FIELD_BYTES:
            raise CanonicalizationError("canonical field exceeds byte bound")
        framed.extend(len(encoded).to_bytes(4, byteorder="big", signed=False))
        framed.extend(encoded)
    return bytes(framed)
