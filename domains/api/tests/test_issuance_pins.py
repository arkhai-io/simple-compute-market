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
    KeyDisposition,
    fulfillment_id,
    issuance_request,
    issuance_request_digest,
    issuance_request_model,
    issuance_result_model,
)
from arkhai_api.labels import IssuanceLabel

PINS = (
    Path(__file__).resolve().parents[3]
    / "domains"
    / "apicredits"
    / "tests"
    / "fixtures"
    / "pins"
    / "issuance_pins.json"
)
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
