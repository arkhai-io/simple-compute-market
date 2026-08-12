from __future__ import annotations

import hashlib
from typing import Any

import pytest
from pydantic import ValidationError

from market_identity import (
    EMPTY_BODY,
    REQUEST_PROTOCOL,
    RESPONSE_PROTOCOL,
    AuthenticatedRequest,
    AuthenticatedResponse,
    Ed25519Signer,
    Eip191Signer,
    ReplayIdentity,
    RequestEnvelope,
    ResponseEnvelope,
    Signer,
    TrustedIdentitySet,
    VerificationCode,
    canonical_body_hash,
    canonical_json,
    canonical_request_bytes,
    canonical_response_bytes,
    request_hash,
    sign_request,
    sign_response,
    verify_request,
    verify_response,
)
from conftest import BODY, NOW


def _request_result(
    request: AuthenticatedRequest | dict[str, Any],
    *,
    body: Any = BODY,
    now: int = NOW,
    existing_replay=None,
    **expected: Any,
):
    principal = (
        request.principal
        if isinstance(request, AuthenticatedRequest)
        else Ed25519Signer(bytes(range(32))).identity
    )
    defaults = {
        "expected_role": "buyer",
        "expected_method": "POST",
        "expected_operation": "negotiation.advance",
        "expected_resource": "negotiation/thread-17",
        "expected_principals": TrustedIdentitySet(identities=(principal,)),
    }
    defaults.update(expected)
    return verify_request(
        request,
        body=body,
        now=now,
        max_skew=300,
        existing_replay=existing_replay,
        **defaults,
    )


def _response_result(
    response: AuthenticatedResponse | dict[str, Any],
    *,
    body: Any,
    now: int = NOW,
):
    principal = response.principal if isinstance(response, AuthenticatedResponse) else None
    assert principal is not None
    return verify_response(
        response,
        body=body,
        now=now,
        max_skew=300,
        expected_role="storefront",
        expected_principals=TrustedIdentitySet(identities=(principal,)),
        expected_method="POST",
        expected_operation="negotiation.advance",
        expected_resource="negotiation/thread-17",
        expected_request_id="7f0ed41b-6ad8-4a1f-94dc-80691c28b841",
    )


def _replace_request(
    request: AuthenticatedRequest,
    **changes: Any,
) -> AuthenticatedRequest:
    data = request.model_dump(mode="python")
    data.update(changes)
    return AuthenticatedRequest.model_validate(data)


def test_canonical_json_and_empty_body_hash_are_deterministic() -> None:
    left = {"z": [3, None, True], "a": {"é": "value"}}
    right = {"a": {"é": "value"}, "z": [3, None, True]}
    assert canonical_json(left) == canonical_json(right)
    assert canonical_json(left) == b'{"a":{"\xc3\xa9":"value"},"z":[3,null,true]}'
    assert canonical_body_hash(left) == hashlib.sha256(canonical_json(left)).hexdigest()
    assert canonical_body_hash() == hashlib.sha256(b"").hexdigest()
    assert canonical_body_hash(None) == hashlib.sha256(b"null").hexdigest()
    assert canonical_body_hash(EMPTY_BODY) != canonical_body_hash(None)


def test_request_canonical_fixture_is_four_byte_length_delimited(
    request_envelope: RequestEnvelope,
) -> None:
    fields = (
        REQUEST_PROTOCOL,
        request_envelope.role,
        request_envelope.principal.scheme.value,
        request_envelope.principal.identifier,
        request_envelope.method,
        request_envelope.operation,
        request_envelope.resource,
        request_envelope.request_id,
        str(request_envelope.timestamp),
        request_envelope.body_hash,
    )
    expected = b"".join(
        len(field.encode()).to_bytes(4, "big") + field.encode() for field in fields
    )
    assert canonical_request_bytes(request_envelope) == expected


def test_length_delimiting_prevents_operation_resource_collisions(
    request_envelope: RequestEnvelope,
) -> None:
    first = RequestEnvelope.model_validate(
        {**request_envelope.model_dump(mode="python"), "operation": "ab", "resource": "c"}
    )
    second = RequestEnvelope.model_validate(
        {**request_envelope.model_dump(mode="python"), "operation": "a", "resource": "bc"}
    )
    assert first.operation + first.resource == second.operation + second.resource
    assert canonical_request_bytes(first) != canonical_request_bytes(second)


def test_request_sign_and_verify_succeeds_for_both_schemes(
    signer: Signer,
    request_envelope: RequestEnvelope,
) -> None:
    request = sign_request(signer=signer, envelope=request_envelope)
    result = _request_result(request)
    assert result.code == VerificationCode.VERIFIED
    assert result.verified is True
    assert result.dispatch_allowed is True
    assert result.reservation is not None
    assert result.reservation.identity == ReplayIdentity(
        principal=signer.identity,
        request_id=request.request_id,
    )
    assert result.reservation.request_hash == request_hash(request)


def test_request_trust_overlap_accepts_old_and_new_then_rejects_removed_old(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    trusted = TrustedIdentitySet(
        identities=(ed25519_signer.identity, eip191_signer.identity)
    )
    requests = []
    for identity_signer in (ed25519_signer, eip191_signer):
        envelope = RequestEnvelope(
            role="buyer",
            principal=identity_signer.identity,
            method="POST",
            operation="negotiation.advance",
            resource="negotiation/thread-17",
            request_id=f"rotation-{identity_signer.identity.scheme.value}",
            timestamp=NOW,
            body_hash=canonical_body_hash(BODY),
        )
        request = sign_request(signer=identity_signer, envelope=envelope)
        requests.append(request)
        assert _request_result(
            request,
            expected_principals=trusted,
        ).code == VerificationCode.VERIFIED

    replacement_only = TrustedIdentitySet(identities=(eip191_signer.identity,))
    assert _request_result(
        requests[0],
        expected_principals=replacement_only,
    ).code == VerificationCode.WRONG_PRINCIPAL


def test_sign_request_rejects_different_signer(
    request_envelope: RequestEnvelope,
) -> None:
    other = Ed25519Signer(bytes(reversed(range(32))))
    if request_envelope.principal.scheme.value == "ed25519":
        with pytest.raises(ValueError, match="signer identity"):
            sign_request(signer=other, envelope=request_envelope)
    else:
        with pytest.raises(ValueError, match="signer identity"):
            sign_request(signer=other, envelope=request_envelope)


@pytest.mark.parametrize(
    "field",
    (
        "role",
        "principal",
        "method",
        "operation",
        "resource",
        "request_id",
        "timestamp",
        "body_hash",
    ),
)
def test_every_signed_request_field_mutation_invalidates_proof(
    signer: Signer,
    request_envelope: RequestEnvelope,
    field: str,
) -> None:
    request = sign_request(signer=signer, envelope=request_envelope)
    changes: dict[str, Any] = {
        "role": "seller",
        "method": "PUT",
        "operation": "negotiation.cancel",
        "resource": "negotiation/thread-18",
        "request_id": "changed-request-id",
        "timestamp": NOW + 1,
        "body_hash": canonical_body_hash({"changed": True}),
    }
    if signer.identity.scheme.value == "ed25519":
        changes["principal"] = Ed25519Signer(b"\x01" * 32).identity
    else:
        changes["principal"] = Eip191Signer(b"\x01" * 32).identity
    mutated = _replace_request(request, **{field: changes[field]})
    expected = {
        "expected_role": mutated.role,
        "expected_method": mutated.method,
        "expected_operation": mutated.operation,
        "expected_resource": mutated.resource,
        "expected_principals": TrustedIdentitySet(identities=(mutated.principal,)),
    }
    body = {"changed": True} if field == "body_hash" else BODY
    result = _request_result(
        mutated,
        body=body,
        now=mutated.timestamp,
        **expected,
    )
    assert result.code == VerificationCode.INVALID_PROOF


def test_body_mutation_is_classified_before_signature_verification(
    signer: Signer,
    request_envelope: RequestEnvelope,
) -> None:
    request = sign_request(signer=signer, envelope=request_envelope)
    result = _request_result(request, body={"amount": 18})
    assert result.code == VerificationCode.BODY_HASH_MISMATCH
    assert result.verified is False


def test_route_context_mutation_is_classified(
    signer: Signer,
    request_envelope: RequestEnvelope,
) -> None:
    request = sign_request(signer=signer, envelope=request_envelope)
    result = _request_result(request, expected_operation="negotiation.cancel")
    assert result.code == VerificationCode.CONTEXT_MISMATCH


def test_skew_boundary_is_inclusive_and_one_second_beyond_is_rejected(
    signer: Signer,
    request_envelope: RequestEnvelope,
) -> None:
    request = sign_request(signer=signer, envelope=request_envelope)
    assert _request_result(request, now=NOW + 300).code == VerificationCode.VERIFIED
    assert _request_result(request, now=NOW - 300).code == VerificationCode.VERIFIED
    assert _request_result(request, now=NOW + 301).code == VerificationCode.TIMESTAMP_SKEW
    assert _request_result(request, now=NOW - 301).code == VerificationCode.TIMESTAMP_SKEW


def test_exact_retry_and_changed_reuse_are_distinct(
    signer: Signer,
    request_envelope: RequestEnvelope,
) -> None:
    original = sign_request(signer=signer, envelope=request_envelope)
    first = _request_result(original)
    assert first.reservation is not None
    exact = _request_result(original, existing_replay=first.reservation)
    assert exact.code == VerificationCode.EXACT_RETRY
    assert exact.verified is True
    assert exact.dispatch_allowed is False

    changed_body = {"amount": 99}
    changed_envelope = RequestEnvelope.model_validate(
        {
            **request_envelope.model_dump(mode="python"),
            "body_hash": canonical_body_hash(changed_body),
        }
    )
    changed = sign_request(signer=signer, envelope=changed_envelope)
    reuse = _request_result(
        changed,
        body=changed_body,
        existing_replay=first.reservation,
    )
    assert reuse.code == VerificationCode.CHANGED_REUSE
    assert reuse.verified is False
    assert reuse.dispatch_allowed is False


def test_fresh_resign_of_same_semantics_is_exact_retry_after_restart(
    signer: Signer,
    request_envelope: RequestEnvelope,
) -> None:
    original = sign_request(signer=signer, envelope=request_envelope)
    first = _request_result(original)
    assert first.reservation is not None

    fresh_envelope = RequestEnvelope.model_validate(
        {
            **request_envelope.model_dump(mode="python"),
            "timestamp": NOW + 1,
        }
    )
    fresh = sign_request(signer=signer, envelope=fresh_envelope)
    assert fresh.proof != original.proof
    assert request_hash(fresh) == request_hash(original)
    retry = _request_result(
        fresh,
        now=NOW + 1,
        existing_replay=first.reservation,
    )
    assert retry.code == VerificationCode.EXACT_RETRY
    assert retry.dispatch_allowed is False
    stale = _request_result(
        fresh,
        now=NOW + 1_000,
        existing_replay=first.reservation,
    )
    assert stale.code == VerificationCode.TIMESTAMP_SKEW


def test_replay_fingerprint_binds_semantics_not_freshness_or_lookup_key(
    signer: Signer,
    request_envelope: RequestEnvelope,
) -> None:
    baseline = request_hash(request_envelope)
    for freshness_only in (
        {"timestamp": NOW + 1},
        {"request_id": "different-lookup-key"},
    ):
        envelope = RequestEnvelope.model_validate(
            {
                **request_envelope.model_dump(mode="python"),
                **freshness_only,
            }
        )
        assert request_hash(envelope) == baseline

    if signer.identity.scheme.value == "ed25519":
        different_principal = Ed25519Signer(b"\x01" * 32).identity
    else:
        different_principal = Eip191Signer(b"\x01" * 32).identity
    semantic_changes: tuple[dict[str, Any], ...] = (
        {"principal": different_principal},
        {"role": "seller"},
        {"method": "PUT"},
        {"operation": "negotiation.cancel"},
        {"resource": "negotiation/thread-18"},
        {"body_hash": canonical_body_hash({"changed": True})},
    )
    for change in semantic_changes:
        envelope = RequestEnvelope.model_validate(
            {
                **request_envelope.model_dump(mode="python"),
                **change,
            }
        )
        assert request_hash(envelope) != baseline


@pytest.mark.parametrize(
    "protocol",
    (
        "arkhai.market-request-signature.v1",
        "arkhai.market-request-signature.v3",
        "unknown",
    ),
)
def test_old_and_unknown_request_versions_are_classified(
    signer: Signer,
    request_envelope: RequestEnvelope,
    protocol: str,
) -> None:
    request = sign_request(signer=signer, envelope=request_envelope)
    raw = request.model_dump(mode="json")
    raw["protocol"] = protocol
    assert _request_result(raw).code == VerificationCode.UNSUPPORTED_VERSION


def test_missing_or_malformed_request_fields_are_classified(
    signer: Signer,
    request_envelope: RequestEnvelope,
) -> None:
    request = sign_request(signer=signer, envelope=request_envelope)
    missing = request.model_dump(mode="json")
    missing.pop("proof")
    assert _request_result(missing).code == VerificationCode.MALFORMED_ENVELOPE
    malformed = request.model_dump(mode="json")
    malformed["proof"]["value"] = "x" * 1000
    assert _request_result(malformed).code == VerificationCode.MALFORMED_ENVELOPE
    unknown = request.model_dump(mode="json")
    unknown["principal"]["scheme"] = "unknown"
    assert _request_result(unknown).code == VerificationCode.UNKNOWN_SCHEME


def test_response_signing_binds_status_and_request_context(signer: Signer) -> None:
    body = {"state": "accepted"}
    envelope = ResponseEnvelope(
        role="storefront",
        principal=signer.identity,
        method="POST",
        operation="negotiation.advance",
        resource="negotiation/thread-17",
        request_id="7f0ed41b-6ad8-4a1f-94dc-80691c28b841",
        timestamp=NOW,
        status=202,
        body_hash=canonical_body_hash(body),
    )
    response = sign_response(signer=signer, envelope=envelope)
    assert _response_result(response, body=body).code == VerificationCode.VERIFIED


    fields = (
        RESPONSE_PROTOCOL,
        response.role,
        response.principal.scheme.value,
        response.principal.identifier,
        response.method,
        response.operation,
        response.resource,
        response.request_id,
        str(response.timestamp),
        str(response.status),
        response.body_hash,
    )
    fixture = b"".join(
        len(field.encode()).to_bytes(4, "big") + field.encode() for field in fields
    )
    assert canonical_response_bytes(response) == fixture


def test_response_trust_overlap_accepts_old_and_new_then_rejects_removed_old(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    body = {"state": "accepted"}
    trusted = TrustedIdentitySet(
        identities=(ed25519_signer.identity, eip191_signer.identity)
    )
    responses = []
    for identity_signer in (ed25519_signer, eip191_signer):
        envelope = ResponseEnvelope(
            role="storefront",
            principal=identity_signer.identity,
            method="POST",
            operation="negotiation.advance",
            resource="negotiation/thread-17",
            request_id="7f0ed41b-6ad8-4a1f-94dc-80691c28b841",
            timestamp=NOW,
            status=202,
            body_hash=canonical_body_hash(body),
        )
        response = sign_response(signer=identity_signer, envelope=envelope)
        responses.append(response)
        assert verify_response(
            response,
            body=body,
            now=NOW,
            max_skew=300,
            expected_role="storefront",
            expected_principals=trusted,
            expected_method="POST",
            expected_operation="negotiation.advance",
            expected_resource="negotiation/thread-17",
            expected_request_id=response.request_id,
        ).code == VerificationCode.VERIFIED

    replacement_only = TrustedIdentitySet(identities=(eip191_signer.identity,))
    assert verify_response(
        responses[0],
        body=body,
        now=NOW,
        max_skew=300,
        expected_role="storefront",
        expected_principals=replacement_only,
        expected_method="POST",
        expected_operation="negotiation.advance",
        expected_resource="negotiation/thread-17",
        expected_request_id=responses[0].request_id,
    ).code == VerificationCode.WRONG_PRINCIPAL


@pytest.mark.parametrize(
    "field",
    (
        "role",
        "principal",
        "method",
        "operation",
        "resource",
        "request_id",
        "timestamp",
        "status",
        "body_hash",
    ),
)
def test_every_signed_response_field_mutation_invalidates_proof(
    signer: Signer,
    field: str,
) -> None:
    body = {"state": "accepted"}
    envelope = ResponseEnvelope(
        role="storefront",
        principal=signer.identity,
        method="POST",
        operation="negotiation.advance",
        resource="negotiation/thread-17",
        request_id="7f0ed41b-6ad8-4a1f-94dc-80691c28b841",
        timestamp=NOW,
        status=202,
        body_hash=canonical_body_hash(body),
    )
    response = sign_response(signer=signer, envelope=envelope)
    changes: dict[str, Any] = {
        "role": "authority",
        "method": "PUT",
        "operation": "negotiation.cancel",
        "resource": "negotiation/thread-18",
        "request_id": "changed-response-id",
        "timestamp": NOW + 1,
        "status": 200,
        "body_hash": canonical_body_hash({"state": "changed"}),
    }
    if signer.identity.scheme.value == "ed25519":
        changes["principal"] = Ed25519Signer(b"\x01" * 32).identity
    else:
        changes["principal"] = Eip191Signer(b"\x01" * 32).identity
    raw = response.model_dump(mode="python")
    raw[field] = changes[field]
    mutated = AuthenticatedResponse.model_validate(raw)
    mutated_body = {"state": "changed"} if field == "body_hash" else body
    result = verify_response(
        mutated,
        body=mutated_body,
        now=mutated.timestamp,
        max_skew=300,
        expected_role=mutated.role,
        expected_principals=TrustedIdentitySet(identities=(mutated.principal,)),
        expected_method=mutated.method,
        expected_operation=mutated.operation,
        expected_resource=mutated.resource,
        expected_request_id=mutated.request_id,
    )
    assert result.code == VerificationCode.INVALID_PROOF


def test_response_rejects_old_version_and_wrong_body(signer: Signer) -> None:
    body = {"state": "accepted"}
    envelope = ResponseEnvelope(
        role="storefront",
        principal=signer.identity,
        method="POST",
        operation="negotiation.advance",
        resource="negotiation/thread-17",
        request_id="7f0ed41b-6ad8-4a1f-94dc-80691c28b841",
        timestamp=NOW,
        status=200,
        body_hash=canonical_body_hash(body),
    )
    response = sign_response(signer=signer, envelope=envelope)
    assert _response_result(response, body={"state": "rejected"}).code == (
        VerificationCode.BODY_HASH_MISMATCH
    )
    raw = response.model_dump(mode="json")
    raw["protocol"] = "arkhai.market-response-signature.v1"
    principal = response.principal
    result = verify_response(
        raw,
        body=body,
        now=NOW,
        max_skew=300,
        expected_role="storefront",
        expected_principals=TrustedIdentitySet(identities=(principal,)),
        expected_method="POST",
        expected_operation="negotiation.advance",
        expected_resource="negotiation/thread-17",
        expected_request_id=response.request_id,
    )
    assert result.code == VerificationCode.UNSUPPORTED_VERSION


def test_envelope_models_are_frozen_and_reject_extra_fields(
    request_envelope: RequestEnvelope,
) -> None:
    with pytest.raises(ValidationError):
        request_envelope.role = "seller"
    with pytest.raises(ValidationError):
        RequestEnvelope(
            **request_envelope.model_dump(mode="python"),
            unsigned_query="changes-behavior",
        )
