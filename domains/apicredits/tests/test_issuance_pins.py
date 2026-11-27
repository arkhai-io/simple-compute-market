"""Byte-for-byte pins of the issuance digests and evidence; each case set is written once with ``--write``.

The API-credits cases pin no terms; one inference-label case records a pinned issuance's bytes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from market_identity import Ed25519Signer, Identity, canonical_json

from arkhai_api.evidence import (
    IssuanceEvidenceBodyV1,
    canonical_signed_issuance_evidence,
    encode_portable_fulfillment_ref,
    issuance_evidence_digest,
    sign_issuance_evidence,
)
from arkhai_api.issuance import (
    IssuanceRequest,
    KeyDisposition,
    accepted_terms_digest,
    fulfillment_id,
    issuance_request,
)
from arkhai_api.labels import IssuanceLabel

from arkhai_apicredits.label import API_CREDITS_LABEL

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "domains" / "api" / "tests" / "fixtures" / "pins" / "issuance_pins.json"
)

# Deterministic development keys for this test only; never used on any network.
ISSUER = Ed25519Signer(bytes(range(32)))
CLAIMANT = Ed25519Signer(bytes(range(2, 34))).identity
ED25519_OWNER_A = Ed25519Signer(bytes(range(1, 33))).identity
ED25519_OWNER_B = Ed25519Signer(bytes(range(3, 35))).identity
EIP191_OWNER_A = Identity(
    scheme="eip191", identifier="0xabcdef0000000000000000000000000000000001"
)
EIP191_OWNER_B = Identity(
    scheme="eip191", identifier="0x9999000000000000000000000000000000000003"
)

CASES: tuple[dict[str, Any], ...] = (
    {
        "name": "new-key-eip191-small",
        "negotiation_id": "neg-pin-1",
        "owner": EIP191_OWNER_A,
        "service": "weather-api",
        "resource_id": "weather-quota",
        "quantity": 3,
        "key": {"mode": "new"},
        "key_id": "ak_0123456789abcdef",
        "condition_anchor": "condition:pin-1",
        "obligation_ref": "obligation:pin-1",
        "committed_at_unix": 2_000_000_000,
        "attestation_uid": "attestation:pin-1",
    },
    {
        "name": "existing-key-eip191-topup",
        "negotiation_id": "neg-pin-2",
        "owner": EIP191_OWNER_A,
        "service": "weather-api",
        "resource_id": "weather-quota",
        "quantity": 10,
        "key": {"mode": "existing", "key_id": "ak_0123456789abcdef"},
        "key_id": "ak_0123456789abcdef",
        "condition_anchor": "condition:pin-2",
        "obligation_ref": "obligation:pin-2",
        "committed_at_unix": 2_000_000_100,
        "attestation_uid": "attestation:pin-2",
    },
    {
        "name": "new-key-ed25519-single-unit",
        "negotiation_id": "neg-pin-3",
        "owner": ED25519_OWNER_A,
        "service": "weather-api",
        "resource_id": "weather-quota",
        "quantity": 1,
        "key": {"mode": "new"},
        "key_id": "ak_fedcba9876543210",
        "condition_anchor": "condition:pin-3",
        "obligation_ref": "obligation:pin-3",
        "committed_at_unix": 2_000_000_200,
        "attestation_uid": "attestation:pin-3",
    },
    {
        "name": "existing-key-ed25519-large",
        "negotiation_id": "neg-pin-4",
        "owner": ED25519_OWNER_B,
        "service": "inference",
        "resource_id": "quota-main",
        "quantity": 250,
        "key": {"mode": "existing", "key_id": "ak_fedcba9876543210"},
        "key_id": "ak_fedcba9876543210",
        "condition_anchor": "condition:pin-4",
        "obligation_ref": "obligation:pin-4",
        "committed_at_unix": 2_000_000_300,
        "attestation_uid": "attestation:pin-4",
    },
    {
        "name": "new-key-eip191-other-service",
        "negotiation_id": "neg-pin-5.with:punctuation_allowed-by-the-ref",
        "owner": EIP191_OWNER_B,
        "service": "inference",
        "resource_id": "quota-main",
        "quantity": 7,
        "key": {"mode": "new"},
        "key_id": "ak_00000000deadbeef",
        "condition_anchor": "condition:pin-5",
        "obligation_ref": "obligation:pin-5",
        "committed_at_unix": 2_000_000_400,
        "attestation_uid": "attestation:pin-5",
    },
)

INFERENCE_LABEL = IssuanceLabel("inference")
INFERENCE_TERMS = {
    "attestation": None,
    "rate_card": {
        "asset": "USD/6",
        "cached_prompt_per_mtok": 0,
        "completion_per_mtok": 0,
        "image_per_unit": 0,
        "prompt_per_mtok": 0,
        "request_credits": 1,
    },
}
INFERENCE_CASES: tuple[dict[str, Any], ...] = (
    {
        "name": "inference-new-key-with-terms",
        "negotiation_id": "neg-pin-inference-1",
        "owner": ED25519_OWNER_A,
        "service": "qwen2.5-0.5b-instruct",
        "resource_id": "inference-quota",
        "quantity": 2_000_000,
        "key": {"mode": "new"},
        "key_id": "ik_0123456789abcdef",
        "condition_anchor": "condition:pin-inference-1",
        "obligation_ref": "obligation:pin-inference-1",
        "committed_at_unix": 2_000_000_500,
        "attestation_uid": "attestation:pin-inference-1",
        "accepted_terms": INFERENCE_TERMS,
        "request_charge": 1,
    },
)

RESOLVER_ID = "api-credit-resolver.v1"
INFERENCE_RESOLVER_ID = "inference-resolver.v1"


def _terms(case: dict[str, Any]) -> dict[str, Any]:
    if "accepted_terms" not in case:
        return {}
    return {
        "accepted_terms": case["accepted_terms"],
        "terms_digest": accepted_terms_digest(case["accepted_terms"]),
        "request_charge": case["request_charge"],
    }


def _issuance_request(case: dict[str, Any], label: IssuanceLabel = API_CREDITS_LABEL) -> IssuanceRequest:
    return issuance_request(
        label,
        negotiation_id=case["negotiation_id"],
        owner=case["owner"],
        service=case["service"],
        resource_id=case["resource_id"],
        quantity=case["quantity"],
        key=KeyDisposition.model_validate(case["key"]),
        **_terms(case),
    )


def _signed_evidence(
    case: dict[str, Any], request: IssuanceRequest, label: IssuanceLabel = API_CREDITS_LABEL
):
    body = IssuanceEvidenceBodyV1(
        domain=label.name,
        condition_anchor=case["condition_anchor"],
        obligation_ref=case["obligation_ref"],
        fulfillment_id=request.fulfillment_id,
        grant_id=request.fulfillment_id,
        service=case["service"],
        resource_id=case["resource_id"],
        quantity=case["quantity"],
        key_mode=case["key"]["mode"],
        key_id=case["key_id"],
        owner=case["owner"],
        buyer=case["owner"],
        claimant=CLAIMANT,
        issuer=ISSUER.identity,
        committed_at_unix=case["committed_at_unix"],
        request_digest=request.request_digest,
        terms_digest=request.terms_digest,
        request_charge=request.request_charge,
    )
    return sign_issuance_evidence(label, body, ISSUER)


def _inputs(case: dict[str, Any], resolver_id: str = RESOLVER_ID) -> dict[str, Any]:
    return {
        **{k: v for k, v in case.items() if k != "owner"},
        "owner": case["owner"].model_dump(mode="json"),
        "claimant": CLAIMANT.model_dump(mode="json"),
        "issuer": ISSUER.identity.model_dump(mode="json"),
        "resolver_id": resolver_id,
    }


def compute_inference_pins(case: dict[str, Any]) -> dict[str, Any]:
    request = _issuance_request(case, INFERENCE_LABEL)
    evidence = _signed_evidence(case, request, INFERENCE_LABEL)
    evidence_digest = issuance_evidence_digest(INFERENCE_LABEL, evidence)
    return {
        "fulfillment_id": request.fulfillment_id,
        "request_digest": request.request_digest,
        "issuance_request": canonical_json(request.model_dump(mode="json")).decode("utf-8"),
        "evidence_digest": evidence_digest,
        "signed_evidence": canonical_signed_issuance_evidence(evidence),
        "portable_fulfillment_ref": encode_portable_fulfillment_ref(
            INFERENCE_LABEL,
            resolver_id=INFERENCE_RESOLVER_ID,
            attestation_uid=case["attestation_uid"],
            evidence_digest=evidence_digest,
        ),
        "api_credits_request_digest": _issuance_request(case).request_digest,
    }


def compute_pins(case: dict[str, Any]) -> dict[str, Any]:
    request = _issuance_request(case)
    evidence = _signed_evidence(case, request)
    evidence_digest = issuance_evidence_digest(API_CREDITS_LABEL, evidence)
    return {
        "fulfillment_id": request.fulfillment_id,
        "request_digest": request.request_digest,
        "evidence_digest": evidence_digest,
        "signed_evidence": canonical_signed_issuance_evidence(evidence),
        "portable_fulfillment_ref": encode_portable_fulfillment_ref(
            API_CREDITS_LABEL,
            resolver_id=RESOLVER_ID,
            attestation_uid=case["attestation_uid"],
            evidence_digest=evidence_digest,
        ),
    }


def build_fixture() -> dict[str, Any]:
    return {
        "cases": [
            {"name": case["name"], "inputs": _inputs(case), "expected": compute_pins(case)}
            for case in CASES
        ],
        "inference_cases": [
            {
                "name": case["name"],
                "inputs": _inputs(case, INFERENCE_RESOLVER_ID),
                "expected": compute_inference_pins(case),
            }
            for case in INFERENCE_CASES
        ],
    }


def load_fixture() -> dict[str, Any]:
    if not FIXTURE.exists():
        raise AssertionError(
            f"{FIXTURE} is missing; it is written once by "
            f"`python {Path(__file__).name} --write`"
        )
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_fixture_records_this_input_set() -> None:
    recorded = load_fixture()
    assert [c["name"] for c in recorded["cases"]] == [c["name"] for c in CASES]
    for recorded_case, case in zip(recorded["cases"], CASES, strict=True):
        assert recorded_case["inputs"] == _inputs(case), case["name"]


def test_every_pin_matches_byte_for_byte() -> None:
    recorded = {c["name"]: c["expected"] for c in load_fixture()["cases"]}
    for case in CASES:
        computed = compute_pins(case)
        for field_name, expected in recorded[case["name"]].items():
            assert computed[field_name] == expected, (
                f"{case['name']}: {field_name} changed\n"
                f"  recorded: {expected}\n  computed: {computed[field_name]}"
            )
        assert set(computed) == set(recorded[case["name"]]), case["name"]


def test_the_fixture_records_this_inference_input_set() -> None:
    recorded = load_fixture()["inference_cases"]
    assert [c["name"] for c in recorded] == [c["name"] for c in INFERENCE_CASES]
    for recorded_case, case in zip(recorded, INFERENCE_CASES, strict=True):
        assert recorded_case["inputs"] == _inputs(case, INFERENCE_RESOLVER_ID), case["name"]


def test_the_inference_case_matches_byte_for_byte() -> None:
    recorded = {c["name"]: c["expected"] for c in load_fixture()["inference_cases"]}
    for case in INFERENCE_CASES:
        assert compute_inference_pins(case) == recorded[case["name"]], case["name"]


def test_the_inference_case_carries_its_terms_where_they_are_digested_and_signed() -> None:
    for case in INFERENCE_CASES:
        pins = compute_inference_pins(case)
        digest = accepted_terms_digest(case["accepted_terms"])
        assert json.loads(pins["issuance_request"])["terms_digest"] == digest
        body = json.loads(pins["signed_evidence"])["body"]
        assert (body["terms_digest"], body["request_charge"]) == (digest, case["request_charge"])
        assert "accepted_terms" not in body
        assert pins["request_digest"] != pins["api_credits_request_digest"]


def test_the_fulfillment_identity_is_derived_from_the_negotiation_alone() -> None:
    for case in CASES:
        pins = compute_pins(case)
        assert pins["fulfillment_id"] == fulfillment_id(API_CREDITS_LABEL, case["negotiation_id"])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write the fixture; refuses to overwrite")
    args = parser.parse_args(argv)
    if not args.write:
        parser.error("nothing to do without --write")
    built = build_fixture()
    recorded = load_fixture() if FIXTURE.exists() else {}
    if all(name in recorded for name in built):
        print(f"{FIXTURE} records every case set and is never rewritten", file=sys.stderr)
        return 1
    # A recorded case set is kept byte for byte; only an absent one is added.
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps({**built, **recorded}, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {FIXTURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
