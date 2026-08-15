from __future__ import annotations

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet

from domains.apicredits.settlement.issuance_evidence import (
    ApiCreditsIssuanceEvidenceBodyV1,
    ExpectedApiCreditsIssuanceEvidenceV1,
    IssuanceEvidenceError,
    canonical_signed_issuance_evidence,
    decode_signed_issuance_evidence,
    encode_portable_issuance_fulfillment_ref,
    issuance_evidence_digest,
    sign_api_credits_issuance_evidence,
    verify_api_credits_issuance_evidence,
)


def _fixture():
    issuer_signer = Ed25519Signer(bytes(range(32)))
    buyer = Ed25519Signer(bytes(range(1, 33))).identity
    claimant = Ed25519Signer(bytes(range(2, 34))).identity
    body = ApiCreditsIssuanceEvidenceBodyV1(
        condition_anchor="condition:abc",
        obligation_ref="obligation:abc",
        fulfillment_id="api-credit-fulfillment.v1:" + "a" * 64,
        grant_id="api-credit-fulfillment.v1:" + "a" * 64,
        service="inference",
        resource_id="quota-main",
        quantity=7,
        key_mode="new",
        key_id="ak_public",
        owner=buyer,
        buyer=buyer,
        claimant=claimant,
        issuer=issuer_signer.identity,
        committed_at_unix=2_000_000_000,
        request_digest="sha256:" + "b" * 64,
    )
    expected = ExpectedApiCreditsIssuanceEvidenceV1(
        **body.model_dump(
            exclude={
                "protocol",
                "schema_version",
                "capability",
                "domain",
                "status",
                "committed_at_unix",
            }
        ),
        funding_expiration_unix=2_000_000_100,
    )
    return issuer_signer, body, expected


def test_signed_evidence_is_canonical_verifiable_and_secret_free():
    signer, body, expected = _fixture()
    evidence = sign_api_credits_issuance_evidence(body, signer)
    encoded = canonical_signed_issuance_evidence(evidence)

    assert decode_signed_issuance_evidence(encoded) == evidence
    assert issuance_evidence_digest(evidence).startswith("sha256:")
    assert "secret" not in encoded.lower()
    assert verify_api_credits_issuance_evidence(
        evidence,
        expected=expected,
        trusted_issuers=TrustedIdentitySet(identities=(signer.identity,)),
        now_unix=2_000_000_010,
    ) == body


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("condition_anchor", "condition:other"),
        ("obligation_ref", "obligation:other"),
        ("service", "other-service"),
        ("resource_id", "other-quota"),
        ("quantity", 8),
        ("key_id", "ak_other"),
        ("key_mode", "existing"),
        ("claimant", Ed25519Signer(bytes(range(4, 36))).identity),
        ("request_digest", "sha256:" + "d" * 64),
    ],
)
def test_exact_mismatch_fails_closed(field_name, changed_value):
    signer, body, expected = _fixture()
    evidence = sign_api_credits_issuance_evidence(body, signer)
    changed = expected.model_copy(update={field_name: changed_value})

    with pytest.raises(IssuanceEvidenceError, match=field_name):
        verify_api_credits_issuance_evidence(
            evidence,
            expected=changed,
            trusted_issuers=TrustedIdentitySet(identities=(signer.identity,)),
            now_unix=2_000_000_010,
        )


def test_signature_and_timely_commit_fail_closed():
    signer, body, expected = _fixture()
    other_signer = Ed25519Signer(bytes(range(3, 35)))
    evidence = sign_api_credits_issuance_evidence(
        body.model_copy(update={"issuer": other_signer.identity}),
        other_signer,
    )
    with pytest.raises(IssuanceEvidenceError, match="issuer"):
        verify_api_credits_issuance_evidence(
            evidence,
            expected=expected,
            trusted_issuers=TrustedIdentitySet(identities=(signer.identity,)),
            now_unix=2_000_000_010,
        )

    late = sign_api_credits_issuance_evidence(
        body.model_copy(update={"committed_at_unix": 2_000_000_101}),
        signer,
    )
    with pytest.raises(IssuanceEvidenceError, match="after funding expiry"):
        verify_api_credits_issuance_evidence(
            late,
            expected=expected,
            trusted_issuers=TrustedIdentitySet(identities=(signer.identity,)),
            now_unix=2_000_000_101,
        )


def test_portable_ref_contains_only_safe_resolver_attestation_and_digest():
    encoded = encode_portable_issuance_fulfillment_ref(
        resolver_id="api-credit-resolver.v1",
        attestation_uid="attestation:opaque",
        evidence_digest="sha256:" + "c" * 64,
    )
    assert "secret" not in encoded.lower()
    assert "provider" not in encoded.lower()
    assert "sha256:" in encoded
