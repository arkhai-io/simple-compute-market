"""Version 2 request and response signing.

The version 2 verifiers in ``market_identity.verification`` also read retained
version 2 signed responses and requests as evidence, which stays readable for as
long as a deal retains it. Signing is kept in this module, apart from those
readers, so that what signs version 2 and what reads it as evidence can change
independently.
"""

from __future__ import annotations

from market_identity.canonical import canonical_request_bytes, canonical_response_bytes
from market_identity.models import (
    AuthenticatedRequest,
    AuthenticatedResponse,
    RequestEnvelope,
    ResponseEnvelope,
    SignatureProof,
)
from market_identity.registry import Signer


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
