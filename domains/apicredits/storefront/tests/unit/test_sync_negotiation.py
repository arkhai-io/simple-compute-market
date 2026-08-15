"""Sync negotiation through the real API-credits round hook.

Capacity snapshots and key lookups are faked at the service seams the
default hook resolves at call time; everything else — guards, terminal
policy, thread persistence, token-terms persistence, and the safe default
that grants no unfunded quota hold — runs against a temporary SQLite database.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.negotiation_runtime import (
    _decode_terms,
    build_api_credit_negotiation_runtime,
)
from market_core.schemas import (
    EscrowProposal,
    ProvisionTerms,
    RateValue,
    SettlementOption,
    SettlementSelection,
    derive_settlement_option_id,
)
from market_negotiation_runtime import NegotiationStateError, OfferUnfulfillableError
from market_identity import Ed25519Signer
from market_policy.identity import Identity
from market_policy.negotiation_middleware import NegotiationDecision
from market_policy.negotiation_thread import get_thread_store
from market_policy.seller_round import SellerRoundResult

_BUYER_PRINCIPAL = Ed25519Signer(bytes.fromhex("11" * 32)).identity
_SELLER_PRINCIPAL = Ed25519Signer(bytes.fromhex("22" * 32)).identity
_STRANGER_PRINCIPAL = Ed25519Signer(bytes.fromhex("33" * 32)).identity
_TOKEN = "0x" + "01" * 20
_ESCROW = "0x" + "11" * 20
_DOMAIN = get_market_domain_contract()


def _hosted_option() -> SettlementOption:
    rates = [RateValue(field="amount", per="credit", value=100)]
    params = {
        "account_ref": "acct-api-credits",
        "authority_id": "hosted-authority-1",
        "environment": "test",
        "country": "US",
        "claimant_principal": _SELLER_PRINCIPAL.model_dump(mode="json"),
        "funds_flow": "separate_charges_transfers",
        "funding_profile": "card.v1",
        "interaction": "interactive",
        "contract_fingerprint": "sha256:" + "11" * 32,
        "condition": {
            "protocol": "arkhai.condition.v1",
            "condition_id": "api-credits-issued",
            "evaluator": {
                "kind": "builtin.v1",
                "version": "trivial.v1",
                "resolver_id": "api-credits",
                "params": {"kind": "trivial"},
            },
            "demand": {
                "encoding": "application/jcs+json",
                "value": {"kind": "api_credits.v1"},
            },
        },
    }
    return SettlementOption(
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


def _hosted_selection(*, expiration_unix: int = 1_900_000_000):
    option = _hosted_option()
    return SettlementSelection(
        mechanism=option.mechanism,
        option_id=option.option_id,
        expiration_unix=expiration_unix,
    )


class FakeCapacity:
    def __init__(self, available: int = 100) -> None:
        self.available = available
        self.reserved: list[dict] = []

    async def snapshot(self):
        return [
            {
                "resource_id": "svc-quota",
                "resource_type": "api_credits",
                "available_units": self.available,
                "total_units": 1000,
                "state": "available",
            }
        ]

    async def reserve(self, *, claim=None, deal_ref=None, ttl_seconds=None):
        self.reserved.append(
            {
                "claim": claim,
                "deal_ref": deal_ref,
                "ttl_seconds": ttl_seconds,
            }
        )
        return {
            "capacity_reservation_id": f"alloc-{len(self.reserved)}",
            "resource_id": "svc-quota",
            "allocated_units": (claim or {}).get("units"),
            "hold_expires_at": "2099-01-01 00:00",
        }


@pytest.fixture
def fake_capacity(monkeypatch):
    capacity = FakeCapacity()
    from apicredits_storefront import negotiation_runtime as runtime_module

    monkeypatch.setattr(
        runtime_module,
        "build_capacity_client",
        lambda factory: capacity,
    )
    return capacity


@pytest.fixture
def key_records(monkeypatch):
    records: dict[str, dict | None] = {}

    async def _lookup(key_id: str):
        return records.get(key_id)

    from apicredits_storefront import negotiation_runtime as runtime_module

    monkeypatch.setattr(runtime_module, "lookup_key_record", _lookup)
    return records


@pytest.fixture
async def db(tmp_path):
    import market_policy.negotiation_thread as thread_module
    from apicredits_storefront.utils.sqlite_client import SQLiteClient

    client = SQLiteClient(db_path=str(tmp_path / "credits-storefront.db"))
    thread_module._thread_store = None
    get_thread_store(
        sqlite_client=client,
        identity=Identity(agent_url="http://test-seller:8002"),
    )
    await client.upsert_listing(
        listing_id="L-tok",
        status="open",
        created_at=datetime.now().isoformat(),
        updated_at=datetime.now().isoformat(),
        offer_resource={
            "kind": "api_credits.v1",
            "service_name": "Acme Inference",
            "openapi_url": "https://api.acme.example/openapi.json",
            "base_url": "https://api.acme.example",
            "resource_id": "svc-quota",
            "capacity_site_id": "tokens",
            "offering_mode": "api_credits",
        },
        accepted_escrows=[
            {
                "chain_name": "anvil",
                "escrow_address": _ESCROW,
                "literal_fields": {"token": _TOKEN},
                "rates": [{"field": "amount", "per": "token", "value": "100"}],
            }
        ],
        settlement_options=[_hosted_option().model_dump(mode="json")],
        fulfillment_resource=None,
        max_duration_seconds=None,
        storefront_url="http://test-seller:8002",
        seller_principal=_SELLER_PRINCIPAL,
    )
    return client


def _proposal(amount: int) -> EscrowProposal:
    return EscrowProposal(
        chain_name="anvil",
        escrow_address=_ESCROW,
        fields={"token": _TOKEN, "amount": amount},
        literal_fields={"token": _TOKEN},
        rates=[{"field": "amount", "per": "token", "value": "100"}],
        expiration_unix=1_800_000_000,
    )


def _terms(quantity=3, key_mode="new", key_id=None) -> ProvisionTerms:
    key: dict = {"mode": key_mode}
    if key_id:
        key["key_id"] = key_id
    return ProvisionTerms(
        kind="api_credits.v1",
        version=1,
        payload={"quantity": quantity, "key": key},
    )


def test_decode_api_credits_message_terms_uses_domain_runtime() -> None:
    normalized = _decode_terms(
        _DOMAIN,
        ProvisionTerms(
            kind="api_credits.v1",
            version=1,
            payload={
                "quantity": "5",
                "key": {"mode": "existing", "key_id": "ak_existing"},
            },
        ),
    )

    assert normalized.decoded.quantity == 5
    assert normalized.decoded.key_mode == "existing"
    assert normalized.decoded.key_id == "ak_existing"


def test_normalize_api_credits_message_terms_rejects_foreign_terms() -> None:
    terms = ProvisionTerms(
        kind="compute.v1",
        version=1,
        payload={"duration_seconds": 60},
    )
    with pytest.raises(ValueError, match=r"api_credits\.v1"):
        _decode_terms(_DOMAIN, terms)


def test_normalize_api_credits_terms_rejects_unsupported_version() -> None:
    terms = ProvisionTerms(
        kind="api_credits.v1",
        version=2,
        payload={"quantity": 1, "key": {"mode": "new"}},
    )
    with pytest.raises(ValueError, match="version"):
        _decode_terms(_DOMAIN, terms)


async def _start(db, *, amount=300, quantity=3, key_mode="new", key_id=None):
    return await build_api_credit_negotiation_runtime(_DOMAIN).start(
        repository=db,
        listing_id="L-tok",
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_SELLER_PRINCIPAL,
        proposal=_proposal(amount),
        terms=_terms(quantity, key_mode, key_id),
        seller_agent_url="http://seller:8002",
        buyer_agent_url="http://buyer:9000",
        actor_principal=_BUYER_PRINCIPAL,
    )


async def _start_hosted(db, *, amount=300, quantity=3):
    selection = _hosted_selection()

    async def counter_at_listed_price(**_kwargs):
        return SellerRoundResult(
            our_amount=300,
            strategy_label="listed_price",
            direction="maximize",
            chain_label="hosted-review",
            decision=NegotiationDecision(
                action="counter",
                proposal={
                    "fields": {"amount": 300},
                    "settlement_selection": selection.model_dump(mode="json"),
                },
            ),
            intermediate={
                "buyer_amount": amount,
                "uses_scalar_amount": True,
            },
        )

    return await build_api_credit_negotiation_runtime(
        _DOMAIN,
        seller_round_hook=counter_at_listed_price,
    ).start(
        repository=db,
        listing_id="L-tok",
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_SELLER_PRINCIPAL,
        proposal={
            "fields": {"amount": amount},
            "settlement_selection": selection.model_dump(mode="json"),
        },
        terms=_terms(quantity),
        seller_agent_url="http://seller:8002",
        buyer_agent_url="http://buyer:9000",
        actor_principal=_BUYER_PRINCIPAL,
    )


async def test_listed_price_accept_persists_terms_without_unfunded_hold(
    db, fake_capacity, key_records
):
    # quantity 3 * unit rate 100 = 300; opening at the bound accepts
    # under the listed_price default.
    response = await _start(db, amount=300, quantity=3)
    assert response["action"] == "accept"
    assert response["accepted_provision_terms"]["payload"]["quantity"] == 3
    # Plan materialization needs a resolvable alkahest chain config (the
    # e2e topology provides one); here the proposal echo is the artifact.
    assert response["accepted_escrow_proposal"]["fields"]["amount"] == "300"

    neg_id = response["negotiation_id"]
    terms = await db.load_credit_terms(negotiation_id=neg_id)
    assert terms == {
        "negotiation_id": neg_id,
        "quantity": 3,
        "key_mode": "new",
        "key_id": None,
    }

    thread = await db.load_negotiation_thread_row(negotiation_id=neg_id)
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == 300

    assert fake_capacity.reserved == []
    assert await db.load_capacity_hold(negotiation_id=neg_id) is None


async def test_quota_guard_rejects_uncovered_quantity(db, fake_capacity, key_records):
    fake_capacity.available = 2
    with pytest.raises(OfferUnfulfillableError) as exc:
        await _start(db, amount=300, quantity=3)
    assert exc.value.reason.startswith("quota_exhausted")
    assert not fake_capacity.reserved


async def test_existing_key_owned_by_buyer_principal(db, fake_capacity, key_records):
    key_records["ak_mine"] = {
        "key_id": "ak_mine",
        "owner_scheme": _BUYER_PRINCIPAL.scheme.value,
        "owner_id": _BUYER_PRINCIPAL.identifier,
        "status": "active",
    }
    response = await _start(
        db,
        amount=300,
        quantity=3,
        key_mode="existing",
        key_id="ak_mine",
    )
    assert response["action"] == "accept"
    terms = await db.load_credit_terms(
        negotiation_id=response["negotiation_id"],
    )
    assert terms["key_mode"] == "existing"
    assert terms["key_id"] == "ak_mine"


async def test_existing_key_rejections(db, fake_capacity, key_records):
    key_records["ak_theirs"] = {
        "key_id": "ak_theirs",
        "owner_scheme": _STRANGER_PRINCIPAL.scheme.value,
        "owner_id": _STRANGER_PRINCIPAL.identifier,
        "status": "active",
    }
    with pytest.raises(OfferUnfulfillableError) as exc:
        await _start(db, key_mode="existing", key_id="ak_theirs")
    assert exc.value.reason.startswith("key_not_owned")

    with pytest.raises(OfferUnfulfillableError) as exc:
        await _start(db, key_mode="existing", key_id="ak_missing")
    assert exc.value.reason.startswith("key_not_found")


async def test_open_key_top_up_without_guarded_owner(db, fake_capacity, key_records):
    key_records["ak_open"] = {
        "key_id": "ak_open",
        "owner_scheme": None,
        "owner_id": None,
        "status": "active",
    }
    response = await _start(
        db,
        amount=300,
        quantity=3,
        key_mode="existing",
        key_id="ak_open",
    )
    assert response["action"] == "accept"


async def test_bisection_counter_round_scales_by_quantity(
    db, fake_capacity, key_records
):
    """Counter rounds keep the quantity-scaled reference from the terms row."""
    from tests._settings_overrides import settings_overrides

    with settings_overrides(**{"negotiation.policies": ["bisection"]}):
        opening = await _start(db, amount=250, quantity=3)
        assert opening["action"] == "counter"
        neg_id = opening["negotiation_id"]
        countered = int(opening["proposal"]["fields"]["amount"])
        assert countered == 275  # midpoint of 250 and the 300 bound

        response = await build_api_credit_negotiation_runtime(
            _DOMAIN
        ).continue_negotiation(
            repository=db,
            negotiation_id=neg_id,
            buyer_action="accept",
            buyer_proposal=None,
            buyer_reason=None,
            buyer_principal=_BUYER_PRINCIPAL,
            seller_principal=_SELLER_PRINCIPAL,
            actor_principal=_BUYER_PRINCIPAL,
            actor_role="buyer",
        )
    assert response["action"] == "accept"
    thread = await db.load_negotiation_thread_row(negotiation_id=neg_id)
    assert thread["terminal_state"] == "success"
    assert int(thread["agreed_price"]) == 275


async def test_hosted_selection_survives_counter_accept_and_skips_quota_hold(
    db,
    fake_capacity,
    key_records,
):
    opening = await _start_hosted(db, amount=250)
    assert opening["action"] == "counter"
    assert opening["settlement_selection"] == _hosted_selection().model_dump(
        mode="json"
    )

    negotiation_id = opening["negotiation_id"]
    response = await build_api_credit_negotiation_runtime(_DOMAIN).continue_negotiation(
        repository=db,
        negotiation_id=negotiation_id,
        buyer_action="accept",
        buyer_proposal=None,
        buyer_reason=None,
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_SELLER_PRINCIPAL,
        actor_principal=_BUYER_PRINCIPAL,
        actor_role="buyer",
    )

    assert response["action"] == "accept"
    assert response["settlement_selection"] == opening["settlement_selection"]
    assert response["settlement_plan"]["obligations"][0]["mechanism"] == (
        "fiat.stripe.v1"
    )
    thread = await db.load_negotiation_thread_row(negotiation_id=negotiation_id)
    assert (
        thread["buyer_escrow_proposal"]["settlement_selection"]
        == opening["settlement_selection"]
    )
    assert thread["settlement_plan"] == response["settlement_plan"]
    assert fake_capacity.reserved == []
    assert await db.load_capacity_hold(negotiation_id=negotiation_id) is None


@pytest.mark.parametrize(
    "changed_selection",
    [
        {
            **_hosted_selection().model_dump(mode="json"),
            "mechanism": "alkahest.v1",
        },
        {
            **_hosted_selection().model_dump(mode="json"),
            "option_id": "f" * 64,
        },
        {
            **_hosted_selection().model_dump(mode="json"),
            "expiration_unix": 1_900_000_001,
        },
    ],
)
async def test_hosted_counter_rejects_opening_selection_switch(
    db,
    fake_capacity,
    key_records,
    changed_selection,
):
    opening = await _start_hosted(db, amount=250)

    with pytest.raises(
        NegotiationStateError,
        match="opening settlement selection cannot change",
    ):
        await build_api_credit_negotiation_runtime(_DOMAIN).continue_negotiation(
            repository=db,
            negotiation_id=opening["negotiation_id"],
            buyer_action="counter",
            buyer_proposal={
                "fields": {"amount": 300},
                "settlement_selection": changed_selection,
            },
            buyer_reason=None,
            buyer_principal=_BUYER_PRINCIPAL,
            seller_principal=_SELLER_PRINCIPAL,
            actor_principal=_BUYER_PRINCIPAL,
            actor_role="buyer",
        )


async def test_hosted_accept_revalidates_current_trusted_listing_option(
    db,
    fake_capacity,
    key_records,
):
    opening = await _start_hosted(db, amount=250)
    await db.update_listing(
        listing_id="L-tok",
        settlement_options=[],
    )

    with pytest.raises(
        NegotiationStateError,
        match="no longer exact-matches the trusted listing",
    ):
        await build_api_credit_negotiation_runtime(_DOMAIN).continue_negotiation(
            repository=db,
            negotiation_id=opening["negotiation_id"],
            buyer_action="accept",
            buyer_proposal=None,
            buyer_reason=None,
            buyer_principal=_BUYER_PRINCIPAL,
            seller_principal=_SELLER_PRINCIPAL,
            actor_principal=_BUYER_PRINCIPAL,
            actor_role="buyer",
        )


def test_accepted_artifacts_stamp_the_seller_recipient(monkeypatch):
    """The accepted escrow artifacts must carry the seller's wallet as
    the escrow recipient — without it the buyer can't materialize a
    funded escrow ("must carry ... a recipient fallback"). Regression
    guard: the assembly once passed seller_wallet_address=None.
    """
    import apicredits_storefront.negotiation_runtime as sn

    captured: dict = {}

    def _fake_artifacts(**kwargs):
        captured.update(kwargs)
        return {"proposal": {}, "accepted_escrow_proposal": {}}

    monkeypatch.setattr(sn, "accepted_escrow_artifacts_from_proposal", _fake_artifacts)
    monkeypatch.setattr(sn, "_seller_wallet_address", lambda: "0xSeLLeR0000")

    sn.build_api_credit_accepted_artifacts(
        buyer_principal=_BUYER_PRINCIPAL,
        seller_principal=_SELLER_PRINCIPAL,
        proposal={"chain_name": "anvil", "escrow_address": _ESCROW},
        agreed_amount=300,
    )
    assert captured["seller_wallet_address"] == "0xSeLLeR0000"
