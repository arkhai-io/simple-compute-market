from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from pydantic import ValidationError

from arkhai_bare_metal import (
    BareMetalAcceptedHostedBinding,
    BareMetalHostedOptionFacts,
    BareMetalLeaseReadyEvidence,
    BareMetalLeaseReadyResult,
    CanonicalPrincipal,
    bare_metal_digest,
    bind_bare_metal_hosted_option,
    build_bare_metal_lease_ready_evidence,
    derive_bare_metal_fulfillment_identity,
)

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
BUYER = CanonicalPrincipal(scheme="ed25519", identifier="buyer")
SELLER = CanonicalPrincipal(scheme="ed25519", identifier="seller")
DIGEST = "sha256:" + "1" * 64


def accepted_binding() -> BareMetalAcceptedHostedBinding:
    facts = BareMetalHostedOptionFacts(
        derivation_key="listing-generation-1",
        projection_digest=DIGEST,
        site_id="site-a",
        executor_kind="bare_metal",
        resource_selection="specific",
        physical_resource_id="resource-a",
        physical_host_id="host-a",
        pool_id="pool-a",
        offer_expires_at=NOW + timedelta(hours=2),
        funding_deadline=NOW + timedelta(minutes=30),
        fulfillment_deadline=NOW + timedelta(hours=1),
    )
    params = {
        "account_ref": "acct-public",
        "authority_id": "authority-a",
        "claimant_principal": SELLER.model_dump(mode="json"),
        "condition": {"kind": "portable-remote.v1"},
        "contract_fingerprint": "sha256:" + "2" * 64,
        "country": "US",
        "environment": "test",
        "funding_profile": "card.v1",
        "funds_flow": "separate_charges_transfers",
        "interaction": "interactive",
    }
    rates = [RateValue(field="amount", value=100)]
    base = SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism="fiat.stripe.v1",
            asset="usd",
            rates=rates,
            params=params,
        ),
        mechanism="fiat.stripe.v1",
        asset="usd",
        rates=rates,
        params=params,
    )
    option = bind_bare_metal_hosted_option(base, facts=facts)
    return BareMetalAcceptedHostedBinding(
        agreement_ref="agreement-a",
        negotiation_id="agreement-a",
        listing_id="listing-a",
        obligation_ref="a" * 64,
        option=option,
        buyer_principal=BUYER,
        seller_principal=SELLER,
        claimant_principal=SELLER,
        demand_digest=DIGEST,
        listing_digest=DIGEST,
        seller_terms_digest=DIGEST,
        accepted_plan_digest=DIGEST,
        access_public_digest=DIGEST,
        authorization_expires_at=NOW + timedelta(minutes=45),
        funding_deadline=NOW + timedelta(minutes=30),
    )


def lease_ready_result() -> BareMetalLeaseReadyResult:
    return BareMetalLeaseReadyResult(
        site_id="site-a",
        resource_selection="specific",
        physical_resource_id="resource-a",
        capacity_reservation_ref="reservation-a",
        settlement_resource_ref="settlement-resource-a",
        fulfillment_ref="fulfillment-a",
        access_grant_ref="access-grant-a",
        access_ready_at=NOW + timedelta(minutes=40),
        expires_at=NOW + timedelta(minutes=50),
    )


def test_lease_ready_evidence_is_deterministic_and_binds_canonical_parties() -> None:
    binding = accepted_binding()
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
            binding=accepted_binding(),
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
        binding=accepted_binding(),
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
