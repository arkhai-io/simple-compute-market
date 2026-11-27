"""The API-credits pins replayed through the vocabulary under the label `api-credits`."""

import json
from pathlib import Path
from typing import Any

import pytest
from market_identity import Ed25519Signer, Identity
from pydantic import ValidationError

from arkhai_api.evidence import (
    IssuanceEvidenceBodyV1,
    IssuanceEvidenceError,
    canonical_signed_issuance_evidence,
    decode_signed_issuance_evidence,
    encode_portable_fulfillment_ref,
    issuance_evidence_digest,
    sign_issuance_evidence,
)
from arkhai_api.issuance import (
    ACCEPTED_TERMS_FIELDS,
    MAX_REQUEST_CHARGE,
    KeyDisposition,
    accepted_terms_digest,
    fulfillment_id,
    issuance_request,
    issuance_request_digest,
    issuance_request_model,
    issuance_result_model,
)
from arkhai_api.labels import IssuanceLabel

PINS = Path(__file__).resolve().parents[1] / "fixtures" / "pins" / "issuance_pins.json"
API_CREDITS = IssuanceLabel("api-credits", "api-credit-fulfillment.v1")
INFERENCE = IssuanceLabel("inference")
# The pins' deterministic development issuer; never used on any network.
ISSUER = Ed25519Signer(bytes(range(32)))

CASES = json.loads(PINS.read_text(encoding="utf-8"))["cases"]


def _pins(label: IssuanceLabel, inputs: dict[str, Any]) -> dict[str, str]:
    owner = Identity.model_validate(inputs["owner"])
    request = issuance_request(
        label,
        negotiation_id=inputs["negotiation_id"],
        owner=owner,
        service=inputs["service"],
        resource_id=inputs["resource_id"],
        quantity=inputs["quantity"],
        key=KeyDisposition.model_validate(inputs["key"]),
    )
    body = IssuanceEvidenceBodyV1(
        domain=label.name,
        condition_anchor=inputs["condition_anchor"],
        obligation_ref=inputs["obligation_ref"],
        fulfillment_id=request.fulfillment_id,
        grant_id=request.fulfillment_id,
        service=inputs["service"],
        resource_id=inputs["resource_id"],
        quantity=inputs["quantity"],
        key_mode=inputs["key"]["mode"],
        key_id=inputs["key_id"],
        owner=owner,
        buyer=owner,
        claimant=Identity.model_validate(inputs["claimant"]),
        issuer=ISSUER.identity,
        committed_at_unix=inputs["committed_at_unix"],
        request_digest=request.request_digest,
    )
    evidence = sign_issuance_evidence(label, body, ISSUER)
    evidence_digest = issuance_evidence_digest(label, evidence)
    return {
        "fulfillment_id": request.fulfillment_id,
        "request_digest": request.request_digest,
        "evidence_digest": evidence_digest,
        "signed_evidence": canonical_signed_issuance_evidence(evidence),
        "portable_fulfillment_ref": encode_portable_fulfillment_ref(
            label,
            resolver_id=inputs["resolver_id"],
            attestation_uid=inputs["attestation_uid"],
            evidence_digest=evidence_digest,
        ),
    }


def test_the_pins_record_this_issuer():
    for case in CASES:
        assert case["inputs"]["issuer"] == ISSUER.identity.model_dump(mode="json")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_every_pin_matches_byte_for_byte_under_api_credits(case):
    assert _pins(API_CREDITS, case["inputs"]) == case["expected"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_the_fulfillment_identity_is_derived_from_the_negotiation_alone(case):
    expected = case["expected"]["fulfillment_id"]
    assert fulfillment_id(API_CREDITS, case["inputs"]["negotiation_id"]) == expected
    assert expected.startswith("api-credit-fulfillment.v1:")


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_the_same_inputs_under_inference_differ_in_every_value(case):
    under_inference = _pins(INFERENCE, case["inputs"])
    for name, value in case["expected"].items():
        assert under_inference[name] != value, name
    assert under_inference["fulfillment_id"].startswith("inference-fulfillment.v1:")


def test_each_label_accepts_only_its_own_request():
    inputs = CASES[0]["inputs"]
    request = issuance_request(
        API_CREDITS,
        negotiation_id=inputs["negotiation_id"],
        owner=Identity.model_validate(inputs["owner"]),
        service=inputs["service"],
        resource_id=inputs["resource_id"],
        quantity=inputs["quantity"],
        key=KeyDisposition.model_validate(inputs["key"]),
    )
    wire = request.model_dump(mode="json", exclude_none=True)
    assert issuance_request_model(API_CREDITS).model_validate(wire) == request
    with pytest.raises(ValidationError):
        issuance_request_model(INFERENCE).model_validate(wire)
    with pytest.raises(ValidationError):
        issuance_request_model(INFERENCE).model_validate({**wire, "schema": INFERENCE.issuance_request_schema})
    assert issuance_request_digest(INFERENCE, request) != request.request_digest


def test_a_result_holds_only_under_its_label():
    inputs = CASES[0]["inputs"]
    identity = fulfillment_id(API_CREDITS, inputs["negotiation_id"])
    wire = {
        "schema": API_CREDITS.issuance_result_schema,
        "negotiation_id": inputs["negotiation_id"],
        "fulfillment_id": identity,
        "grant_id": identity,
        "owner": inputs["owner"],
        "service": inputs["service"],
        "resource_id": inputs["resource_id"],
        "quantity": inputs["quantity"],
        "key_mode": "new",
        "key_id": inputs["key_id"],
        "balance": inputs["quantity"],
        "request_digest": CASES[0]["expected"]["request_digest"],
        "committed_at_unix": inputs["committed_at_unix"],
        "secret": f"{inputs['key_id']}.private",
    }
    result = issuance_result_model(API_CREDITS).model_validate(wire)
    assert result.secret == wire["secret"]
    assert "secret" not in result.model_dump(mode="json")
    with pytest.raises(ValidationError):
        issuance_result_model(INFERENCE).model_validate({**wire, "schema": INFERENCE.issuance_result_schema})
    with pytest.raises(ValidationError):
        issuance_result_model(API_CREDITS).model_validate({**wire, "key_mode": "existing"})


def test_evidence_decodes_only_under_its_label():
    recorded = CASES[0]["expected"]["signed_evidence"]
    assert canonical_signed_issuance_evidence(decode_signed_issuance_evidence(API_CREDITS, recorded)) == recorded
    with pytest.raises(IssuanceEvidenceError):
        decode_signed_issuance_evidence(INFERENCE, recorded)


# Accepted terms

ACCEPTED_TERMS = {"attestation": None, "rate_card": {"asset": "USD/6", "request_credits": 1}}


def _with_terms(label: IssuanceLabel = INFERENCE, **terms: Any):
    inputs = CASES[0]["inputs"]
    return issuance_request(
        label,
        negotiation_id=inputs["negotiation_id"],
        owner=Identity.model_validate(inputs["owner"]),
        service=inputs["service"],
        resource_id=inputs["resource_id"],
        quantity=inputs["quantity"],
        key=KeyDisposition.model_validate(inputs["key"]),
        **terms,
    )


def _terms(**overrides: Any) -> dict[str, Any]:
    terms = {
        "accepted_terms": ACCEPTED_TERMS,
        "terms_digest": accepted_terms_digest(ACCEPTED_TERMS),
        "request_charge": 1,
    }
    return {**terms, **overrides}


def test_a_request_without_terms_serialises_none_of_them():
    assert not set(ACCEPTED_TERMS_FIELDS) & set(_with_terms(API_CREDITS).model_dump(mode="json"))


def test_a_request_with_terms_digests_the_digest_and_charge_and_not_the_payload():
    request = _with_terms(**_terms())
    assert request.model_dump(mode="json")["accepted_terms"] == ACCEPTED_TERMS
    unpinned = _with_terms()
    assert request.request_digest != unpinned.request_digest
    other_payload = {"attestation": {"kind": "x"}, "rate_card": ACCEPTED_TERMS["rate_card"]}
    # The same digest and charge over another payload digest identically; the
    # model refuses that pairing, so it is checked through the digest function.
    assert issuance_request_digest(INFERENCE, request) == issuance_request_digest(
        INFERENCE, request.model_copy(update={"accepted_terms": other_payload})
    )
    assert issuance_request_digest(INFERENCE, request) != issuance_request_digest(
        INFERENCE, request.model_copy(update={"request_charge": 2})
    )
    wire = request.model_dump(mode="json")
    assert issuance_request_model(INFERENCE).model_validate(wire) == request


def test_terms_are_set_together_and_their_digest_matches_the_payload():
    with pytest.raises(ValidationError, match="does not match accepted_terms"):
        _with_terms(**_terms(terms_digest="sha256:" + "0" * 64))
    with pytest.raises(ValidationError, match="set together"):
        _with_terms(**_terms(request_charge=None))


def test_the_request_charge_is_bounded_by_the_canonical_integer_domain():
    assert _with_terms(**_terms(request_charge=MAX_REQUEST_CHARGE)).request_charge == 2**53 - 1
    for charge in (0, 2**53):
        with pytest.raises(ValidationError, match="request_charge|less than or equal|greater than"):
            _with_terms(**_terms(request_charge=charge))


def test_a_wire_request_outside_the_charge_domain_is_refused_by_the_model():
    wire = _with_terms(**_terms()).model_dump(mode="json")
    for charge in (0, 2**53):
        with pytest.raises(ValidationError, match="request_charge"):
            issuance_request_model(INFERENCE).model_validate({**wire, "request_charge": charge})
