"""Verifying a retained signed message offline, whichever version signed it.

A signed request or response kept as evidence is verified long after it was
signed, by a party that did not admit it. Two verifiers do so, one for a request
and one for a response. Each takes what was kept -- a version 3 record
(:mod:`market_identity.records`) or a version 2 envelope as it was stored -- with
the exact body bytes and the principals trusted for it, tells the versions apart by
the record's ``protocol``, and answers one view for both.

A retained message is not a live request, so neither verifier judges freshness;
and the audience concerned only the authority that admitted the request, so
neither checks its membership. A version 3 response signs no role, so the response
verifier takes none: the exact trusted principals bind its signer, and a version 2
response envelope's signed role is not checked either.
"""

from __future__ import annotations

import hmac
import json
from collections.abc import Mapping
from enum import Enum
from typing import Any, Union

from pydantic import Field, ValidationError

from market_identity.canonical import (
    EMPTY_BODY,
    CanonicalizationError,
    canonical_body_hash,
    canonical_request_bytes,
    canonical_response_bytes,
)
from market_identity.codes import VerificationCode
# The profile's record rebuilding is the package's own, never a consumer's: a
# consumer verifies retained evidence only through the two verifiers here.
from market_identity.http_profile import (
    _check_market_response,
    _rebuild_request_headers,
    _rebuild_response_headers,
    _record_binding,
    verify_market_request,
)
from market_identity.models import (
    REQUEST_PROTOCOL,
    RESPONSE_PROTOCOL,
    AuthenticatedRequest,
    AuthenticatedResponse,
    ContractModel,
    Identity,
    TrustedIdentitySet,
)
from market_identity.records import RequestRecord, ResponseRecord
from market_identity.registry import get_identity_verifier
from market_identity.wire import REQUEST_PROFILE, RESPONSE_PROFILE, RecordField


class _Unchecked(Enum):
    UNCHECKED = "unchecked"


#: The default of ``expected_resource``: the caller does not know the resource.
#: ``None`` instead expects a request that named none.
UNCHECKED = _Unchecked.UNCHECKED

RetainedRequest = Union[RequestRecord, AuthenticatedRequest, Mapping[str, Any]]
"""A retained request: a version 3 record, or a version 2 envelope, as a model or as
stored."""

RetainedResponse = Union[ResponseRecord, AuthenticatedResponse, Mapping[str, Any]]
"""A retained response: a version 3 record, or a version 2 envelope, as a model or
as stored."""


class RequestEvidence(ContractModel):
    """What a verified retained request attests, whichever version signed it.

    ``resource`` is ``None`` where the request named none; a version 2 request
    signed an empty one for an operation with no target.
    """

    principal: Identity
    timestamp: int = Field(ge=0)
    operation: str
    resource: str | None
    request_id: str
    role: str


class ResponseEvidence(ContractModel):
    """What a verified retained response attests, whichever version signed it."""

    principal: Identity
    timestamp: int = Field(ge=0)
    operation: str
    resource: str | None
    request_id: str
    status: int


class RequestEvidenceVerification(ContractModel):
    code: VerificationCode
    evidence: RequestEvidence | None = None

    @property
    def verified(self) -> bool:
        return self.code == VerificationCode.VERIFIED


class ResponseEvidenceVerification(ContractModel):
    code: VerificationCode
    evidence: ResponseEvidence | None = None

    @property
    def verified(self) -> bool:
        return self.code == VerificationCode.VERIFIED


def verify_request_evidence(
    retained: RetainedRequest,
    *,
    body: bytes,
    trusted: TrustedIdentitySet,
    expected_role: str | None = None,
    expected_operation: str | None = None,
    expected_resource: str | None | _Unchecked = UNCHECKED,
) -> RequestEvidenceVerification:
    """Verify a retained request against its exact body and the principals trusted
    for it.

    The proof is checked under the principal's scheme, over the signature base
    rebuilt from what was kept and the digest computed from ``body``, and the
    principal against ``trusted``. Each expectation the caller gives -- a role, an
    operation, a resource or ``None`` for none -- must hold.
    """

    parsed = _parse(retained, RequestRecord, AuthenticatedRequest, REQUEST_PROFILE, REQUEST_PROTOCOL)
    if isinstance(parsed, VerificationCode):
        return RequestEvidenceVerification(code=parsed)
    if isinstance(parsed, RequestRecord):
        result = _verify_request_record(parsed, body)
    else:
        result = _verify_request_envelope(parsed, body)
    if isinstance(result, VerificationCode):
        return RequestEvidenceVerification(code=result)
    if not trusted.allows(result.principal):
        return RequestEvidenceVerification(code=VerificationCode.WRONG_PRINCIPAL)
    if not _expected(result.operation, result.resource, expected_operation, expected_resource) or (
        expected_role is not None and result.role != expected_role
    ):
        return RequestEvidenceVerification(code=VerificationCode.CONTEXT_MISMATCH)
    return RequestEvidenceVerification(code=VerificationCode.VERIFIED, evidence=result)


def verify_response_evidence(
    retained: RetainedResponse,
    *,
    body: bytes,
    trusted: TrustedIdentitySet,
    expected_operation: str | None = None,
    expected_resource: str | None | _Unchecked = UNCHECKED,
) -> ResponseEvidenceVerification:
    """Verify a retained response against its exact body and the principals trusted
    for it, which alone bind its signer.

    As :func:`verify_request_evidence`, but no role is asked or checked: a version 3
    response signs none, and a version 2 response's signed role is not read.
    """

    parsed = _parse(retained, ResponseRecord, AuthenticatedResponse, RESPONSE_PROFILE, RESPONSE_PROTOCOL)
    if isinstance(parsed, VerificationCode):
        return ResponseEvidenceVerification(code=parsed)
    if isinstance(parsed, ResponseRecord):
        result = _verify_response_record(parsed, body, trusted)
    else:
        result = _verify_response_envelope(parsed, body)
    if isinstance(result, VerificationCode):
        return ResponseEvidenceVerification(code=result)
    if not trusted.allows(result.principal):
        return ResponseEvidenceVerification(code=VerificationCode.WRONG_PRINCIPAL)
    if not _expected(result.operation, result.resource, expected_operation, expected_resource):
        return ResponseEvidenceVerification(code=VerificationCode.CONTEXT_MISMATCH)
    return ResponseEvidenceVerification(code=VerificationCode.VERIFIED, evidence=result)


def _parse(retained: Any, record_type: Any, envelope_type: Any, profile: str, protocol: str) -> Any:
    """The retained message as its version's model, or the code refusing it."""

    if isinstance(retained, (record_type, envelope_type)):
        return retained
    if not isinstance(retained, Mapping):
        return VerificationCode.MALFORMED_ENVELOPE
    kind = retained.get(RecordField.PROTOCOL.value)
    model = {profile: record_type, protocol: envelope_type}.get(kind) if isinstance(kind, str) else None
    if model is None:
        return VerificationCode.UNSUPPORTED_VERSION
    try:
        return model.model_validate(dict(retained))
    except ValidationError:
        return VerificationCode.MALFORMED_ENVELOPE


def _expected(
    operation: str,
    resource: str | None,
    expected_operation: str | None,
    expected_resource: str | None | _Unchecked,
) -> bool:
    if expected_operation is not None and operation != expected_operation:
        return False
    return expected_resource is UNCHECKED or resource == expected_resource


def _verify_request_record(record: RequestRecord, body: bytes) -> RequestEvidence | VerificationCode:
    verification = verify_market_request(
        method=record.method,
        headers=_rebuild_request_headers(record, body),
        body=body,
        query=record.query,
    )
    if not verification.verified or verification.request is None:
        return verification.code
    return RequestEvidence(
        principal=verification.request.principal,
        timestamp=record.timestamp,
        operation=record.operation,
        resource=record.resource,
        request_id=record.request_id,
        role=record.role,
    )


def _verify_response_record(
    record: ResponseRecord, body: bytes, trusted: TrustedIdentitySet
) -> ResponseEvidence | VerificationCode:
    verification = _check_market_response(
        status=record.status,
        headers=_rebuild_response_headers(record, body),
        body=body,
        request=_record_binding(record),
        expected_principals=trusted,
    )
    if not verification.verified or verification.principal is None:
        return verification.code
    return ResponseEvidence(
        principal=verification.principal,
        timestamp=record.timestamp,
        operation=record.operation,
        resource=record.resource,
        request_id=record.request_id,
        status=record.status,
    )


def _verify_request_envelope(envelope: AuthenticatedRequest, body: bytes) -> RequestEvidence | VerificationCode:
    failure = _envelope_failure(envelope.body_hash, body)
    if failure is None and not get_identity_verifier(envelope.principal.scheme).verify_signature(
        envelope.principal, canonical_request_bytes(envelope), envelope.proof.to_bytes()
    ):
        failure = VerificationCode.INVALID_PROOF
    if failure is not None:
        return failure
    return RequestEvidence(
        principal=envelope.principal,
        timestamp=envelope.timestamp,
        operation=envelope.operation,
        resource=envelope.resource or None,
        request_id=envelope.request_id,
        role=envelope.role,
    )


def _verify_response_envelope(envelope: AuthenticatedResponse, body: bytes) -> ResponseEvidence | VerificationCode:
    failure = _envelope_failure(envelope.body_hash, body)
    if failure is None and not get_identity_verifier(envelope.principal.scheme).verify_signature(
        envelope.principal, canonical_response_bytes(envelope), envelope.proof.to_bytes()
    ):
        failure = VerificationCode.INVALID_PROOF
    if failure is not None:
        return failure
    return ResponseEvidence(
        principal=envelope.principal,
        timestamp=envelope.timestamp,
        operation=envelope.operation,
        resource=envelope.resource or None,
        request_id=envelope.request_id,
        status=envelope.status,
    )


def _envelope_failure(body_hash: str, body: bytes) -> VerificationCode | None:
    """Whether ``body`` is the JSON a version 2 envelope's canonical hash names."""

    try:
        value = json.loads(body) if body else EMPTY_BODY
        computed = canonical_body_hash(value)
    except (ValueError, CanonicalizationError):
        return VerificationCode.BODY_HASH_MISMATCH
    if not hmac.compare_digest(body_hash, computed):
        return VerificationCode.BODY_HASH_MISMATCH
    return None
