from __future__ import annotations

from dataclasses import replace
from datetime import datetime
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from arkhai_vms import make_vm_provision_terms
from market_hosted_settlement import StripeResolverConfig
from market_identity import Ed25519Signer
from market_settlement_runtime import PreparedSettlement, derive_obligation_ref
from core_storefront.domain_lifecycle import StorefrontSettlementFulfillmentInput
from core_storefront.domain_registry import (
    StorefrontListingBinding,
    StorefrontThreadBinding,
    build_storefront_derivation_key,
    StorefrontDomainBindingError,
)

from market_storefront.models.hosted_settlement_models import SettlementPublicResponse
from market_storefront.settlement_composition import (
    VmProjectionContext,
    _hosted_evidence_input,
    _terminal_requires_lease_truncation,
    build_storefront_settlement_registry,
    build_vm_settlement_composition,
    fulfill_vm_settlement,
    hosted_settlement_projection,
    persist_vm_settlement_outcome,
    prepare_vm_settlement,
    reserve_vm_settlement_start,
    serialize_settlement_job,
)
from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sqlite_client import SQLiteClient

_BUYER_SIGNER = Ed25519Signer(b"\x31" * 32)
_SELLER_SIGNER = Ed25519Signer(b"\x32" * 32)
_BUYER = _BUYER_SIGNER.identity
_SELLER = _SELLER_SIGNER.identity
_ACCEPTED_PROVISION = make_vm_provision_terms(
    duration_seconds=3600,
    ssh_public_key="ssh-ed25519 accepted",
).model_dump(mode="json")


def _obligation(index: int = 0) -> dict:
    return {
        "mechanism": "alkahest.v1",
        "payer": "buyer",
        "claimant": "seller",
        "payer_principal": _BUYER.model_dump(mode="json"),
        "claimant_principal": _SELLER.model_dump(mode="json"),
        "expiration_unix": 1_900_000_000 + index,
        "params": {
            "chain_name": "anvil",
            "escrow_contract": "0x" + f"{index + 1:02x}" * 20,
            "obligation_data": {"amount": index + 1},
        },
    }


async def _persist_accepted_negotiation(
    db: SQLiteClient,
    *,
    negotiation_id: str,
    listing_id: str,
    proposal: dict | None,
) -> StorefrontThreadBinding:
    registration = db.domain_registry.resolve_mode("vm")
    timestamp = datetime.now().isoformat()
    pool_id = f"pool-{listing_id}"
    listing_binding = StorefrontListingBinding.from_source_envelope(
        listing_id=listing_id,
        site_id="site-1",
        pool_id=pool_id,
        binding=registration.binding,
        derivation_key=build_storefront_derivation_key(
            site_id="site-1",
            offering_mode=registration.offering_mode,
            binding=registration.binding,
            source_identity={"pool_id": pool_id},
        ),
        source_envelope={
            "kind": "vm.test-listing-source.v1",
            "schema_version": 1,
            "payload": {"pool_id": pool_id},
        },
        last_reconciled_at=timestamp,
    )
    await db.upsert_listing_with_binding(
        binding=listing_binding,
        status="open",
        created_at=timestamp,
        updated_at=timestamp,
        offer_resource={
            "resource_id": f"resource-{listing_id}",
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.9,
            "region": "California, US",
            "virtualization_type": "vm",
        },
        fulfillment_resource=None,
        max_duration_seconds=3600,
        storefront_url="http://storefront.test",
        seller_principal=_SELLER,
    )
    thread_binding = StorefrontThreadBinding(
        negotiation_id=negotiation_id,
        listing_id=listing_id,
        site_id=listing_binding.site_id,
        binding=listing_binding.binding,
    )
    await db.create_negotiation_thread(
        negotiation_id=negotiation_id,
        our_listing_id=listing_id,
        their_listing_id=f"buyer-{listing_id}",
        our_agent_id="seller-agent",
        their_agent_id="buyer-agent",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        owner_id="seller-agent",
        our_initial_price=42,
        requested_duration_seconds=3600,
        buyer_escrow_proposal=proposal,
        provision_terms=_ACCEPTED_PROVISION,
        binding=thread_binding,
    )
    await db.commit_agreed_terms(
        negotiation_id=negotiation_id,
        agreed_price=42,
        agreed_duration_seconds=3600,
    )
    await db.update_negotiation_thread_terminal(
        negotiation_id=negotiation_id,
        terminal_state="success",
    )
    return thread_binding


def _prepared(db: SQLiteClient, *, escrow_uid: str = "0xescrow") -> PreparedSettlement:
    obligation = _obligation()
    obligation_ref = derive_obligation_ref("neg-1", 0, obligation)
    return PreparedSettlement(
        agreement_ref="neg-1",
        obligations=(obligation,),
        selected_obligation_index=0,
        local_principal=_SELLER,
        mechanism_ref=escrow_uid,
        mechanism_receipt={"verified": True},
        fulfillment_input=StorefrontSettlementFulfillmentInput(
            buyer_principal=_BUYER,
            thread_binding=StorefrontThreadBinding(
                negotiation_id="neg-1",
                listing_id="listing-1",
                site_id="site-1",
                binding=db.domain_registry.resolve_mode("vm").binding,
            ),
            domain_input={
                "provision": make_vm_provision_terms(
                    duration_seconds=3600,
                    ssh_public_key="ssh-ed25519 AAAA",
                ),
                "listing_id": "listing-1",
                "order": {"listing_id": "listing-1"},
            },
        ),
        projection_context=VmProjectionContext(
            sqlite_client=db,
            escrow_uid=escrow_uid,
            negotiation_id="neg-1",
            chain_name="anvil",
            escrow_address="0x" + "11" * 20,
            obligation_ref=obligation_ref,
            obligation_index=0,
        ),
    )


@pytest.fixture
def db(tmp_path):
    return SQLiteClient(db_path=str(tmp_path / "vm-settlement.db"), registry=build_vm_storefront_registry(build_vm_storefront_domain()))


def test_storefront_installs_both_mechanism_registrations():
    registry = build_storefront_settlement_registry()

    assert [registration.mechanism_id for registration in registry.registrations] == [
        "alkahest.v1",
        "fiat.stripe.v1",
    ]


def test_hosted_evidence_resolver_accepts_typed_configuration():
    evidence_client = object()
    resolver = StripeResolverConfig(
        chain_name="fiat.stripe.v1",
        evidence_mode="portable-remote.v1",
    )
    composition = SimpleNamespace(
        settlement_config=SimpleNamespace(
            mechanism_config=lambda _key: SimpleNamespace(
                resolvers={"vm-portable": resolver}
            )
        ),
        evidence_clients={"fiat.stripe.v1": evidence_client},
    )
    condition = SimpleNamespace(evaluator=SimpleNamespace(resolver_id="vm-portable"))

    assert _hosted_evidence_input(
        composition=composition,
        condition=condition,
    ) == ("vm-portable", "portable-remote.v1", evidence_client)


@pytest.mark.parametrize(
    ("outcome", "collection_state", "expected"),
    [
        ("failed", "pending", True),
        ("manual_required", "succeeded", False),
        ("failed", "succeeded", False),
        ("collected", "pending", False),
    ],
)
def test_terminal_cleanup_never_truncates_a_collected_vm_lease(
    outcome,
    collection_state,
    expected,
):
    record = SimpleNamespace(collection_state=collection_state)

    assert _terminal_requires_lease_truncation(record, outcome) is expected


@pytest.mark.asyncio
async def test_hosted_projection_exposes_portable_fulfillment_binding():
    record = SimpleNamespace(
        mechanism_ref="settlement-1",
        obligation_ref="obligation-1",
        payer_principal=_BUYER,
        claimant_principal=_SELLER,
        obligation={
            "params": {
                "funding_profile": "card.v1",
            }
        },
        mechanism_params={
            "funding_profile": "card.v1",
            "funding_authorization_ref": "authorization-1",
        },
        mechanism_status="ready",
        mechanism_state={"funding_reason": "available"},
        reclaim_state="pending",
        collection_state="pending",
        materialization_state="materialized",
        condition_state="pending",
        condition_anchor="0xanchor",
        fulfillment_ref="0xfulfillment",
        buyer_action=None,
        status_receipt={"funding_reason": "available"},
        materialization_receipt=None,
        collection_receipt=None,
        reclaim_receipt=None,
    )
    projection = await hosted_settlement_projection(
        composition=SimpleNamespace(),
        record=record,
    )

    response = SettlementPublicResponse.model_validate(projection)
    assert response.funding_profile.value == "card.v1"
    assert response.funding_authorization_ref == "authorization-1"
    assert response.receipt == {"funding_reason": "available"}
    # Both halves of the binding a buyer verifies fulfillment against.
    assert response.condition_anchor == "0xanchor"
    assert response.fulfillment_ref == "0xfulfillment"
    record.mechanism_status = "manual_required"
    record.collection_state = "succeeded"
    record.status_receipt = {"funding_reason": "post_collection_loss"}
    late_loss = SettlementPublicResponse.model_validate(
        await hosted_settlement_projection(
            composition=SimpleNamespace(),
            record=record,
        )
    )
    assert late_loss.status == "manual_required"
    assert late_loss.funding_reason == "post_collection_loss"


@pytest.mark.asyncio
async def test_prepare_pins_the_exact_verified_obligation(tmp_path, monkeypatch):
    proposal = {
        "chain_name": "anvil",
        "escrow_address": "0x" + "11" * 20,
        "fields": {"token": "0x" + "22" * 20},
        "expiration_unix": 1_900_000_000,
    }
    obligations = [_obligation(0), _obligation(1)]
    build_contexts = []

    def build_plan(*, context):
        build_contexts.append(context)
        return {"settlement_plan": {"obligations": obligations}}

    domain = build_vm_storefront_domain()
    assert domain.settlement is not None
    domain = replace(
        domain,
        settlement=replace(domain.settlement, build_plan=build_plan),
    )
    db = SQLiteClient(
        db_path=str(tmp_path / "injected-plan.db"),
        registry=build_vm_storefront_registry(domain),
    )
    thread_binding = await _persist_accepted_negotiation(
        db,
        negotiation_id="neg-1",
        listing_id="listing-1",
        proposal=proposal,
    )
    verify = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "market_storefront.utils.escrow_verification.verify_escrow_for_settlement",
        verify,
    )
    monkeypatch.setattr(
        "market_storefront.utils.config.CHAINS",
        {"anvil": SimpleNamespace(alkahest_address_config_path="/addresses.json")},
    )

    prepared = await prepare_vm_settlement(
        domain=domain,
        escrow_uid="0xverified",
        negotiation_id="neg-1",
        local_principal=_SELLER,
        mechanism_client=object(),
        chain_name="anvil",
        request={"ssh_public_key": "ssh-ed25519 substituted"},
        sqlite_client=db,
    )

    assert prepared.selected_obligation_index == 1
    assert prepared.obligations == tuple(obligations)
    assert prepared.local_principal == _SELLER
    assert prepared.mechanism_ref == "0xverified"
    projection_context = prepared.projection_context
    assert projection_context.obligation_ref == derive_obligation_ref(
        "neg-1", 1, obligations[1]
    )
    assert projection_context.obligation_index == 1
    assert prepared.fulfillment_input.thread_binding == thread_binding
    assert len(build_contexts) == 1
    build_context = build_contexts[0]
    assert build_context.binding == thread_binding.binding
    assert build_context.negotiation_id == thread_binding.negotiation_id
    assert build_context.listing_id == thread_binding.listing_id
    assert build_context.site_id == thread_binding.site_id
    assert build_context.buyer_principal == _BUYER
    assert build_context.seller_principal == _SELLER
    verify.assert_awaited_once()
    assert (
        prepared.fulfillment_input.domain_input["provision"].ssh_public_key
        == "ssh-ed25519 accepted"
    )


@pytest.mark.asyncio
async def test_prepare_hosted_rejects_the_removed_legacy_start_route(db):
    await _persist_accepted_negotiation(
        db,
        negotiation_id="neg-hosted",
        listing_id="listing-hosted",
        proposal={
            "settlement_selection": {
                "mechanism": "fiat.stripe.v1",
                "option_id": "accepted-option",
                "expiration_unix": 1_900_000_000,
            }
        },
    )

    with pytest.raises(
        ValueError,
        match="accepted settlement endpoint",
    ):
        await prepare_vm_settlement(
            domain=db.domain_registry.resolve_mode("vm").contract,
            escrow_uid="settlement-1",
            negotiation_id="neg-hosted",
            local_principal=_SELLER,
            mechanism_client=object(),
            chain_name="",
            request={"caller_override": "rejected"},
            sqlite_client=db,
        )


@pytest.mark.asyncio
async def test_prepare_rejects_missing_accepted_proposal_without_fallback(db):
    await _persist_accepted_negotiation(
        db,
        negotiation_id="neg-1",
        listing_id="listing-1",
        proposal=None,
    )

    with pytest.raises(ValueError, match="no persisted accepted escrow proposal"):
        await prepare_vm_settlement(
            domain=db.domain_registry.resolve_mode("vm").contract,
            escrow_uid="0xverified",
            negotiation_id="neg-1",
            local_principal=_SELLER,
            mechanism_client=object(),
            chain_name="anvil",
            request={"ssh_public_key": "ssh-ed25519 AAAA"},
            sqlite_client=db,
        )


@pytest.mark.asyncio
async def test_prepare_rejects_contract_outside_the_accepted_thread_binding(
    db,
):
    proposal = {
        "chain_name": "anvil",
        "escrow_address": "0x" + "11" * 20,
        "fields": {"token": "0x" + "22" * 20},
        "expiration_unix": 1_900_000_000,
    }
    await _persist_accepted_negotiation(
        db,
        negotiation_id="neg-1",
        listing_id="listing-1",
        proposal=proposal,
    )
    unregistered_domain = build_vm_storefront_domain()

    with pytest.raises(
        RuntimeError,
        match="contract disagrees with accepted binding",
    ):
        await prepare_vm_settlement(
            domain=unregistered_domain,
            escrow_uid="0xverified",
            negotiation_id="neg-1",
            local_principal=_SELLER,
            mechanism_client=object(),
            chain_name="anvil",
            sqlite_client=db,
        )


@pytest.mark.asyncio
async def test_reserve_persists_immutable_obligation_mapping_before_fulfillment(db):
    prepared = _prepared(db)
    assert await reserve_vm_settlement_start(prepared, "0xescrow", "neg-1") is None

    row = await db.load_escrow(escrow_uid="0xescrow")
    assert row["status"] == "provisioning"
    assert row["obligation_ref"] == prepared.projection_context.obligation_ref
    assert row["obligation_index"] == 0

    existing = await reserve_vm_settlement_start(prepared, "0xescrow", "neg-1")
    assert existing["obligation_ref"] == prepared.projection_context.obligation_ref

    conflicting = _prepared(db, escrow_uid="0xescrow")
    conflicting_context = VmProjectionContext(
        **{
            **conflicting.projection_context.__dict__,
            "obligation_ref": "different-obligation",
        }
    )
    conflicting = PreparedSettlement(
        **{
            **conflicting.__dict__,
            "projection_context": conflicting_context,
        }
    )
    with pytest.raises(ValueError, match="different obligation"):
        await reserve_vm_settlement_start(conflicting, "0xescrow", "neg-1")


@pytest.mark.asyncio
async def test_fulfillment_keeps_private_delivery_out_of_public_runtime_result(
    tmp_path,
):
    private_result = {
        "status": "fulfilled",
        "message": "Compute obligation fulfilled",
        "fulfillment_uid": "0xfulfillment",
        "connection_details": "ssh tenant@host",
        "tenant_credentials": {"password": "secret", "key_type": "ed25519"},
    }
    result = {
        "negotiation_id": "neg-1",
        "escrow_uid": "0xescrow",
        "site_id": "site-1",
        "state": "fulfilled",
        "fulfillment_id": "0xfulfillment",
        "domain_result": private_result,
    }
    fulfill = AsyncMock(return_value=result)
    domain = build_vm_storefront_domain()
    domain = replace(
        domain,
        fulfillment=replace(domain.fulfillment, fulfill=fulfill),
    )
    db = SQLiteClient(db_path=str(tmp_path / "injected-fulfillment.db"), registry=build_vm_storefront_registry(domain))
    prepared = _prepared(db)

    outcome = await fulfill_vm_settlement(
        domain,
        prepared,
        mechanism_client=object(),
        sqlite_client=db,
    )

    assert outcome.status == "fulfilled"
    assert outcome.fulfillment_ref == "0xfulfillment"
    assert "connection_details" not in outcome.public_result
    assert "tenant_credentials" not in outcome.public_result
    assert outcome.private_result == private_result
    assert fulfill.await_args.kwargs["context"].site_id == "site-1"


def test_composition_rejects_repository_domain_mismatch_before_registration(
    db,
    monkeypatch,
) -> None:
    registry_builder = Mock()
    monkeypatch.setattr(
        "market_storefront.settlement_composition.build_storefront_settlement_registry",
        registry_builder,
    )
    other_domain = build_vm_storefront_domain()

    with pytest.raises(
        StorefrontDomainBindingError,
        match="exact startup-owned object",
    ):
        build_vm_settlement_composition(
            domain=other_domain,
            sqlite_client=db,
            alkahest_clients={},
            marketplace_signer=_SELLER_SIGNER,
        )

    registry_builder.assert_not_called()


@pytest.mark.asyncio
async def test_persist_outcome_preserves_legacy_ready_projection(db):
    prepared = _prepared(db)
    await reserve_vm_settlement_start(prepared, "0xescrow", "neg-1")
    from market_settlement_runtime import FulfillmentOutcome

    await persist_vm_settlement_outcome(
        prepared,
        FulfillmentOutcome(
            status="fulfilled",
            fulfillment_ref="0xfulfillment",
            private_result={
                "connection_details": "ssh tenant@host",
                "tenant_credentials": {"password": "secret"},
            },
        ),
    )

    row = await db.load_escrow(escrow_uid="0xescrow")
    assert row["status"] == "ready"
    assert row["fulfillment_uid"] == "0xfulfillment"
    assert row["connection_details"] == "ssh tenant@host"
    assert json.loads(row["tenant_credentials"]) == {"password": "secret"}


def test_serialize_keeps_physical_and_onchain_fulfillment_ids_distinct():
    serialized = serialize_settlement_job(
        {
            "escrow_uid": "0xe",
            "negotiation_id": "neg-1",
            "status": "ready",
            "fulfillment_uid": "0xonchain",
            "fulfillment_id": "physical-123",
            "connection_details": "ssh tenant@host",
            "tenant_credentials": json.dumps({"password": "secret"}),
            "created_at": "2026-04-23T00:00:00Z",
            "updated_at": "2026-04-23T00:00:00Z",
        }
    )

    assert serialized["fulfillment_id"] == "physical-123"
    assert serialized["fulfillment_uid"] == "0xonchain"
    assert serialized["tenant_credentials"] == {"password": "secret"}
    assert "obligation_ref" not in serialized
