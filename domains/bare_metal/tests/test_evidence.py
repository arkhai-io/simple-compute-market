from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import (
    BareMetalAcceptedAlkahestBinding,
    BareMetalLeaseReadyEvidence,
    BareMetalLeaseReadyEvidenceDocument,
    BareMetalLeaseReadyResult,
    CanonicalPrincipal,
    bare_metal_digest,
    build_bare_metal_lease_ready_evidence,
    derive_bare_metal_fulfillment_identity,
)

from arkhai_bare_metal.evidence import canonical_bare_metal_json

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
BUYER = CanonicalPrincipal(scheme="ed25519", identifier="buyer")
SELLER = CanonicalPrincipal(scheme="ed25519", identifier="seller")
DIGEST = "sha256:" + "1" * 64


def lease_ready_result() -> BareMetalLeaseReadyResult:
    return BareMetalLeaseReadyResult(
        site_id="site-a",
        resource_selection="specific",
        physical_resource_id="resource-a",
        capacity_reservation_ref="reservation-a",
        settlement_resource_ref="settlement-resource-a",
        fulfillment_ref="fulfillment-a",
        access_ready_at=NOW + timedelta(minutes=40),
        expires_at=NOW + timedelta(minutes=50),
    )


def test_lease_ready_evidence_is_deterministic_and_binds_canonical_parties() -> None:
    binding = alkahest_binding()
    result = lease_ready_result()

    evidence = build_bare_metal_lease_ready_evidence(
        binding=binding,
        condition_anchor="condition-a",
        result=result,
    )

    assert evidence.result_digest == bare_metal_digest(result)
    assert evidence.fulfillment_identity == derive_bare_metal_fulfillment_identity(
        binding
    )
    assert evidence.buyer_principal == BUYER
    assert evidence.claimant_principal == SELLER
    assert evidence.canonical_json() == evidence.canonical_json()
    assert evidence.evidence_digest.startswith("sha256:")


def test_evidence_rejects_credentials_provider_data_and_changed_resource() -> None:
    result_payload = lease_ready_result().model_dump()
    for unsafe in (
        {"private_key": "secret"},
        {"provider_metadata": {"job": "provider-1"}},
        {"connection_details": "ssh://root@private"},
    ):
        with pytest.raises(ValidationError):
            BareMetalLeaseReadyResult.model_validate({**result_payload, **unsafe})

    with pytest.raises(ValueError, match="Physical Resource"):
        build_bare_metal_lease_ready_evidence(
            binding=alkahest_binding(),
            condition_anchor="condition-a",
            result=lease_ready_result().model_copy(
                update={"physical_resource_id": "resource-b"}
            ),
        )


def test_fungible_evidence_cannot_publish_assigned_physical_resource() -> None:
    payload = lease_ready_result().model_dump()
    payload["resource_selection"] = "fungible"
    with pytest.raises(
        ValidationError, match="keep assigned Physical Resource internal"
    ):
        BareMetalLeaseReadyResult.model_validate(payload)


def test_changed_result_digest_and_unknown_evidence_fields_fail_closed() -> None:
    evidence = build_bare_metal_lease_ready_evidence(
        binding=alkahest_binding(),
        condition_anchor="condition-a",
        result=lease_ready_result(),
    )
    payload = evidence.to_wire()
    payload["result_digest"] = "sha256:" + "f" * 64
    with pytest.raises(ValueError, match="does not match"):
        BareMetalLeaseReadyEvidenceDocument.from_wire(payload)
    payload = evidence.to_wire()
    payload["action_url"] = "https://provider.invalid/action"
    with pytest.raises(ValidationError):
        BareMetalLeaseReadyEvidenceDocument.from_wire(payload)


def alkahest_binding(**changes) -> BareMetalAcceptedAlkahestBinding:
    values = dict(
        agreement_ref="negotiation-a",
        negotiation_id="negotiation-a",
        listing_id="listing-a",
        obligation_ref="obligation-a",
        escrow_uid="0x" + "ab" * 32,
        accepted_plan_digest=DIGEST,
        buyer_principal=BUYER,
        seller_principal=SELLER,
        claimant_principal=SELLER,
        site_id="site-a",
        resource_selection="specific",
        physical_resource_id="resource-a",
        pool_id="pool-a",
    )
    values.update(changes)
    return BareMetalAcceptedAlkahestBinding(**values)


def test_alkahest_evidence_binds_the_escrow_plan_and_parties() -> None:
    binding = alkahest_binding()

    evidence = build_bare_metal_lease_ready_evidence(
        binding=binding,
        condition_anchor=binding.escrow_uid,
        result=lease_ready_result(),
    )

    assert evidence.accepted_binding_kind == "bare_metal.accepted-alkahest-binding.v1"
    assert evidence.accepted_binding_digest == binding.binding_digest
    assert evidence.condition_anchor == binding.escrow_uid
    assert evidence.fulfillment_identity == derive_bare_metal_fulfillment_identity(
        binding
    )
    assert evidence.buyer_principal == BUYER
    assert evidence.claimant_principal == SELLER
    assert (
        BareMetalLeaseReadyEvidence.model_validate_json(evidence.canonical_json())
        == evidence.value
    )


def test_alkahest_evidence_refuses_a_result_from_another_resource() -> None:
    with pytest.raises(ValueError, match="Physical Resource"):
        build_bare_metal_lease_ready_evidence(
            binding=alkahest_binding(physical_resource_id="resource-b"),
            condition_anchor="0x" + "ab" * 32,
            result=lease_ready_result(),
        )


def test_an_alkahest_binding_states_its_resource_selection_consistently() -> None:
    with pytest.raises(ValidationError):
        alkahest_binding(resource_selection="fungible")
    with pytest.raises(ValidationError):
        alkahest_binding(physical_resource_id=None)


GOLDEN_EVIDENCE = (
    '{"accepted_binding_digest":"sha256:880cad5e404e8c785c725ed0aea68a387eb537844a44adf54ee'
    '428abf39da151","accepted_binding_kind":"bare_metal.accepted-alkahest-binding.v1","agre'
    'ement_ref":"negotiation-a","buyer_principal":{"identifier":"buyer","scheme":"ed25519"}'
    ',"claimant_principal":{"identifier":"seller","scheme":"ed25519"},"condition_anchor":"c'
    'ondition-a","fulfillment_identity":"sha256:8de1d5c8f3fbf4c60b401deac9c9aba506cfbf34c04'
    'fbd583fce33f173e9437b","kind":"bare_metal.lease-ready-evidence.v1","obligation_ref":"o'
    'bligation-a","result":{"access_method":"ssh","access_ready":true,"access_ready_at":"20'
    '30-01-01T00:40:00Z","capacity_reservation_ref":"reservation-a","expires_at":"2030-01-0'
    '1T00:50:00Z","fulfillment_ref":"fulfillment-a","kind":"bare_metal.lease-ready-result.v'
    '1","offering_mode":"bare_metal","physical_resource_id":"resource-a","resource_selectio'
    'n":"specific","settlement_resource_ref":"settlement-resource-a","site_id":"site-a"},"r'
    'esult_digest":"sha256:ae51de1f73954f708cbf093708f1c7dbe5203b413c9dc3e37dc26a3523f7c339'
    '","seller_principal":{"identifier":"seller","scheme":"ed25519"}}'
)


def test_v1_production_pins_original_bytes_and_identities():
    evidence = build_bare_metal_lease_ready_evidence(
        binding=alkahest_binding(),
        condition_anchor="condition-a",
        result=lease_ready_result(),
    )
    assert evidence.canonical_bytes == GOLDEN_EVIDENCE.encode("utf-8")
    assert (
        evidence.evidence_digest
        == "sha256:eeb0e95abc054ba2bbd48771f4cc0b5ae4779eb7fee63238ca0cac5a65fde412"
    )
    assert (
        evidence.result_digest
        == "sha256:ae51de1f73954f708cbf093708f1c7dbe5203b413c9dc3e37dc26a3523f7c339"
    )
    assert (
        evidence.accepted_binding_digest
        == "sha256:880cad5e404e8c785c725ed0aea68a387eb537844a44adf54ee428abf39da151"
    )
    assert (
        evidence.fulfillment_identity
        == "sha256:8de1d5c8f3fbf4c60b401deac9c9aba506cfbf34c04fbd583fce33f173e9437b"
    )


def test_document_retains_timestamp_spelling_omissions_and_explicit_null():
    wire = json.loads(GOLDEN_EVIDENCE)
    wire["result"]["access_ready_at"] = "2030-01-01T00:40:00+00:00"
    wire["result"]["resource_selection"] = "fungible"
    wire["result"]["physical_resource_id"] = None
    wire["result"].pop("access_method")
    wire["result_digest"] = bare_metal_digest(wire["result"])
    document = BareMetalLeaseReadyEvidenceDocument.from_wire(wire)
    assert document.result.access_method == "ssh"
    assert document.result.physical_resource_id is None
    assert document.to_wire() == wire
    assert document.result.to_wire() == wire["result"]
    assert bare_metal_digest(document.value) != document.evidence_digest
    assert document.result.value.result_digest != document.result_digest
    assert document.canonical_json() == canonical_bare_metal_json(wire)


def test_documents_and_their_wire_copies_cannot_change_retained_proof_input():
    document = BareMetalLeaseReadyEvidenceDocument.from_wire(
        json.loads(GOLDEN_EVIDENCE)
    )
    wire = document.to_wire()
    wire["result"]["site_id"] = "changed"
    wire["buyer_principal"]["identifier"] = "changed"
    result_wire = document.result.to_wire()
    result_wire["site_id"] = "changed"
    assert document.canonical_json() == GOLDEN_EVIDENCE
    assert document.result.site_id == "site-a"
    with pytest.raises(FrozenInstanceError):
        document.evidence_digest = DIGEST
    with pytest.raises((AttributeError, TypeError)):
        document.condition_anchor = "changed"
    with pytest.raises(ValidationError):
        document.value.condition_anchor = "changed"


@pytest.mark.parametrize(
    "mutation",
    [
        "outer",
        "nested",
        "unknown-kind",
        "unknown-field",
        "principal",
        "timestamp",
        "selection",
    ],
)
def test_document_refuses_tampering_and_invalid_v1_content(mutation):
    wire = json.loads(GOLDEN_EVIDENCE)
    expected = bare_metal_digest(wire)
    if mutation == "outer":
        wire["condition_anchor"] = "changed"
    elif mutation == "nested":
        wire["result"]["site_id"] = "changed"
        expected = bare_metal_digest(wire)
    elif mutation == "unknown-kind":
        wire["kind"] = "bare_metal.lease-ready-evidence.v2"
        expected = bare_metal_digest(wire)
    elif mutation == "unknown-field":
        wire["result"]["private_key"] = "secret"
        wire["result_digest"] = bare_metal_digest(wire["result"])
        expected = bare_metal_digest(wire)
    elif mutation == "principal":
        wire["buyer_principal"]["scheme"] = " ed25519"
        expected = bare_metal_digest(wire)
    elif mutation == "timestamp":
        wire["result"]["expires_at"] = "2030-01-01T00:50:00"
        wire["result_digest"] = bare_metal_digest(wire["result"])
        expected = bare_metal_digest(wire)
    elif mutation == "selection":
        wire["result"]["resource_selection"] = "fungible"
        wire["result_digest"] = bare_metal_digest(wire["result"])
        expected = bare_metal_digest(wire)
    with pytest.raises(ValueError):
        BareMetalLeaseReadyEvidenceDocument(
            canonical_bare_metal_json(wire).encode(), expected
        )


def test_new_view_defaults_do_not_enter_v1_production_or_its_identities():
    class EvolvedResult(BareMetalLeaseReadyResult):
        diagnostic: str = "ready"

    class EvolvedBinding(BareMetalAcceptedAlkahestBinding):
        diagnostic: str = "accepted"

    result = EvolvedResult.model_validate(lease_ready_result().model_dump())
    binding = EvolvedBinding.model_validate(alkahest_binding().model_dump())
    assert "diagnostic" in result.model_dump()
    evidence = build_bare_metal_lease_ready_evidence(
        binding=binding, condition_anchor="condition-a", result=result
    )
    assert evidence.canonical_json() == GOLDEN_EVIDENCE
    assert binding.binding_digest == alkahest_binding().binding_digest
    assert result.result_digest == lease_ready_result().result_digest
    assert evidence.to_wire() == json.loads(GOLDEN_EVIDENCE)


@pytest.mark.parametrize("offset", [0, 30, 3600, -18000])
def test_v1_snapshot_keeps_the_existing_datetime_wire_codec(offset):
    result = lease_ready_result().model_copy(
        update={
            "access_ready_at": (
                NOW + timedelta(minutes=40, microseconds=123400)
            ).astimezone(timezone(timedelta(seconds=offset))),
        }
    )
    evidence = build_bare_metal_lease_ready_evidence(
        binding=alkahest_binding(), condition_anchor="condition-a", result=result
    )
    assert evidence.result.to_wire() == result.model_dump(
        mode="json", exclude_none=True
    )
    if offset == 0:
        assert (
            BareMetalLeaseReadyEvidence.model_validate(evidence.value.model_dump())
            == evidence.value
        )


@pytest.mark.parametrize(
    "access_ready", [1, 1.0, "true", [True], {"ready": True}, False]
)
def test_retained_wire_refuses_non_literal_true_even_with_matching_digests(
    access_ready,
):
    wire = json.loads(GOLDEN_EVIDENCE)
    wire["result"]["access_ready"] = access_ready
    wire["result_digest"] = bare_metal_digest(wire["result"])
    with pytest.raises(ValueError, match="access_ready must be JSON true"):
        BareMetalLeaseReadyEvidenceDocument.from_wire(wire)
