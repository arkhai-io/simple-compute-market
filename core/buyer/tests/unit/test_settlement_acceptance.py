"""Buyer-side validation of an option-selected seller acceptance.

The seller reply shape under test mirrors what every hosted storefront
emits at acceptance: an obligation built from the advertised option plus
the party principals, and a domain-namespaced ``service_terms`` package
(``vm.v1`` / ``bare_metal.v1`` / api-credits equivalents).
"""

from __future__ import annotations

import pytest
from market_core.schemas import (
    SettlementObligation,
    SettlementOption,
    SettlementPlan,
    SettlementSelection,
    derive_settlement_option_id,
)
from market_identity import Identity, TrustedIdentitySet

from core_buyer.negotiation_client import _validate_settlement_acceptance

_BUYER = Identity(scheme="eip191", identifier="0x" + "11" * 20)
_SELLER = Identity(scheme="eip191", identifier="0x" + "22" * 20)
_CONDITION = {"kind": "hosted_funding.v1", "resolver": "authority"}
_EXPIRATION = 1_900_000_000
_AMOUNT = 4200
_PARAMS = {
    "condition": dict(_CONDITION),
    "claimant_principal": _SELLER.model_dump(mode="json"),
}
_OPTION_ID = derive_settlement_option_id(
    mechanism="fiat.stripe.v1",
    asset="usd",
    rates=[],
    params=_PARAMS,
)


def _advertised_option() -> SettlementOption:
    return SettlementOption(
        option_id=_OPTION_ID,
        mechanism="fiat.stripe.v1",
        asset="usd",
        rates=[],
        params={key: dict(value) for key, value in _PARAMS.items()},
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
                mechanism="fiat.stripe.v1",
                params=params,
            )
        ],
    )


def _validate(plan: SettlementPlan) -> None:
    selection = SettlementSelection(
        mechanism="fiat.stripe.v1",
        option_id=_OPTION_ID,
        expiration_unix=_EXPIRATION,
    )
    _validate_settlement_acceptance(
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
