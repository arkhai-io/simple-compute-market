from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from core_storefront.aggregation import fill_first
from core_storefront.domain_registry import (
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from market_capacity_publication import (
    CapacityBinding,
    CapacityRuntime,
    CapacitySite,
)
from market_core.schemas import (
    EscrowProposal,
    ProvisionTerms,
    RateValue,
    SettlementOption,
    derive_settlement_option_id,
)
from market_identity import Ed25519Signer, TrustedIdentitySet
from market_negotiation_runtime import OfferUnfulfillableError
from market_policy.identity import Identity
from market_policy.listing_source import ListingSourceVerdict
from market_policy.negotiation_middleware import NegotiationDecision
from market_policy.negotiation_thread import get_thread_store

from market_storefront.domain_runtime import (
    build_vm_storefront_domain,
    build_vm_storefront_registry,
)
from arkhai_vms_negotiation.storefront_round import SellerRoundResult
from market_storefront.negotiation_runtime import (
    _decode_vm_terms,
    _default_seller_round_hook,
    build_vm_negotiation_runtime,
)

_BUYER_SIGNER = Ed25519Signer(b"\x41" * 32)
_SELLER_SIGNER = Ed25519Signer(b"\x42" * 32)
_BUYER = _BUYER_SIGNER.identity
_SELLER = _SELLER_SIGNER.identity
_PROVISIONING_AUTHORITIES = TrustedIdentitySet(
    identities=(Ed25519Signer(b"\x43" * 32).identity,)
)
_TOKEN = "0x0000000000000000000000000000000000000001"
_RECIPIENT = "0x" + "44" * 20
_ESCROW = "0x" + "11" * 20
_DOMAIN = build_vm_storefront_domain()


async def _noop_reconcile(_context) -> None:
    return None


def _capacity_runtime() -> CapacityRuntime:
    return CapacityRuntime(
        sites=(
            CapacitySite(
                "site-test",
                "http://capacity.test",
                _PROVISIONING_AUTHORITIES,
            ),
        ),
        signer=_SELLER_SIGNER,
        placement=fill_first,
        reconcile=_noop_reconcile,
        site_client_factory=lambda _site, _signer: object(),
    )


def _listing_binding(db, listing_id: str) -> StorefrontListingBinding:
    registration = db.domain_registry.resolve_mode("vm")
    pool_id = f"pool-{listing_id}"
    return StorefrontListingBinding.from_source_envelope(
        listing_id=listing_id,
        site_id="site-test",
        pool_id=pool_id,
        binding=registration.binding,
        derivation_key=build_storefront_derivation_key(
            site_id="site-test",
            offering_mode=registration.offering_mode,
            binding=registration.binding,
            source_identity={"pool_id": pool_id},
        ),
        source_envelope={
            "kind": "vm.test-listing-source.v1",
            "schema_version": 1,
            "payload": {"pool_id": pool_id},
        },
        last_reconciled_at=datetime.now().isoformat(),
        capacity_backing="backed",
    )


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
async def db(tmp_path, monkeypatch):
    address_config = tmp_path / "alkahest-addresses.json"
    address_config.write_text(
        json.dumps(
            {
                "erc20_addresses": {
                    "escrow_obligation_unconditional": _ESCROW,
                },
                "arbiters_addresses": {
                    "recipient_arbiter": "0x" + "33" * 20,
                },
            }
        )
    )
    monkeypatch.setattr(
        "market_storefront.negotiation_runtime._chain_config_paths",
        lambda: {"anvil": str(address_config)},
    )
    import market_policy.negotiation_thread as thread_module

    from market_storefront.utils.sqlite_client import SQLiteClient

    registry = build_vm_storefront_registry(_DOMAIN)
    client = SQLiteClient(
        db_path=str(tmp_path / "seller_round_hook.db"),
        registry=registry,
    )
    thread_module._thread_store = None
    get_thread_store(
        sqlite_client=client,
        identity=Identity(agent_url="http://test-seller:8001"),
    )
    listing_binding = _listing_binding(client, "L-hook")
    await client.upsert_listing_with_binding(
        binding=listing_binding,
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        listing_resource={
            "gpu_model": "H200",
            "gpu_count": 1,
            "sla": 99.9,
            "region": "California, US",
            "resource_id": "resource-hook",
            "offering_mode": "vm",
        },
        settlement_options=[_option().model_dump(mode="json")],
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

    async def resolve_capacity_binding(repository, listing_id):
        binding = await repository.load_listing_binding(listing_id=listing_id)
        assert binding is not None
        return CapacityBinding(
            binding.site_id,
            binding.binding.offering_mode,
            str(binding.pool_id),
        )

    monkeypatch.setattr(
        "market_storefront.negotiation_runtime.capacity_binding_for_listing",
        resolve_capacity_binding,
    )
    assert await client.load_listing_binding(listing_id="L-hook") == listing_binding
    return client


def _option() -> SettlementOption:
    entry = {
        "chain_name": "anvil", "escrow_address": _ESCROW,
        "literal_fields": {"token": _TOKEN, "recipient": _RECIPIENT},
        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
    }
    body = {"mechanism": "alkahest.v1", "asset": _TOKEN,
            "rates": [RateValue(field="amount", per="hour", value=100)],
            "params": {"accepted_escrow": entry}}
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


def _selected_proposal(amount: int) -> dict:
    return {"fields": {"amount": amount}, "settlement_selection": {
        "mechanism": "alkahest.v1", "option_id": _option().option_id,
        "expiration_unix": 1_800_000_000,
    }}


def _proposal(amount: int) -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": amount},
        literal_fields={"token": _TOKEN, "recipient": _RECIPIENT},
        rates=[{"field": "amount", "per": "hour", "value": "100"}],
        expiration_unix=1_800_000_000,
    )


async def _source_matches(_repository, _resolved) -> ListingSourceVerdict:
    """These tests exercise the policy hook; the source check has its own."""
    return ListingSourceVerdict("matches")


async def _start(
    *,
    sqlite_client,
    our_listing_id,
    buyer_principal,
    seller_principal,
    proposal=None,
    provision_terms=None,
    our_base_url,
    their_agent_url,
    seller_round_hook=None,
    capacity_runtime=None,
    listing_source_check=None,
):
    registration = sqlite_client.domain_registry.resolve_mode("vm")
    runtime = build_vm_negotiation_runtime(
        registration.contract,
        registry=sqlite_client.domain_registry,
        binding=registration.binding,
        capacity_runtime=capacity_runtime or _capacity_runtime(),
        seller_round_hook=seller_round_hook,
        listing_source_check=listing_source_check or _source_matches,
    )
    proposal_wire = (
        proposal.model_dump(mode="json")
        if hasattr(proposal, "model_dump")
        else proposal
    )
    return await runtime.start(
        repository=sqlite_client,
        listing_id=our_listing_id,
        buyer_principal=buyer_principal,
        seller_principal=seller_principal,
        actor_principal=buyer_principal,
        proposal=proposal_wire,
        terms=provision_terms,
        seller_agent_url=our_base_url,
        buyer_agent_url=their_agent_url,
    )


async def _continue(
    *,
    sqlite_client,
    neg_id,
    buyer_action,
    buyer_proposal,
    buyer_reason,
    buyer_principal,
    actor_principal,
    seller_principal=None,
    seller_round_hook=None,
    capacity_runtime=None,
    listing_source_check=None,
):
    registration = sqlite_client.domain_registry.resolve_mode("vm")
    runtime = build_vm_negotiation_runtime(
        registration.contract,
        registry=sqlite_client.domain_registry,
        binding=registration.binding,
        capacity_runtime=capacity_runtime or _capacity_runtime(),
        seller_round_hook=seller_round_hook,
        listing_source_check=listing_source_check or _source_matches,
    )
    return await runtime.continue_negotiation(
        repository=sqlite_client,
        negotiation_id=neg_id,
        buyer_action=buyer_action,
        buyer_proposal=buyer_proposal,
        buyer_reason=buyer_reason,
        buyer_principal=buyer_principal,
        actor_principal=actor_principal,
        actor_role=("buyer" if actor_principal == buyer_principal else "admin"),
        seller_principal=seller_principal,
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

    normalized = _decode_vm_terms(_DOMAIN, terms)

    assert normalized.decoded.duration_seconds == 3600
    assert normalized.decoded.start_utc == "2030-01-01T00:00:00Z"


def test_normalize_vm_message_terms_rejects_foreign_terms() -> None:
    terms = ProvisionTerms(
        kind="fiat.v1",
        version=1,
        payload={"invoice_id": "inv-1"},
    )

    with pytest.raises(ValueError, match=r"compute\.v1"):
        _decode_vm_terms(_DOMAIN, terms)


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
        _decode_vm_terms(_DOMAIN, terms)


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
    assert _default_seller_round_hook(domain) is seller_hook
    # The policy is given no source check and no capacity client: the
    # runtime checks the listing against its source and hands each round
    # the verdict.
    assert policy.call_args.args == ()
    assert "source_check" not in policy.call_args.kwargs


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
        await _start(
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
async def test_negotiation_runtime_uses_injected_seller_round_hook(db):
    seen = {}

    async def hook(**kwargs):
        seen["history"] = kwargs["history"]
        seen["has_policy_inputs"] = "policy_inputs" in kwargs
        seen["has_sqlite_client"] = "sqlite_client" in kwargs
        seen["listing_source"] = kwargs.get("listing_source")
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

    response = await _start(
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
    assert seen["listing_source"] == ListingSourceVerdict("matches")
    listing_binding = await db.load_listing_binding(listing_id="L-hook")
    thread_binding = await db.load_thread_binding(
        negotiation_id=response["negotiation_id"]
    )
    assert listing_binding is not None
    assert thread_binding.listing_id == listing_binding.listing_id
    assert thread_binding.site_id == listing_binding.site_id
    assert thread_binding.binding == listing_binding.binding


@pytest.mark.asyncio
async def test_negotiation_runtime_rejects_mismatched_resource_shape(db):
    """A buyer requesting a shape other than the listing's is refused outright.

    Seller negotiation policy currently prices only the listing's
    advertised shape; this pins the loud-rejection behavior rather than
    silent admission or silent fallback to the listing's shape.
    """

    async def hook(**_kwargs):
        raise AssertionError("seller policy must not run for a rejected request")

    with pytest.raises(OfferUnfulfillableError) as exc_info:
        await _start(
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
async def test_negotiation_runtime_permits_matching_resource_shape(db):
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

    response = await _start(
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
async def test_negotiation_runtime_continuation_uses_injected_seller_round_hook(db):
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

    opened = await _start(
        sqlite_client=db,
        our_listing_id="L-hook",
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        proposal=_selected_proposal(50),
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

    response = await _continue(
        sqlite_client=db,
        neg_id=opened["negotiation_id"],
        buyer_action="counter",
        buyer_proposal=_selected_proposal(100),
        buyer_reason=None,
        buyer_principal=_BUYER,
        actor_principal=_BUYER,
        seller_round_hook=continue_hook,
    )

    assert response["action"] == "accept"
    assert response["accepted_escrow_proposal"]["fields"]["amount"] == "100"
    thread = await db.load_negotiation_thread_row(negotiation_id=opened["negotiation_id"])
    assert thread["settlement_data"]["accepted_escrow_proposal"] == response["accepted_escrow_proposal"]
    assert _DOMAIN.settlement.seller_stages["alkahest.v1"].accepted_proposal(thread) == response["accepted_escrow_proposal"]
    assert seen["history"][-1].sender == "them"
    assert seen["history"][-1].proposal["fields"]["amount"] == 100
    assert seen["has_policy_inputs"] is False
    assert seen["has_sqlite_client"] is False
    thread_binding = await db.load_thread_binding(
        negotiation_id=opened["negotiation_id"]
    )
    assert db.domain_registry.resolve(thread_binding.binding) is _DOMAIN
