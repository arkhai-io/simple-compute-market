from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from arkhai_bare_metal import (
    BareMetalAcceptedAlkahestBinding,
    BareMetalLeaseReadyEvidence,
    BareMetalLeaseReadyResult,
    CanonicalPrincipal,
    bare_metal_digest,
    build_bare_metal_lease_ready_evidence,
    derive_bare_metal_fulfillment_identity,
)

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
    payload = evidence.model_dump()
    payload["result_digest"] = "sha256:" + "f" * 64
    with pytest.raises(ValidationError, match="does not match"):
        BareMetalLeaseReadyEvidence.model_validate(payload)
    payload = evidence.model_dump()
    payload["action_url"] = "https://provider.invalid/action"
    with pytest.raises(ValidationError):
        BareMetalLeaseReadyEvidence.model_validate(payload)


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
        == evidence
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
