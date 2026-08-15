from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id

from arkhai_bare_metal import (
    BareMetalAcceptedHostedBinding,
    BareMetalHostedOptionFacts,
    BareMetalLeaseReadyResult,
    CanonicalPrincipal,
    bind_bare_metal_hosted_option,
    build_bare_metal_lease_ready_evidence,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient


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
    return BareMetalAcceptedHostedBinding(
        agreement_ref="agreement-a",
        negotiation_id="agreement-a",
        listing_id="listing-a",
        obligation_ref="a" * 64,
        option=bind_bare_metal_hosted_option(base, facts=facts),
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


@pytest.mark.asyncio
async def test_accepted_binding_exact_retry_survives_restart_and_changed_replay_conflicts(
    tmp_path,
) -> None:
    path = tmp_path / "storefront.db"
    binding = accepted_binding()
    first = SQLiteClient(str(path))

    created = await first.save_bare_metal_hosted_binding(binding)
    repeated = await first.save_bare_metal_hosted_binding(binding)
    restarted = SQLiteClient(str(path))
    loaded = await restarted.load_bare_metal_hosted_lifecycle(
        obligation_ref=binding.obligation_ref
    )

    assert repeated == created
    assert loaded == created
    assert loaded is not None
    assert loaded.capacity_reservation_id is None
    changed = binding.model_copy(update={"listing_id": "listing-b"})
    with pytest.raises(RuntimeError, match="changed on replay"):
        await restarted.save_bare_metal_hosted_binding(changed)


@pytest.mark.asyncio
async def test_billable_hold_never_impersonates_capacity_reservation(
    tmp_path,
) -> None:
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    binding = accepted_binding().model_copy(
        update={
            "billable_hold_ref": "billable-hold-a",
            "billable_hold_expires_at": NOW + timedelta(minutes=40),
        }
    )

    created = await client.save_bare_metal_hosted_binding(binding)

    assert created.accepted_binding.billable_hold_ref == "billable-hold-a"
    assert created.capacity_reservation_id is None


@pytest.mark.asyncio
async def test_monotonic_physical_refs_are_idempotent_and_changed_reuse_fails(
    tmp_path,
) -> None:
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    binding = accepted_binding()
    await client.save_bare_metal_hosted_binding(binding)

    reserved = await client.advance_bare_metal_hosted_lifecycle(
        obligation_ref=binding.obligation_ref,
        physical_state="capacity_reserved",
        capacity_reservation_id="reservation-a",
    )
    repeated = await client.advance_bare_metal_hosted_lifecycle(
        obligation_ref=binding.obligation_ref,
        physical_state="capacity_reserved",
        capacity_reservation_id="reservation-a",
    )
    assert repeated == reserved

    with pytest.raises(RuntimeError, match="capacity_reservation_id changed"):
        await client.advance_bare_metal_hosted_lifecycle(
            obligation_ref=binding.obligation_ref,
            capacity_reservation_id="reservation-b",
        )
    with pytest.raises(RuntimeError, match="physical state regressed"):
        await client.advance_bare_metal_hosted_lifecycle(
            obligation_ref=binding.obligation_ref,
            physical_state="funded",
        )


@pytest.mark.asyncio
async def test_public_result_and_portable_evidence_persist_atomically_and_exactly(
    tmp_path,
) -> None:
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    binding = accepted_binding()
    await client.save_bare_metal_hosted_binding(binding)
    result = lease_ready_result()
    evidence = build_bare_metal_lease_ready_evidence(
        binding=binding,
        condition_anchor="condition-a",
        result=result,
    )

    ready = await client.advance_bare_metal_hosted_lifecycle(
        obligation_ref=binding.obligation_ref,
        physical_state="access_ready",
        capacity_reservation_id=result.capacity_reservation_ref,
        settlement_resource_id=result.settlement_resource_ref,
        fulfillment_id=result.fulfillment_ref,
        public_result=result,
    )
    published = await client.advance_bare_metal_hosted_lifecycle(
        obligation_ref=binding.obligation_ref,
        physical_state="evidence_published",
        public_result=result,
        portable_evidence=evidence,
        portable_evidence_ref="portable-evidence-a",
    )

    assert ready.public_result_digest == result.result_digest
    assert published.portable_evidence_digest == evidence.evidence_digest
    assert published.portable_evidence_ref == "portable-evidence-a"
    with pytest.raises(RuntimeError, match="evidence changed on replay"):
        await client.advance_bare_metal_hosted_lifecycle(
            obligation_ref=binding.obligation_ref,
            portable_evidence=evidence,
            portable_evidence_ref="portable-evidence-b",
        )


@pytest.mark.asyncio
async def test_collection_unknown_freezes_reclaim_and_collected_loss_is_manual(
    tmp_path,
) -> None:
    client = SQLiteClient(str(tmp_path / "storefront.db"))
    binding = accepted_binding()
    await client.save_bare_metal_hosted_binding(binding)

    unknown = await client.advance_bare_metal_hosted_lifecycle(
        obligation_ref=binding.obligation_ref,
        financial_state="collection_unknown",
    )
    assert unknown.financial_state == "collection_unknown"
    with pytest.raises(RuntimeError, match="financial state conflicts"):
        await client.advance_bare_metal_hosted_lifecycle(
            obligation_ref=binding.obligation_ref,
            financial_state="reclaimed",
        )

    second = binding.model_copy(
        update={
            "agreement_ref": "agreement-b",
            "negotiation_id": "agreement-b",
            "obligation_ref": "b" * 64,
        }
    )
    await client.save_bare_metal_hosted_binding(second)
    await client.advance_bare_metal_hosted_lifecycle(
        obligation_ref=second.obligation_ref,
        financial_state="collected",
    )
    incident = await client.advance_bare_metal_hosted_lifecycle(
        obligation_ref=second.obligation_ref,
        recovery_state="loss_manual",
    )
    assert incident.financial_state == "collected"
    assert incident.recovery_state == "loss_manual"
