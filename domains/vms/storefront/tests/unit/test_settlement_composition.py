from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_hosted_settlement import StripeResolverConfig
from market_identity import Ed25519Signer
from market_settlement_runtime import PreparedSettlement, derive_obligation_ref

from market_storefront.models.hosted_settlement_models import SettlementPublicResponse
from market_storefront.settlement_composition import (
    VmFulfillmentInput,
    VmProjectionContext,
    _hosted_evidence_input,
    build_storefront_settlement_registry,
    fulfill_vm_settlement,
    hosted_settlement_projection,
    persist_vm_settlement_outcome,
    prepare_vm_settlement,
    reserve_vm_settlement_start,
    serialize_settlement_job,
)
from market_storefront.utils.sqlite_client import SQLiteClient

_BUYER_SIGNER = Ed25519Signer(b"\x31" * 32)
_SELLER_SIGNER = Ed25519Signer(b"\x32" * 32)
_BUYER = _BUYER_SIGNER.identity
_SELLER = _SELLER_SIGNER.identity


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
        fulfillment_input=VmFulfillmentInput(
            provision=SimpleNamespace(
                ssh_public_key="ssh-ed25519 AAAA",
                duration_seconds=3600,
                start_utc=None,
            ),
            listing_id="listing-1",
            order={"listing_id": "listing-1"},
            negotiation_id="neg-1",
            site_id="site-1",
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
    return SQLiteClient(db_path=str(tmp_path / "vm-settlement.db"))


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


@pytest.mark.asyncio
async def test_hosted_projection_exposes_portable_fulfillment_binding():
    record = SimpleNamespace(
        mechanism_ref="settlement-1",
        obligation_ref="obligation-1",
        payer_principal=_BUYER,
        claimant_principal=_SELLER,
        mechanism_status="ready",
        reclaim_state="pending",
        collection_state="pending",
        materialization_state="succeeded",
        condition_state="pending",
        fulfillment_ref="0xfulfillment",
        condition_anchor="0xanchor",
        buyer_action=None,
    )
    projection = await hosted_settlement_projection(
        composition=SimpleNamespace(mechanism_clients={}),
        record=record,
    )

    response = SettlementPublicResponse.model_validate(projection)
    assert response.condition_anchor == "0xanchor"
    assert response.fulfillment_ref == "0xfulfillment"


@pytest.mark.asyncio
async def test_prepare_pins_the_exact_verified_obligation(db, monkeypatch):
    proposal = {
        "chain_name": "anvil",
        "escrow_address": "0x" + "11" * 20,
        "fields": {"token": "0x" + "22" * 20},
        "expiration_unix": 1_900_000_000,
    }
    db.load_negotiation_thread_row = AsyncMock(
        return_value={
            "negotiation_id": "neg-1",
            "terminal_state": "success",
            "agreed_price": 42,
            "agreed_duration_seconds": 3600,
            "our_listing_id": "listing-1",
            "buyer_principal": _BUYER.model_dump(mode="json"),
            "buyer_escrow_proposal": proposal,
        }
    )
    db.load_listing = AsyncMock(
        return_value={
            "listing_id": "listing-1",
            "offer_resource": {"gpu_model": "H200", "gpu_count": 1},
            "max_duration_seconds": 3600,
        }
    )
    obligations = [_obligation(0), _obligation(1)]
    verify = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "market_storefront.utils.escrow_verification.verify_escrow_for_settlement",
        verify,
    )
    monkeypatch.setattr(
        "market_storefront.domain_runtime.get_market_domain_contract",
        lambda: SimpleNamespace(
            settlement=SimpleNamespace(
                build_plan=lambda **_kwargs: {
                    "settlement_plan": {"obligations": obligations}
                }
            )
        ),
    )
    monkeypatch.setattr(
        "domains.vms.listings.reconciler.site_id_for_listing",
        lambda *_args: "site-1",
    )
    monkeypatch.setattr(
        "market_storefront.utils.config.CHAINS",
        {"anvil": SimpleNamespace(alkahest_address_config_path="/addresses.json")},
    )

    prepared = await prepare_vm_settlement(
        escrow_uid="0xverified",
        negotiation_id="neg-1",
        local_principal=_SELLER,
        mechanism_client=object(),
        chain_name="anvil",
        request={"ssh_public_key": "ssh-ed25519 AAAA"},
        sqlite_client=db,
    )

    assert prepared.selected_obligation_index == 1
    assert prepared.obligations == tuple(obligations)
    assert prepared.local_principal == _SELLER
    assert prepared.mechanism_ref == "0xverified"
    context = prepared.projection_context
    assert context.obligation_ref == derive_obligation_ref("neg-1", 1, obligations[1])
    assert context.obligation_index == 1
    verify.assert_awaited_once()


@pytest.mark.asyncio
async def test_prepare_hosted_requires_funded_exact_listed_selection(db, monkeypatch):
    from market_core.schemas import (
        RateValue,
        SettlementOption,
        derive_settlement_option_id,
    )

    rates = [RateValue(field="amount", value=42)]
    params = {
        "account_ref": "acct-seller",
        "claimant_principal": _SELLER.model_dump(mode="json"),
        "condition": {
            "kind": "builtin",
            "arbiter": "trusted_oracle",
            "demand": {"oracle": "0x" + "11" * 20},
        },
    }
    option = SettlementOption(
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
    selection = {
        "mechanism": "fiat.stripe.v1",
        "option_id": option.option_id,
        "expiration_unix": 1_900_000_000,
    }
    db.load_negotiation_thread_row = AsyncMock(
        return_value={
            "negotiation_id": "neg-hosted",
            "terminal_state": "success",
            "agreed_price": 42,
            "agreed_duration_seconds": 3600,
            "our_listing_id": "listing-hosted",
            "buyer_principal": _BUYER.model_dump(mode="json"),
            "buyer_escrow_proposal": {"settlement_selection": selection},
        }
    )
    db.load_listing = AsyncMock(
        return_value={
            "listing_id": "listing-hosted",
            "offer_resource": {"gpu_model": "H200", "gpu_count": 1},
            "settlement_options": [option.model_dump(mode="json")],
            "max_duration_seconds": 3600,
        }
    )
    mechanism = SimpleNamespace(
        get_status=AsyncMock(
            return_value=SimpleNamespace(
                status="ready",
                receipt={"financial_state": "funded"},
            )
        )
    )
    monkeypatch.setattr(
        "domains.vms.listings.reconciler.site_id_for_listing",
        lambda *_args: "site-1",
    )
    monkeypatch.setattr("market_storefront.utils.config.CHAINS", {})

    prepared = await prepare_vm_settlement(
        escrow_uid="settlement-1",
        negotiation_id="neg-hosted",
        local_principal=_SELLER,
        mechanism_client=mechanism,
        chain_name="",
        request={"ssh_public_key": "ssh-ed25519 AAAA"},
        sqlite_client=db,
    )

    assert prepared.mechanism_ref == "settlement-1"
    assert prepared.obligations[0]["payer_principal"] == _BUYER.model_dump(mode="json")
    assert prepared.obligations[0]["claimant_principal"] == _SELLER.model_dump(
        mode="json"
    )
    assert prepared.obligations[0]["mechanism"] == "fiat.stripe.v1"
    assert prepared.obligations[0]["amount"] == "42"
    assert prepared.mechanism_receipt["financial_state"] == "funded"
    mechanism.get_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_prepare_rejects_missing_accepted_proposal_without_fallback(
    db, monkeypatch
):
    db.load_negotiation_thread_row = AsyncMock(
        return_value={
            "negotiation_id": "neg-1",
            "terminal_state": "success",
            "agreed_price": 42,
            "agreed_duration_seconds": 3600,
            "our_listing_id": "listing-1",
            "buyer_principal": _BUYER.model_dump(mode="json"),
            "buyer_escrow_proposal": None,
        }
    )
    db.load_listing = AsyncMock(
        return_value={
            "listing_id": "listing-1",
            "offer_resource": {},
            "max_duration_seconds": 3600,
        }
    )
    monkeypatch.setattr(
        "market_storefront.utils.config.CHAINS",
        {"anvil": SimpleNamespace(alkahest_address_config_path=None)},
    )

    with pytest.raises(ValueError, match="no persisted accepted escrow proposal"):
        await prepare_vm_settlement(
            escrow_uid="0xverified",
            negotiation_id="neg-1",
            local_principal=_SELLER,
            mechanism_client=object(),
            chain_name="anvil",
            request={"ssh_public_key": "ssh-ed25519 AAAA"},
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
    db, monkeypatch
):
    result = {
        "status": "fulfilled",
        "message": "Compute obligation fulfilled",
        "fulfillment_uid": "0xfulfillment",
        "connection_details": "ssh tenant@host",
        "tenant_credentials": {"password": "secret", "key_type": "ed25519"},
    }
    fulfill = AsyncMock(return_value=result)
    monkeypatch.setattr(
        "market_storefront.domain_runtime.get_market_domain_contract",
        lambda: SimpleNamespace(fulfillment=SimpleNamespace(fulfill=fulfill)),
    )
    prepared = _prepared(db)

    outcome = await fulfill_vm_settlement(
        prepared,
        mechanism_client=object(),
    )

    assert outcome.status == "fulfilled"
    assert outcome.fulfillment_ref == "0xfulfillment"
    assert "connection_details" not in outcome.public_result
    assert "tenant_credentials" not in outcome.public_result
    assert outcome.private_result == result
    assert fulfill.await_args.kwargs["site_id"] == "site-1"


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
