"""Buyer-side validation of an option-selected seller acceptance.

The seller reply shape under test mirrors what an option-selected storefront
emits at acceptance: an obligation built from the advertised option plus
the party principals, and a domain-namespaced ``service_terms`` package
(``vm.v1`` / ``bare_metal.v1`` / api-credits equivalents).
"""

from __future__ import annotations

import base64
from types import SimpleNamespace

import pytest
from core_buyer.negotiation_client import (
    _parse_settlement_data,
    _validate_settlement_acceptance,
    negotiate_with_seller,
)
from market_core.schemas import (
    Agreement,
    SettlementObligation,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
    derive_settlement_option_id,
)
from market_identity import Ed25519Signer, Identity, TrustedIdentitySet


def test_seller_settlement_data_survives_buyer_acceptance(monkeypatch) -> None:
    buyer = Ed25519Signer(bytes([17]) * 32)
    seller = Ed25519Signer(bytes([34]) * 32)
    provision_terms = {"kind": "example.v1", "version": 1, "payload": {}}
    agreement = Agreement(
        negotiation_id="neg-1",
        listing_id="listing-1",
        listing_hash="0" * 64,
        buyer=buyer.identity.model_dump(mode="json"),
        seller=seller.identity.model_dump(mode="json"),
        amount=4200,
        duration_seconds=3600,
        start_utc="2025-01-01T00:00:00Z",
        accepted_at="2025-01-01T00:00:00Z",
    )
    agreement_bytes = agreement.model_dump_json(exclude_none=True).encode()
    settlement_data = {"mandate": {"opaque": "to-core"}}
    reply = {
        "negotiation_id": "neg-1",
        "action": "accept",
        "proposal": {"fields": {"amount": 4200}},
        "buyer_principal": buyer.identity.model_dump(mode="json"),
        "seller_principal": seller.identity.model_dump(mode="json"),
        "accepted_provision_terms": provision_terms,
        "agreement": agreement.model_dump(mode="json", exclude_none=True),
        "agreement_bytes": base64.b64encode(agreement_bytes).decode("ascii"),
        "settlement_data": settlement_data,
    }

    monkeypatch.setattr(
        "core_buyer.negotiation_client.run_negotiation_chain",
        lambda *_args, **_kwargs: SimpleNamespace(
            action="counter", proposal={"fields": {"amount": 4200}}
        ),
    )
    monkeypatch.setattr(
        "core_buyer.negotiation_client._authenticated_json",
        lambda *_args, **_kwargs: reply,
    )
    accepted = []
    observed = []

    def validate_acceptance(outcome):
        assert observed == []
        accepted.append(outcome)

    outcome = negotiate_with_seller(
        seller_url="http://seller",
        principal=buyer.identity,
        signer=buyer,
        listing_id="listing-1",
        resolve_seller_principals=lambda: TrustedIdentitySet(
            identities=(seller.identity,)
        ),
        initial_price=4200,
        max_price=4200,
        unit_count=1,
        provision_terms=provision_terms,
        escrow_proposal={},
        encode_escrow_proposal=lambda _proposal: {"fields": {"amount": 4200}},
        chain=[],
        validate_acceptance=validate_acceptance,
        on_round=lambda *_args: observed.append("accepted"),
    )

    assert accepted == [outcome]
    assert accepted[0] is outcome
    assert observed == ["accepted"]
    assert outcome.settlement_data == settlement_data
    assert outcome.to_dict()["settlement_data"] == settlement_data
    assert _parse_settlement_data({}) is None
    with pytest.raises(ValueError, match="must be an object"):
        _parse_settlement_data({"settlement_data": ["not", "an object"]})


_BUYER = Identity(scheme="eip191", identifier="0x" + "11" * 20)
_SELLER = Identity(scheme="eip191", identifier="0x" + "22" * 20)
_CONDITION = {"kind": "example.condition.v1", "resolver": "authority"}
_EXPIRATION = 1_900_000_000
_AMOUNT = 4200
_PARAMS = {
    "condition": dict(_CONDITION),
    "claimant_principal": _SELLER.model_dump(mode="json"),
}
_OPTION_ID = derive_settlement_option_id(
    mechanism="example.payment.v1",
    asset="usd",
    rates=[],
    params=_PARAMS,
)


def _advertised_option() -> SettlementOption:
    return SettlementOption(
        option_id=_OPTION_ID,
        mechanism="example.payment.v1",
        asset="usd",
        rates=[],
        params={key: dict(value) for key, value in _PARAMS.items()},
    )


def _agreement(
    option: SettlementOption,
    *,
    amount: int = _AMOUNT,
    listing_id: str = "L-hosted",
) -> Agreement:
    return Agreement(
        negotiation_id="neg-1",
        listing_id=listing_id,
        listing_hash="0" * 64,
        buyer=_BUYER.model_dump(mode="json"),
        seller=_SELLER.model_dump(mode="json"),
        settlement=option,
        amount=amount,
        asset=option.asset,
        duration_seconds=3600,
        start_utc="2025-01-01T00:00:00Z",
        accepted_at="2025-01-01T00:00:00Z",
    )


def _seller_plan(service_terms: dict) -> SettlementPlan:
    option = _advertised_option()
    params = dict(option.params)
    params["payer_principal"] = _BUYER.model_dump(mode="json")
    params["claimant_principal"] = _SELLER.model_dump(mode="json")
    return SettlementPlan(
        buyer_principal=_BUYER.model_dump(mode="json"),
        seller_principal=_SELLER.model_dump(mode="json"),
        service_terms=service_terms,
        obligations=[
            SettlementObligation(
                payer="buyer",
                claimant="seller",
                payer_principal=_BUYER.model_dump(mode="json"),
                claimant_principal=_SELLER.model_dump(mode="json"),
                amount=_AMOUNT,
                asset="usd",
                expiration_unix=_EXPIRATION,
                conditions=[dict(_CONDITION)],
                mechanism="example.payment.v1",
                params=params,
            )
        ],
    )


def _validate(plan: SettlementPlan) -> None:
    selection = SettlementSelection(
        mechanism="example.payment.v1",
        option_id=_OPTION_ID,
        expiration_unix=_EXPIRATION,
    )
    _validate_settlement_acceptance(
        agreement=_agreement(_advertised_option()),
        expected_listing_id="L-hosted",
        reply={
            "buyer_principal": _BUYER.model_dump(mode="json"),
            "seller_principal": _SELLER.model_dump(mode="json"),
        },
        selection=selection,
        plan=plan,
        expected_selection=selection,
        advertised_option=_advertised_option(),
        agreed_amount=_AMOUNT,
        expected_plan=None,
        buyer_principal=_BUYER,
        trusted_seller_principals=TrustedIdentitySet(identities=(_SELLER,)),
        validate_advertised_plan=None,
    )


def test_accepts_seller_plan_with_domain_service_terms() -> None:
    plan = _seller_plan(
        service_terms={
            "vm.v1": {
                "listing_id": "L-hosted",
                "order": {"offer_resource": {"resource_id": "resource-hosted"}},
                "provision": {"ssh_public_key": "ssh-rsa AAAA"},
            }
        }
    )
    _validate(plan)


def test_accepts_seller_plan_with_empty_service_terms() -> None:
    _validate(_seller_plan(service_terms={}))


_CONTACT_PARAMS = {
    "profile": "default",
    "channel": "telegram",
    "terms": "Net-30, prose contract on request.",
    "claimant_principal": _SELLER.model_dump(mode="json"),
}
_CONTACT_OPTION_ID = derive_settlement_option_id(
    mechanism="contact-exchange.v1",
    asset="introduction",
    rates=[],
    params=_CONTACT_PARAMS,
)


def test_accepts_amountless_introduction_plan() -> None:
    """An introduction accept mirrors the contact-exchange seller shape:
    amountless obligation, nominal asset, mechanism-namespaced package."""

    option = SettlementOption(
        option_id=_CONTACT_OPTION_ID,
        mechanism="contact-exchange.v1",
        asset="introduction",
        rates=[],
        params=dict(_CONTACT_PARAMS),
    )
    params = dict(option.params)
    params["payer_principal"] = _BUYER.model_dump(mode="json")
    params["claimant_principal"] = _SELLER.model_dump(mode="json")
    plan = SettlementPlan(
        buyer_principal=_BUYER.model_dump(mode="json"),
        seller_principal=_SELLER.model_dump(mode="json"),
        service_terms={
            "contact-exchange.v1": {
                "option_id": _CONTACT_OPTION_ID,
                "profile": "default",
                "channel": "telegram",
                "terms": "Net-30, prose contract on request.",
            }
        },
        obligations=[
            SettlementObligation(
                payer="buyer",
                claimant="seller",
                payer_principal=_BUYER.model_dump(mode="json"),
                claimant_principal=_SELLER.model_dump(mode="json"),
                amount=None,
                asset="introduction",
                expiration_unix=_EXPIRATION,
                conditions=[],
                mechanism="contact-exchange.v1",
                params=params,
            )
        ],
    )
    selection = SettlementSelection(
        mechanism="contact-exchange.v1",
        option_id=_CONTACT_OPTION_ID,
        expiration_unix=_EXPIRATION,
    )
    _validate_settlement_acceptance(
        agreement=_agreement(option, amount=0, listing_id="L-contact"),
        expected_listing_id="L-contact",
        reply={
            "buyer_principal": _BUYER.model_dump(mode="json"),
            "seller_principal": _SELLER.model_dump(mode="json"),
        },
        selection=selection,
        plan=plan,
        expected_selection=selection,
        advertised_option=option,
        agreed_amount=None,
        expected_plan=None,
        buyer_principal=_BUYER,
        trusted_seller_principals=TrustedIdentitySet(identities=(_SELLER,)),
        validate_advertised_plan=None,
    )


def test_rejects_tampered_conditions() -> None:
    plan = _seller_plan(service_terms={})
    tampered = plan.obligations[0].model_copy(
        update={"conditions": [{"kind": "other.v1"}]}
    )
    with pytest.raises(RuntimeError, match="differ from the advertised option"):
        _validate(plan.model_copy(update={"obligations": [tampered]}))


def test_rejects_tampered_params() -> None:
    plan = _seller_plan(service_terms={})
    params = dict(plan.obligations[0].params)
    params["destination"] = "attacker"
    tampered = plan.obligations[0].model_copy(update={"params": params})
    with pytest.raises(RuntimeError, match="params differ"):
        _validate(plan.model_copy(update={"obligations": [tampered]}))
