from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from market_identity import (
    Ed25519Signer,
    Eip191Signer,
    RotationIntent,
    RotationRequest,
    SignatureProof,
    canonical_rotation_bytes,
    sign_rotation,
    verify_rotation,
)
from conftest import NOW


def _intent(
    current: Ed25519Signer,
    replacement: Eip191Signer,
) -> RotationIntent:
    return RotationIntent(
        current=current.identity,
        replacement=replacement.identity,
        subject="publisher/pub-17",
        authority="registry/main",
        nonce="rotation-7f0ed41b",
        overlap_seconds=86_400,
        expires_at=NOW + 600,
    )


def test_rotation_signs_identical_canonical_bytes_with_both_schemes(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    intent = _intent(ed25519_signer, eip191_signer)
    request = sign_rotation(
        current_signer=ed25519_signer,
        replacement_signer=eip191_signer,
        intent=intent,
    )
    message = canonical_rotation_bytes(intent)
    assert request.current_proof.to_bytes() == ed25519_signer.sign(message)
    assert request.replacement_proof.to_bytes() == eip191_signer.sign(message)
    result = verify_rotation(request, now=NOW)
    assert result.current_valid is True
    assert result.replacement_valid is True
    assert result.expired is False
    assert result.verified is True


def test_rotation_canonical_fixture_is_length_delimited(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    intent = _intent(ed25519_signer, eip191_signer)
    fields = (
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
    expected = b"".join(
        len(field.encode()).to_bytes(4, "big") + field.encode() for field in fields
    )
    assert canonical_rotation_bytes(intent) == expected


def test_any_rotation_intent_mutation_invalidates_both_proofs(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    intent = _intent(ed25519_signer, eip191_signer)
    request = sign_rotation(
        current_signer=ed25519_signer,
        replacement_signer=eip191_signer,
        intent=intent,
    )
    mutations: dict[str, Any] = {
        "current": Ed25519Signer(b"\x02" * 32).identity,
        "replacement": Eip191Signer(b"\x02" * 32).identity,
        "subject": "publisher/pub-18",
        "authority": "registry/backup",
        "nonce": "rotation-changed",
        "overlap_seconds": 1,
        "expires_at": NOW + 601,
    }
    for field, value in mutations.items():
        data = intent.model_dump(mode="python")
        data[field] = value
        mutated_intent = RotationIntent.model_validate(data)
        mutated = RotationRequest(
            intent=mutated_intent,
            current_proof=request.current_proof,
            replacement_proof=request.replacement_proof,
        )
        result = verify_rotation(mutated, now=NOW)
        assert result.current_valid is False
        assert result.replacement_valid is False
        assert result.verified is False


def test_rotation_requires_both_proofs_and_matching_schemes(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    intent = _intent(ed25519_signer, eip191_signer)
    request = sign_rotation(
        current_signer=ed25519_signer,
        replacement_signer=eip191_signer,
        intent=intent,
    )
    raw = request.model_dump(mode="python")
    raw.pop("replacement_proof")
    with pytest.raises(ValidationError):
        RotationRequest.model_validate(raw)
    with pytest.raises(ValidationError):
        RotationRequest(
            intent=intent,
            current_proof=request.replacement_proof,
            replacement_proof=request.replacement_proof,
        )


def test_rotation_rejects_unknown_protocol_version(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    data = _intent(ed25519_signer, eip191_signer).model_dump(mode="python")
    data["protocol"] = "arkhai.market-identity-rotation.v2"
    with pytest.raises(ValidationError):
        RotationIntent.model_validate(data)


def test_rotation_expiry_is_fail_closed_at_one_second_past_expiry(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    intent = _intent(ed25519_signer, eip191_signer)
    request = sign_rotation(
        current_signer=ed25519_signer,
        replacement_signer=eip191_signer,
        intent=intent,
    )
    assert verify_rotation(request, now=intent.expires_at).verified is True
    expired = verify_rotation(request, now=intent.expires_at + 1)
    assert expired.expired is True
    assert expired.verified is False


def test_rotation_rejects_same_principal_and_mismatched_signers(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    with pytest.raises(ValidationError):
        RotationIntent(
            current=ed25519_signer.identity,
            replacement=ed25519_signer.identity,
            subject="publisher/pub-17",
            authority="registry/main",
            nonce="rotation-same",
            overlap_seconds=60,
            expires_at=NOW + 600,
        )
    intent = _intent(ed25519_signer, eip191_signer)
    with pytest.raises(ValueError, match="current signer identity"):
        sign_rotation(
            current_signer=eip191_signer,
            replacement_signer=eip191_signer,
            intent=intent,
        )
    with pytest.raises(ValueError, match="replacement signer identity"):
        sign_rotation(
            current_signer=ed25519_signer,
            replacement_signer=ed25519_signer,
            intent=intent,
        )


def test_malformed_rotation_proof_is_rejected_before_verification(
    ed25519_signer: Ed25519Signer,
    eip191_signer: Eip191Signer,
) -> None:
    intent = _intent(ed25519_signer, eip191_signer)
    with pytest.raises(ValidationError):
        RotationRequest(
            intent=intent,
            current_proof=SignatureProof(
                scheme="ed25519",
                value="A" * 85,
            ),
            replacement_proof=SignatureProof.from_bytes(
                eip191_signer.identity.scheme,
                eip191_signer.sign(canonical_rotation_bytes(intent)),
            ),
        )
