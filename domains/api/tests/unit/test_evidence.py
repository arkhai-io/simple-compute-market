import json

import pytest
from market_identity import Ed25519Signer, TrustedIdentitySet
from pydantic import ValidationError

from arkhai_api.evidence import (
    ExpectedIssuanceEvidenceV1,
    IssuanceEvidenceBodyV1,
    IssuanceEvidenceError,
    canonical_signed_issuance_evidence,
    decode_portable_fulfillment_ref,
    decode_signed_issuance_evidence,
    encode_portable_fulfillment_ref,
    issuance_evidence_digest,
    sign_issuance_evidence,
    verify_issuance_evidence,
)
from arkhai_api.labels import IssuanceLabel

LABEL = IssuanceLabel("weather")
OTHER = IssuanceLabel("climate")
# Deterministic development keys for this test only; never used on any network.
ISSUER = Ed25519Signer(bytes(range(32)))
BUYER = Ed25519Signer(bytes(range(1, 33))).identity
CLAIMANT = Ed25519Signer(bytes(range(2, 34))).identity
TRUSTED = TrustedIdentitySet(identities=(ISSUER.identity,))


def _body(**overrides) -> IssuanceEvidenceBodyV1:
    fields = {
        "domain": LABEL.name,
        "condition_anchor": "condition:abc",
        "obligation_ref": "obligation:abc",
        "fulfillment_id": "weather-fulfillment.v1:" + "a" * 64,
        "grant_id": "weather-fulfillment.v1:" + "a" * 64,
        "service": "weather-api",
        "resource_id": "quota-main",
        "quantity": 7,
        "key_mode": "new",
        "key_id": "ak_public",
        "owner": BUYER,
        "buyer": BUYER,
        "claimant": CLAIMANT,
        "issuer": ISSUER.identity,
        "committed_at_unix": 2_000_000_000,
        "request_digest": "sha256:" + "b" * 64,
    }
    return IssuanceEvidenceBodyV1(**{**fields, **overrides})


def _expected(body: IssuanceEvidenceBodyV1, **overrides) -> ExpectedIssuanceEvidenceV1:
    fields = body.model_dump(
        exclude={"protocol", "schema_version", "capability", "domain", "status", "committed_at_unix"}
    )
    return ExpectedIssuanceEvidenceV1(**{**fields, "funding_expiration_unix": 2_000_000_100, **overrides})


def test_the_body_spells_its_protocol_and_capability_from_its_domain():
    body = _body()
    assert (body.protocol, body.capability) == ("arkhai.weather.issuance-evidence.v1", "weather.issuance.v1")
    with pytest.raises(ValueError):
        _body(protocol=OTHER.evidence_protocol)
    with pytest.raises(ValueError):
        _body(domain="Weather")
    with pytest.raises(ValueError):
        _body(buyer=CLAIMANT)
    with pytest.raises(ValueError):
        _body(grant_id="weather-fulfillment.v1:" + "c" * 64)


def test_signed_evidence_is_canonical_verifiable_and_secret_free():
    body = _body()
    evidence = sign_issuance_evidence(LABEL, body, ISSUER)
    encoded = canonical_signed_issuance_evidence(evidence)
    assert "secret" not in json.loads(encoded)["body"]
    decoded = decode_signed_issuance_evidence(LABEL, encoded)
    assert decoded == evidence
    assert issuance_evidence_digest(LABEL, decoded) == issuance_evidence_digest(LABEL, evidence)
    verified = verify_issuance_evidence(
        LABEL, decoded, expected=_expected(body), trusted_issuers=TRUSTED, now_unix=2_000_000_050
    )
    assert verified == body


def test_every_operation_refuses_another_label():
    evidence = sign_issuance_evidence(LABEL, _body(), ISSUER)
    with pytest.raises(IssuanceEvidenceError):
        sign_issuance_evidence(OTHER, _body(), ISSUER)
    with pytest.raises(IssuanceEvidenceError):
        issuance_evidence_digest(OTHER, evidence)
    with pytest.raises(IssuanceEvidenceError):
        decode_signed_issuance_evidence(OTHER, canonical_signed_issuance_evidence(evidence))
    with pytest.raises(IssuanceEvidenceError):
        verify_issuance_evidence(
            OTHER, evidence, expected=_expected(evidence.body), trusted_issuers=TRUSTED, now_unix=2_000_000_050
        )


def test_non_canonical_or_oversized_evidence_is_refused():
    evidence = sign_issuance_evidence(LABEL, _body(), ISSUER)
    pretty = json.dumps(json.loads(canonical_signed_issuance_evidence(evidence)), indent=2)
    with pytest.raises(IssuanceEvidenceError):
        decode_signed_issuance_evidence(LABEL, pretty)
    with pytest.raises(IssuanceEvidenceError):
        decode_signed_issuance_evidence(LABEL, "{" + " " * 40_000 + "}")
    with pytest.raises(IssuanceEvidenceError):
        decode_signed_issuance_evidence(LABEL, "not json")


def test_a_wrong_signer_is_refused_and_a_tampered_body_fails_verification():
    body = _body()
    with pytest.raises(IssuanceEvidenceError):
        sign_issuance_evidence(LABEL, body, Ed25519Signer(bytes(range(3, 35))))
    evidence = sign_issuance_evidence(LABEL, body, ISSUER)
    tampered = evidence.model_copy(update={"body": body.model_copy(update={"quantity": 8})})
    with pytest.raises(IssuanceEvidenceError, match="signature is invalid"):
        verify_issuance_evidence(
            LABEL, tampered, expected=_expected(tampered.body), trusted_issuers=TRUSTED, now_unix=2_000_000_050
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"funding_expiration_unix": 1_999_999_999}, "after funding expiry"),
        ({"quantity": 8}, "quantity does not match"),
        ({"issuer": CLAIMANT}, "issuer is not trusted"),
    ],
)
def test_verification_compares_every_accepted_fact(overrides, message):
    body = _body()
    evidence = sign_issuance_evidence(LABEL, body, ISSUER)
    with pytest.raises(IssuanceEvidenceError, match=message):
        verify_issuance_evidence(
            LABEL, evidence, expected=_expected(body, **overrides), trusted_issuers=TRUSTED, now_unix=2_000_000_050
        )


def test_a_commitment_in_the_future_is_refused():
    body = _body()
    evidence = sign_issuance_evidence(LABEL, body, ISSUER)
    with pytest.raises(IssuanceEvidenceError, match="in the future"):
        verify_issuance_evidence(
            LABEL, evidence, expected=_expected(body), trusted_issuers=TRUSTED, now_unix=1_999_999_000
        )


def test_the_portable_reference_round_trips_under_its_label_only():
    digest = "sha256:" + "d" * 64
    encoded = encode_portable_fulfillment_ref(
        LABEL, resolver_id="weather-resolver.v1", attestation_uid="attestation:1", evidence_digest=digest
    )
    assert json.loads(encoded)["schema"] == LABEL.portable_fulfillment_ref_schema
    ref = decode_portable_fulfillment_ref(LABEL, encoded)
    assert (ref.resolver_id, ref.attestation_uid, ref.evidence_digest) == ("weather-resolver.v1", "attestation:1", digest)
    with pytest.raises(IssuanceEvidenceError):
        decode_portable_fulfillment_ref(OTHER, encoded)
    with pytest.raises(IssuanceEvidenceError):
        decode_portable_fulfillment_ref(LABEL, json.dumps(json.loads(encoded), indent=1))
    with pytest.raises(ValidationError):
        encode_portable_fulfillment_ref(
            LABEL, resolver_id="bad resolver", attestation_uid="attestation:1", evidence_digest=digest
        )
