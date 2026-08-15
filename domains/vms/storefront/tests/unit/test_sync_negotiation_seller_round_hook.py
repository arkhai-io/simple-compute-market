from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from market_core.schemas import EscrowProposal, ProvisionTerms
from core_storefront.negotiation_sync import OfferUnfulfillableError
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_policy.identity import Identity
from market_policy.negotiation_middleware import NegotiationDecision
from market_policy.negotiation_thread import get_thread_store

from market_storefront.domain_runtime import build_vm_storefront_domain, build_vm_storefront_registry
from market_storefront.utils.sync_negotiation import (
    SellerRoundResult,
    _accepted_hosted_artifacts,
    _default_seller_round_hook,
    _normalize_vm_message_terms,
    continue_sync_negotiation,
    start_sync_negotiation,
)

_BUYER_SIGNER = Ed25519Signer(b"\x41" * 32)
_SELLER_SIGNER = Ed25519Signer(b"\x42" * 32)
_BUYER = _BUYER_SIGNER.identity
_SELLER = _SELLER_SIGNER.identity
_PROVISIONING_AUTHORITIES = TrustedIdentitySet(
    identities=(Ed25519Signer(b"\x43" * 32).identity,)
)
_TOKEN = "0x0000000000000000000000000000000000000001"
_ESCROW = "0x" + "11" * 20
_DOMAIN = build_vm_storefront_domain()


@pytest.fixture
def marketplace_dependencies(monkeypatch):
    from market_storefront import container
    from market_storefront.services import capacity_client

    monkeypatch.setattr(
        container,
        "resolved_marketplace_signer",
        _SELLER_SIGNER,
    )
    monkeypatch.setattr(
        capacity_client,
        "get_provisioning_authorities",
        lambda: _PROVISIONING_AUTHORITIES,
    )
    return _SELLER_SIGNER


@pytest.fixture
async def db(tmp_path):
    import market_policy.negotiation_thread as thread_module

    from market_storefront.utils.sqlite_client import SQLiteClient

    client = SQLiteClient(db_path=str(tmp_path / "seller_round_hook.db"), registry=build_vm_storefront_registry(_DOMAIN))
    thread_module._thread_store = None
    get_thread_store(
        sqlite_client=client,
        identity=Identity(agent_url="http://test-seller:8001"),
    )
    await client.upsert_listing(
        listing_id="L-hook",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.9,
            "region": "California, US",
            "resource_id": "resource-hook",
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": _ESCROW,
                "literal_fields": {"token": _TOKEN},
                "rates": [{"field": "amount", "per": "hour", "value": "100"}],
            }
        ],
        fulfillment_resource=None,
        max_duration_seconds=7200,
        storefront_url="http://seller:8001",
        seller_principal=_SELLER,
    )
    return client


def _proposal(amount: int) -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": amount},
        literal_fields={"token": _TOKEN},
        rates=[{"field": "amount", "per": "hour", "value": "100"}],
        expiration_unix=1_800_000_000,
    )


def test_normalize_vm_message_terms_uses_domain_runtime() -> None:
    terms = ProvisionTerms.model_validate(
        {
            "kind": "compute.v1",
            "version": 1,
            "payload": {
                "duration_seconds": "3600",
                "start_utc": "2030-01-01T00:00:00Z",
                "ssh_public_key": "ssh-rsa AAAA",
            },
        }
    )

    normalized = _normalize_vm_message_terms(_DOMAIN, terms)

    assert normalized is not None
    assert normalized.duration_seconds == 3600
    assert normalized.start_utc == "2030-01-01T00:00:00Z"


def test_normalize_vm_message_terms_rejects_foreign_terms() -> None:
    terms = ProvisionTerms(
        kind="fiat.v1",
        version=1,
        payload={"invoice_id": "inv-1"},
    )

    with pytest.raises(ValueError, match=r"compute\.v1"):
        _normalize_vm_message_terms(_DOMAIN, terms)


def test_normalize_vm_message_terms_rejects_unsupported_version() -> None:
    terms = ProvisionTerms(
        kind="compute.v1",
        version=2,
        payload={
            "duration_seconds": 3600,
            "ssh_public_key": "ssh-rsa AAAA",
        },
    )

    with pytest.raises(ValueError, match="version"):
        _normalize_vm_message_terms(_DOMAIN, terms)



def test_default_policy_is_resolved_from_the_injected_contract(
    marketplace_dependencies,
) -> None:
    domain = build_vm_storefront_domain()
    seller_hook = AsyncMock()
    policy = Mock(return_value=seller_hook)
    domain = replace(
        domain,
        storefront=replace(
            domain.storefront,
            run_negotiation_policy=policy,
        ),
    )
    repository = object()

    assert _default_seller_round_hook(domain, repository) is seller_hook
    assert policy.call_args.args


@pytest.mark.asyncio
async def test_foreign_envelope_rejects_before_policy_or_repository_state(db) -> None:
    repository_probe = AsyncMock()
    db.is_listing_paused = repository_probe
    seller_hook = AsyncMock()
    terms = {
        "kind": "bare_metal.v1",
        "version": 1,
        "duration_seconds": 3600,
        "ssh_public_key": "ssh-ed25519 AAAA",
    }

    with pytest.raises(ValueError, match=r"compute\.v1"):
        await start_sync_negotiation(
            domain=db.domain_registry.resolve_mode("vm").contract,
            sqlite_client=db,
            our_listing_id="L-hook",
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
            provision_terms=terms,
            our_base_url="http://seller",
            their_agent_url="http://buyer",
            seller_round_hook=seller_hook,
        )

    repository_probe.assert_not_awaited()
    seller_hook.assert_not_awaited()

@pytest.mark.asyncio
async def test_start_sync_negotiation_uses_injected_seller_round_hook(db):
    seen = {}

    async def hook(**kwargs):
        seen["history"] = kwargs["history"]
        seen["has_policy_inputs"] = "policy_inputs" in kwargs
        seen["has_sqlite_client"] = "sqlite_client" in kwargs
        return SellerRoundResult(
            our_amount=123,
            strategy_label="maximize",
            direction="maximize",
            chain_label="custom",
            decision=NegotiationDecision(
                action="counter",
                proposal=_proposal(123).model_dump(),
            ),
        )

    response = await start_sync_negotiation(
        domain=db.domain_registry.resolve_mode("vm").contract,
        sqlite_client=db,
        our_listing_id="L-hook",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        proposal=_proposal(50),
        provision_terms=ProvisionTerms(
            kind="compute.v1",
            version=1,
            payload={
                "duration_seconds": 3600,
                "ssh_public_key": "ssh-rsa AAAA",
            },
        ),
        our_base_url="http://test-seller:8001",
        their_agent_url="http://buyer:9000",
        seller_round_hook=hook,
    )

    assert response["action"] == "counter"
    assert response["proposal"]["fields"]["amount"] == "123"
    assert seen["history"][0].proposal["fields"]["amount"] == 50
    assert seen["has_policy_inputs"] is False
    assert seen["has_sqlite_client"] is False


@pytest.mark.asyncio
async def test_hosted_selection_is_persisted_and_materialized_as_plan(db):
    from market_core.schemas import (
        RateValue,
        SettlementOption,
        SettlementSelection,
        derive_settlement_option_id,
    )

    rates = [RateValue(field="amount", value=42)]
    params = {
        "account_ref": "acct-seller",
        "authority_id": "hosted-authority-1",
        "environment": "test",
        "country": "US",
        "claimant_principal": _SELLER.model_dump(mode="json"),
        "funds_flow": "separate_charges_transfers",
        "funding_profile": "card.v1",
        "interaction": "interactive",
        "contract_fingerprint": "sha256:" + "11" * 32,
        "condition": {
            "protocol": "arkhai.condition.v1",
            "condition_id": "condition-1",
            "evaluator": {
                "kind": "builtin.v1",
                "version": "trivial.v1",
                "params": {"kind": "trivial"},
            },
            "demand": {"encoding": "application/jcs+json", "value": True},
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
    selection = SettlementSelection(
        mechanism=option.mechanism,
        option_id=option.option_id,
        expiration_unix=1_900_000_000,
    )
    await db.upsert_listing(
        listing_id="L-hosted",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.9,
            "region": "California, US",
            "resource_id": "resource-hosted",
        },
        accepted_escrows=[],
        settlement_options=[option.model_dump(mode="json")],
        fulfillment_resource=None,
        max_duration_seconds=7200,
        storefront_url="http://seller:8001",
        seller_principal=_SELLER,
    )
    await db.upsert_resource(
        resource_id="resource-hosted",
        resource_type="compute.gpu",
        resource_subtype=None,
        unit="vm",
        value=1,
        state="available",
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "kvm1",
        },
    )

    from tests.fake_site import FakeSite, site_capacity

    site = FakeSite()
    site.add_resource(
        "resource-hosted",
        1,
        attributes={
            "gpu_model": "H200",
            "region": "California, US",
            "vm_host": "kvm1",
        },
    )

    async def hook(**_kwargs):
        return SellerRoundResult(
            our_amount=42,
            strategy_label="listed_price",
            direction="minimize",
            chain_label="hosted",
            decision=NegotiationDecision(
                action="accept",
                proposal={"settlement_selection": selection.model_dump()},
            ),
            intermediate={
                "accepted_settlement_selection": selection.model_dump(),
                "accepted_settlement_option": option.model_dump(mode="json"),
            },
        )

    with site_capacity(site):
        response = await start_sync_negotiation(
            domain=db.domain_registry.resolve_mode("vm").contract,
            sqlite_client=db,
            our_listing_id="L-hosted",
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
            proposal={"settlement_selection": selection.model_dump()},
            provision_terms=ProvisionTerms(
                kind="compute.v1",
                version=1,
                payload={
                    "duration_seconds": 3600,
                    "ssh_public_key": "ssh-rsa AAAA",
                },
            ),
            our_base_url="http://test-seller:8001",
            their_agent_url="http://buyer:9000",
            seller_round_hook=hook,
        )

    assert response["action"] == "accept"
    assert response["settlement_selection"] == selection.model_dump()
    assert response["settlement_plan"]["obligations"][0]["mechanism"] == (
        "fiat.stripe.v1"
    )
    obligation = response["settlement_plan"]["obligations"][0]
    assert obligation["payer_principal"] == _BUYER.model_dump(mode="json")
    assert obligation["claimant_principal"] == _SELLER.model_dump(mode="json")
    vm_state = response["settlement_plan"]["service_terms"]["vm.v1"]
    assert vm_state["listing_id"] == "L-hosted"
    assert vm_state["order"]["offer_resource"]["resource_id"] == "resource-hosted"
    assert vm_state["provision"]["payload"]["ssh_public_key"] == "ssh-rsa AAAA"
    thread = await db.load_negotiation_thread_row(
        negotiation_id=response["negotiation_id"]
    )
    assert thread["buyer_escrow_proposal"] == {
        "settlement_selection": selection.model_dump()
    }
    assert thread["settlement_plan"] == response["settlement_plan"]
    assert thread["provision_terms"] == {
        "kind": "compute.v1",
        "version": 1,
        "payload": {
            "duration_seconds": 3600,
            "ssh_public_key": "ssh-rsa AAAA",
        },
    }
    legacy_params = dict(params)
    legacy_params.pop("funding_profile")
    legacy_params["payment_method_types"] = ["card"]
    legacy_option = option.model_copy(update={"params": legacy_params})
    with pytest.raises(
        OfferUnfulfillableError,
        match="hosted_settlement_option_not_exact",
    ):
        _accepted_hosted_artifacts(
            selection=selection.model_dump(mode="json"),
            option=legacy_option.model_dump(mode="json"),
            agreed_amount=42,
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
            listing=vm_state["order"],
            provision_terms=vm_state["provision"],
        )


@pytest.mark.asyncio
async def test_start_sync_negotiation_rejects_mismatched_resource_shape(db):
    """A buyer requesting a shape other than the listing's is refused outright.

    Seller negotiation policy currently prices only the listing's
    advertised shape; this pins the loud-rejection behavior rather than
    silent admission or silent fallback to the listing's shape.
    """
    from market_storefront.utils.sync_negotiation import OfferUnfulfillableError

    async def hook(**_kwargs):
        raise AssertionError("seller policy must not run for a rejected request")

    with pytest.raises(OfferUnfulfillableError) as exc_info:
        await start_sync_negotiation(
            domain=db.domain_registry.resolve_mode("vm").contract,
            sqlite_client=db,
            our_listing_id="L-hook",
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
            proposal=_proposal(50),
            provision_terms=ProvisionTerms(
                kind="compute.v1",
                version=1,
                payload={
                    "duration_seconds": 3600,
                    "ssh_public_key": "ssh-rsa AAAA",
                    # Listing offers gpu_count=1; this asks for 2.
                    "compute_resource": {"gpu_count": 2},
                },
            ),
            our_base_url="http://test-seller:8001",
            their_agent_url="http://buyer:9000",
            seller_round_hook=hook,
        )
    assert "resource_shape_not_negotiable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_start_sync_negotiation_permits_resource_shape_matching_listing(db):
    """A buyer that names a shape equal to the listing's own is unaffected."""
    seen = {}

    async def hook(**kwargs):
        seen["ran"] = True
        return SellerRoundResult(
            our_amount=100,
            strategy_label="maximize",
            direction="maximize",
            chain_label="custom",
            decision=NegotiationDecision(
                action="counter",
                proposal=_proposal(100).model_dump(),
            ),
        )

    response = await start_sync_negotiation(
        domain=db.domain_registry.resolve_mode("vm").contract,
        sqlite_client=db,
        our_listing_id="L-hook",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        proposal=_proposal(50),
        provision_terms=ProvisionTerms(
            kind="compute.v1",
            version=1,
            payload={
                "duration_seconds": 3600,
                "ssh_public_key": "ssh-rsa AAAA",
                "compute_resource": {"gpu_count": 1},
            },
        ),
        our_base_url="http://test-seller:8001",
        their_agent_url="http://buyer:9000",
        seller_round_hook=hook,
    )
    assert seen["ran"] is True
    assert response["action"] == "counter"


@pytest.mark.asyncio
async def test_continue_sync_negotiation_uses_injected_seller_round_hook(db):
    async def opening_hook(**_kwargs):
        return SellerRoundResult(
            our_amount=100,
            strategy_label="maximize",
            direction="maximize",
            chain_label="custom",
            decision=NegotiationDecision(
                action="counter",
                proposal=_proposal(100).model_dump(),
            ),
        )

    opened = await start_sync_negotiation(
        domain=db.domain_registry.resolve_mode("vm").contract,
        sqlite_client=db,
        our_listing_id="L-hook",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        proposal=_proposal(50),
        provision_terms=ProvisionTerms(
            kind="compute.v1",
            version=1,
            payload={
                "duration_seconds": 3600,
                "ssh_public_key": "ssh-rsa AAAA",
            },
        ),
        our_base_url="http://test-seller:8001",
        their_agent_url="http://buyer:9000",
        seller_round_hook=opening_hook,
    )

    seen = {}

    async def continue_hook(**kwargs):
        seen["history"] = kwargs["history"]
        seen["has_policy_inputs"] = "policy_inputs" in kwargs
        seen["has_sqlite_client"] = "sqlite_client" in kwargs
        return SellerRoundResult(
            our_amount=100,
            strategy_label="maximize",
            direction="maximize",
            chain_label="custom",
            decision=NegotiationDecision(
                action="accept",
                proposal=_proposal(100).model_dump(),
                reason="custom",
            ),
        )

    response = await continue_sync_negotiation(
        domain=db.domain_registry.resolve_mode("vm").contract,
        sqlite_client=db,
        neg_id=opened["negotiation_id"],
        buyer_action="counter",
        buyer_proposal=_proposal(100).model_dump(),
        buyer_reason=None,
        buyer_principal=_BUYER,
        actor_principal=_BUYER,
        seller_round_hook=continue_hook,
    )

    assert response["action"] == "accept"
    assert response["accepted_escrow_proposal"]["fields"]["amount"] == "100"
    assert seen["history"][-1].sender == "them"
    assert seen["history"][-1].proposal["fields"]["amount"] == 100
    assert seen["has_policy_inputs"] is False
    assert seen["has_sqlite_client"] is False
