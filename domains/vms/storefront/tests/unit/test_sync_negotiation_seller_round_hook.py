from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from arkhai_vms import price_vm_shape, vm_family_rate
from core_storefront.aggregation import fill_first
from core_storefront.domain_registry import (
    StorefrontListingBinding,
    build_storefront_derivation_key,
)
from market_capacity_publication import (
    PublicationBinding,
    CapacityRuntime,
    CapacitySite,
)
from market_resource_pools_contracts.backing import BACKED
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
from market_storefront.utils.migrations import migrate_storefront_database
from tests._settings_overrides import replaced_setting
from tests.fake_site import FakeProjectionSite, site_projection_state

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


async def _policy_projections():
    """The held pool supplies policy; source confirmation is injected separately."""
    state = site_projection_state({"site-test": FakeProjectionSite(resource_pools=[
        {"pool_id": "pool-L-hook", "pool_metadata": {"policy_tags": {}}},
    ])})
    await state.poll_once()
    return state


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

    monkeypatch.setattr(
        container,
        "resolved_marketplace_signer",
        _SELLER_SIGNER,
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
    migrate_storefront_database(tmp_path / "seller_round_hook.db")
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
        # The release condition the accepted plan settles under: the address
        # book's recipient arbiter, paying the seller.
        demands=[
            {
                "chain_name": "anvil",
                "arbiter": "0x" + "33" * 20,
                "demand_data": {"recipient": "0x" + "44" * 20},
            }
        ],
    )

    async def resolve_capacity_binding(repository, listing_id):
        binding = await repository.load_listing_binding(listing_id=listing_id)
        assert binding is not None
        return PublicationBinding(
            binding.site_id,
            binding.binding.offering_mode,
            str(binding.pool_id),
            BACKED,
        )

    monkeypatch.setattr(
        "market_storefront.negotiation_runtime.capacity_binding_for_listing",
        resolve_capacity_binding,
    )
    assert await client.load_listing_binding(listing_id="L-hook") == listing_binding
    with replaced_setting("registry.urls", list(_REGISTRIES)):
        yield client


#: The registries the storefront publishes to; test URLs, never contacted.
_REGISTRIES = ("http://registry-a.test", "http://registry-b.test")


def _structure(rates: dict[str, str]) -> dict[str, list[dict[str, str]]]:
    return {
        family: [{"asset": _TOKEN, "rate": rate, "per": "hour"}]
        for family, rate in rates.items()
    }


async def _record_publish(
    db,
    structure,
    *,
    accepted: bool = True,
    registries=_REGISTRIES,
    listing_id: str = "L-hook",
) -> None:
    """Record a publish of ``structure`` as the publication kit records it."""
    payload = {"listing_id": listing_id, "pricing": {"rate_structure": structure}}
    for registry_url in registries:
        await db.upsert_publication(
            listing_id=listing_id,
            registry_url=registry_url,
            payload=payload,
            status="published" if accepted else "failed",
            last_error=None if accepted else "registry unavailable",
            published_payload=payload if accepted else None,
        )


async def _reprice(db, structure, *, accepted: bool = True, registries=_REGISTRIES):
    """Store a new rate structure and record a publish of it."""
    await db.update_listing(listing_id="L-hook", rate_structure=structure)
    await _record_publish(db, structure, accepted=accepted, registries=registries)


def _option() -> SettlementOption:
    entry = {
        "chain_name": "anvil", "escrow_address": _ESCROW,
        "literal_fields": {"token": _TOKEN, "recipient": _RECIPIENT},
        "rates": [{"field": "amount", "per": "hour", "value": "100"}],
    }
    body = {
        "price": {
            "asset": _TOKEN,
            "rates": [RateValue(field="amount", per="hour", value=100)],
        },
        "settlement": {"schema": "alkahest.v1", **({"accepted_escrow": entry} or {})},
    }
    return SettlementOption(option_id=derive_settlement_option_id(**body), **body)


def _selected_proposal(amount: int) -> dict:
    return {
        "fields": {"amount": amount},
        "settlement_selection": {
            "option_id": _option().option_id,
            "settlement": {"schema": "alkahest.v1"},
            "expiration_unix": 1_800_000_000,
        },
    }


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
        site_projections=await _policy_projections(),
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
        site_projections=await _policy_projections(),
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


_BEFORE = {"gpu": "60", "cpu": "10"}
_AFTER = {"gpu": "80", "cpu": "5"}


def _countering_hook() -> AsyncMock:
    return AsyncMock(return_value=SellerRoundResult(
        our_amount=10_000,
        strategy_label="maximize",
        direction="maximize",
        chain_label="custom",
        decision=NegotiationDecision(action="counter", proposal=_selected_proposal(10_000)),
    ))


async def _open_shape_priced(db, hook):
    return await _start(
        sqlite_client=db, our_listing_id="L-hook",
        buyer_principal=_BUYER, seller_principal=_SELLER,
        proposal=_selected_proposal(9_000),
        provision_terms=ProvisionTerms(kind="compute.v1", version=1, payload={
            "duration_seconds": 3600, "ssh_public_key": "ssh-ed25519 AAAA",
        }),
        our_base_url="http://seller.test", their_agent_url="http://buyer.test",
        seller_round_hook=hook,
    )


async def _admin_accept(db, negotiation_id):
    registration = db.domain_registry.resolve_mode("vm")
    runtime = build_vm_negotiation_runtime(
        registration.contract,
        registry=db.domain_registry,
        binding=registration.binding,
        capacity_runtime=_capacity_runtime(),
        site_projections=await _policy_projections(),
        listing_source_check=_source_matches,
    )
    return await runtime.accept_administratively(
        repository=db, listing_id="L-hook", negotiation_id=negotiation_id,
        amount=10_000, actor_principal=_SELLER,
    )


async def _round(db, negotiation_id, action, hook):
    if action == "admin_accept":
        return await _admin_accept(db, negotiation_id)
    return await _continue(
        sqlite_client=db, neg_id=negotiation_id,
        buyer_action=action,
        buyer_proposal=None if action == "exit" else _selected_proposal(10_000),
        buyer_reason=None, buyer_principal=_BUYER, actor_principal=_BUYER,
        seller_round_hook=hook,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["counter", "accept", "admin_accept", "exit"])
async def test_a_published_repricing_refuses_even_with_unchanged_listing_total(db, action):
    advertised = {"gpu": {"count": 1, "model": "H200"}, "cpu": {"count": 4}}
    revised = {"gpu": {"count": 1, "model": "H200"}, "cpu": {"count": 2}}

    def price(shape, rates):
        return price_vm_shape(
            shape, {family: vm_family_rate(rate, "hour") for family, rate in rates.items()}
        ).amount

    assert price(advertised, _BEFORE) == price(advertised, _AFTER) == "100"
    assert price(revised, _BEFORE) == "80"
    assert price(revised, _AFTER) == "90"
    await _reprice(db, _structure(_BEFORE))
    hook = _countering_hook()
    opened = await _open_shape_priced(db, hook)
    await _reprice(db, _structure(_AFTER))
    hook.reset_mock()
    if action == "exit":
        response = await _round(db, opened["negotiation_id"], action, hook)
        assert response["action"] == "exit"
        hook.assert_not_awaited()
        return
    with pytest.raises(OfferUnfulfillableError, match="rate_structure_changed_reopen"):
        await _round(db, opened["negotiation_id"], action, hook)
    hook.assert_not_awaited()
    thread = await db.load_negotiation_thread_row(negotiation_id=opened["negotiation_id"])
    assert thread["terminal_state"] is None


@pytest.mark.asyncio
async def test_a_failed_republication_keeps_the_negotiation_on_its_published_rates(db):
    """A stored repricing no registry accepted is not what a buyer can read."""
    await _reprice(db, _structure(_BEFORE))
    hook = _countering_hook()
    opened = await _open_shape_priced(db, hook)
    await _reprice(db, _structure(_AFTER), accepted=False)
    hook.reset_mock()

    response = await _round(db, opened["negotiation_id"], "counter", hook)

    assert response["action"] == "counter"
    hook.assert_awaited_once()
    assert hook.await_args.kwargs["listing"]["rate_structure"] == _structure(_BEFORE)
    stored = await db.load_listing(listing_id="L-hook")
    assert stored["rate_structure"] == _structure(_AFTER)


@pytest.mark.asyncio
async def test_an_upgraded_listing_refuses_openings_until_its_first_successful_publish(db):
    """Rows recorded before the published payload was kept carry none."""
    await db.update_listing(listing_id="L-hook", rate_structure=_structure(_BEFORE))
    for registry_url in _REGISTRIES:
        await db.upsert_publication(
            listing_id="L-hook", registry_url=registry_url,
            payload={"listing_id": "L-hook"}, status="published",
        )
    hook = _countering_hook()

    with pytest.raises(OfferUnfulfillableError, match="^rate_structure_unpublished$"):
        await _open_shape_priced(db, hook)
    hook.assert_not_awaited()

    await _record_publish(db, _structure(_BEFORE))
    opened = await _open_shape_priced(db, hook)
    assert opened["action"] == "counter"
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_partial_first_refresh_refuses_until_the_unseen_registry_accepts(db):
    """A registry still serving a listing published before payloads were kept
    may hold rates the seller cannot see, so a refresh accepted elsewhere does
    not let a negotiation price from the new rates alone."""
    await db.update_listing(listing_id="L-hook", rate_structure=_structure(_BEFORE))
    for registry_url in _REGISTRIES:
        await db.upsert_publication(
            listing_id="L-hook", registry_url=registry_url,
            payload={"listing_id": "L-hook"}, status="published",
        )
    # The first refresh after the upgrade reprices; one registry accepts it.
    await _reprice(db, _structure(_AFTER), registries=_REGISTRIES[:1])
    await _record_publish(db, _structure(_AFTER), accepted=False, registries=_REGISTRIES[1:])
    hook = _countering_hook()

    with pytest.raises(OfferUnfulfillableError, match="^rate_structure_divergent$"):
        await _open_shape_priced(db, hook)
    hook.assert_not_awaited()

    # Convergence resends the listing to the registry that refused it.
    await _record_publish(db, _structure(_AFTER), registries=_REGISTRIES[1:])
    opened = await _open_shape_priced(db, hook)
    assert opened["action"] == "counter"
    assert hook.await_args.kwargs["listing"]["rate_structure"] == _structure(_AFTER)


@pytest.mark.asyncio
async def test_a_flat_priced_listing_negotiates_beside_an_unseen_registry(db):
    """A flat-priced quote reads no rate structure, so a registry's unknown
    payload cannot diverge from it."""
    await db.upsert_publication(
        listing_id="L-hook", registry_url=_REGISTRIES[0],
        payload={"listing_id": "L-hook"}, status="published",
    )
    await _record_publish(db, None, registries=_REGISTRIES[1:])
    hook = _countering_hook()

    opened = await _open_shape_priced(db, hook)

    assert opened["action"] == "counter"
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_registry_never_sent_the_listing_does_not_block_negotiation(db):
    """A configured registry with no publication of the listing serves none of it."""
    await _reprice(db, _structure(_BEFORE), registries=_REGISTRIES[:1])
    hook = _countering_hook()

    opened = await _open_shape_priced(db, hook)

    assert opened["action"] == "counter"
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_registries_holding_different_rates_refuse_until_the_resend_converges(db):
    await _reprice(db, _structure(_BEFORE))
    hook = _countering_hook()
    opened = await _open_shape_priced(db, hook)
    # One registry accepted the repricing, the other missed it.
    await _reprice(db, _structure(_AFTER), registries=_REGISTRIES[:1])
    await _record_publish(db, _structure(_AFTER), accepted=False, registries=_REGISTRIES[1:])
    hook.reset_mock()

    with pytest.raises(OfferUnfulfillableError, match="^rate_structure_divergent$"):
        await _open_shape_priced(db, hook)
    with pytest.raises(OfferUnfulfillableError, match="^rate_structure_divergent$"):
        await _round(db, opened["negotiation_id"], "counter", hook)
    hook.assert_not_awaited()
    thread = await db.load_negotiation_thread_row(negotiation_id=opened["negotiation_id"])
    assert thread["terminal_state"] is None

    # Convergence resends the listing to the registry that diverged.
    await _record_publish(db, _structure(_AFTER), registries=_REGISTRIES[1:])
    reopened = await _open_shape_priced(db, hook)
    assert reopened["action"] == "counter"
    with pytest.raises(OfferUnfulfillableError, match="rate_structure_changed_reopen"):
        await _round(db, opened["negotiation_id"], "counter", hook)


@pytest.mark.asyncio
async def test_a_registry_no_longer_configured_is_not_read(db):
    await _reprice(db, _structure(_BEFORE))
    await _record_publish(db, _structure(_AFTER), registries=("http://retired.test",))
    hook = _countering_hook()

    opened = await _open_shape_priced(db, hook)

    assert opened["action"] == "counter"
    assert hook.await_args.kwargs["listing"]["rate_structure"] == _structure(_BEFORE)


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
        buyer_proposal={
            **_selected_proposal(100),
            "provision_terms": {
                "kind": "compute.v1", "version": 1,
                "payload": {"gpu": {"model": "H200", "count": 1}},
            },
        },
        buyer_reason=None,
        buyer_principal=_BUYER,
        actor_principal=_BUYER,
        seller_round_hook=continue_hook,
    )

    assert response["action"] == "accept"
    messages = await db.load_negotiation_thread(negotiation_id=opened["negotiation_id"])
    assert messages[-1]["provision_terms"]["payload"]["compute_resource"] == {
        "gpu_model": "H200", "gpu_count": 1,
    }
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
