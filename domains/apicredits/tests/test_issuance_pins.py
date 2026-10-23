"""Byte-for-byte pins of the issuance digests and evidence; the fixture is written once with ``--write``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from market_core import SettlementEvidence
from market_identity import Ed25519Signer, Identity

from arkhai_api.issuance import IssuanceRequest, KeyDisposition, fulfillment_id, issuance_request

from arkhai_apicredits.label import API_CREDITS_LABEL
from arkhai_apicredits.settlement.fulfillment import prepare_credit_issuance_request
from arkhai_apicredits.settlement.issuance_evidence import (
    ApiCreditsIssuanceEvidenceBodyV1,
    canonical_signed_issuance_evidence,
    encode_portable_issuance_fulfillment_ref,
    issuance_evidence_digest,
    sign_api_credits_issuance_evidence,
)

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "pins" / "issuance_pins.json"

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

RESOLVER_ID = "api-credit-resolver.v1"


def _issuance_request(case: dict[str, Any]) -> IssuanceRequest:
    return issuance_request(
        API_CREDITS_LABEL,
        negotiation_id=case["negotiation_id"],
        owner=case["owner"],
        service=case["service"],
        resource_id=case["resource_id"],
        quantity=case["quantity"],
        key=KeyDisposition.model_validate(case["key"]),
    )


def _settlement_evidence(case: dict[str, Any]) -> SettlementEvidence:
    key = case["key"]
    return SettlementEvidence(
        negotiation_id=case["negotiation_id"],
        mechanism="alkahest.v1",
        settlement_ref=case["obligation_ref"],
        status="verified",
        evidence={
            "kind": "api_credits.settlement-evidence.v1",
            "schema_version": 1,
            "agreement_digest": "a" * 64,
            "source": {"obligation_ref": case["obligation_ref"]},
            "delivery": {
                "owner": case["owner"].model_dump(mode="json"),
                "listing_resource": {
                    "service_name": case["service"],
                    "resource_id": case["resource_id"],
                },
                "quantity": case["quantity"],
                "key_mode": key["mode"],
                "key_id": key.get("key_id"),
            },
        },
    )


def _signed_evidence(case: dict[str, Any], request: IssuanceRequest):
    body = ApiCreditsIssuanceEvidenceBodyV1(
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
    )
    return sign_api_credits_issuance_evidence(body, ISSUER)


def _inputs(case: dict[str, Any]) -> dict[str, Any]:
    return {
        **{k: v for k, v in case.items() if k != "owner"},
        "owner": case["owner"].model_dump(mode="json"),
        "claimant": CLAIMANT.model_dump(mode="json"),
        "issuer": ISSUER.identity.model_dump(mode="json"),
        "resolver_id": RESOLVER_ID,
    }


def compute_pins(case: dict[str, Any]) -> dict[str, Any]:
    request = _issuance_request(case)
    evidence = _signed_evidence(case, request)
    evidence_digest = issuance_evidence_digest(evidence)
    return {
        "fulfillment_id": request.fulfillment_id,
        "request_digest": request.request_digest,
        "evidence_digest": evidence_digest,
        "signed_evidence": canonical_signed_issuance_evidence(evidence),
        "portable_fulfillment_ref": encode_portable_issuance_fulfillment_ref(
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
        ]
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


def test_the_fulfillment_identity_is_derived_from_the_negotiation_alone() -> None:
    for case in CASES:
        pins = compute_pins(case)
        assert pins["fulfillment_id"] == fulfillment_id(API_CREDITS_LABEL, case["negotiation_id"])


def test_the_storefronts_evidence_path_authorizes_the_pinned_request() -> None:
    recorded = {c["name"]: c["expected"] for c in load_fixture()["cases"]}
    for case in CASES:
        prepared = prepare_credit_issuance_request(evidence=_settlement_evidence(case))
        assert prepared.fulfillment_id == recorded[case["name"]]["fulfillment_id"]
        assert prepared.request_digest == recorded[case["name"]]["request_digest"]


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="write the fixture; refuses to overwrite")
    args = parser.parse_args(argv)
    if not args.write:
        parser.error("nothing to do without --write")
    if FIXTURE.exists():
        print(f"{FIXTURE} exists and is never rewritten", file=sys.stderr)
        return 1
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(build_fixture(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {FIXTURE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
