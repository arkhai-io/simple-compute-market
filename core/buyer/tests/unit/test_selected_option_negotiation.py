"""Shared buyer orchestration resolves a hook's selection to the advertised option.

A domain's buyer hook may return a bare ``SettlementSelection`` naming a
mechanism and option ID. Negotiation needs the option itself — its rate and
acceptance contract — so orchestration resolves the selection against the
listing before it contacts the seller, and refuses a selection the listing
does not advertise.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

import pytest
from market_core.schemas import (
    RateValue,
    SettlementOption,
    SettlementSelection,
    derive_settlement_option_id,
)
from market_identity import Ed25519Signer, TrustedIdentitySet

from core_buyer import BuyConfig, BuyConstraints, RegistryAuthority
from core_buyer.negotiation_client import NegotiationOutcome, negotiate_with_seller
from core_buyer.orchestration import make_negotiate_hook

# Deterministic development keys and addresses for these tests only; never used
# on any network.
BUYER = Ed25519Signer(b"\x41" * 32)
REGISTRY = Ed25519Signer(b"\x42" * 32)
SELLER = Ed25519Signer(b"\x43" * 32)


def _option(mechanism: str, asset: str, rate: int) -> SettlementOption:
    rates = [RateValue(field="amount", per="hour", value=rate)]
    params = {"claimant_principal": SELLER.identity.model_dump(mode="json")}
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism=mechanism, asset=asset, rates=rates, params=params
        ),
        mechanism=mechanism,
        asset=asset,
        rates=rates,
        params=params,
    )


PAYMENT = _option("arkhai.payments.v1", "USD/2", 300)
ESCROW = _option("alkahest.v1", "erc20:0x" + "aa" * 20, 900)


def _listing() -> dict[str, Any]:
    return {
        "listing_id": "L1",
        "publisher_id": 7,
        "storefront_url": "http://seller",
        "source_registry_url": "http://registry",
        "source_registry_authority": "registry",
        "publisher_principals": TrustedIdentitySet(
            identities=(SELLER.identity,)
        ).model_dump(mode="json"),
        "settlement_options": [
            ESCROW.model_dump(mode="json"),
            PAYMENT.model_dump(mode="json"),
        ],
    }


def _config() -> BuyConfig:
    return BuyConfig(
        registry_urls=["http://registry"],
        registry_authorities={
            "http://registry": RegistryAuthority(
                authority="registry",
                principals=TrustedIdentitySet(identities=(REGISTRY.identity,)),
            )
        },
        principal=BUYER.identity,
        buyer_profile_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
        signer=BUYER,
    )


def _hook(selection: SettlementSelection, revalidated: list[SettlementOption]):
    async def revalidate(_match: dict[str, Any], option: SettlementOption) -> None:
        revalidated.append(option)

    return make_negotiate_hook(
        config=_config(),
        constraints=BuyConstraints(),
        provision={"kind": "example.v1", "version": 1, "payload": {}},
        unit_count=1.0,
        build_escrow_proposal=lambda _match: selection,
        encode_escrow_proposal=lambda proposal: proposal,
        decode_provision_terms=lambda value: value,
        decode_escrow_proposal=lambda value: value,
        decode_escrow_terms=lambda value: value,
        max_negotiation_rounds=3,
        derive_prices=lambda _match: (300, 300),
        chain=None,
        revalidate_settlement=revalidate,
    )


def test_a_payment_selection_negotiates_with_the_advertised_payment_option() -> None:
    selection = SettlementSelection(
        mechanism=PAYMENT.mechanism, option_id=PAYMENT.option_id
    )
    revalidated: list[SettlementOption] = []
    calls: list[dict[str, Any]] = []

    def negotiate(**kwargs: Any) -> NegotiationOutcome:
        calls.append(kwargs)
        return NegotiationOutcome(status="exited", negotiation_id=None, reason="seller_exit")

    with (
        patch("core_buyer.orchestration.fetch_listing_dict", return_value=_listing()),
        patch("core_buyer.orchestration.negotiate_with_seller", negotiate),
    ):
        _hook(selection, revalidated)([_listing()], lambda *_args: None)

    assert revalidated == [PAYMENT]
    [call] = calls
    assert call["settlement_selection"] == selection
    # The payment option, not the escrow advertised beside it, reaches the policy.
    assert call["policy_params"]["_selected_settlement_option"] == PAYMENT.model_dump(
        mode="json"
    )


def test_the_selected_option_lets_the_opening_carry_an_amount() -> None:
    """With the advertised option in its context, the buyer's opening bargains a
    scalar amount; without it the opening carries none.

    The amount's value is the domain's derived opening price (`initial_price`
    times the unit count), deliberately unlike either option's rate here: that a
    domain derives it from the selected option's rate is proved for the credits
    buyer by its in-process buy test, not by core.
    """

    sent: list[dict[str, Any]] = []

    def capture(_url: str, body: Any, **_kwargs: Any) -> dict[str, Any]:
        sent.append(body)
        return {"negotiation_id": "N1", "action": "exit", "reason": "test"}

    def opening(policy_params: dict[str, Any]) -> dict[str, Any]:
        sent.clear()
        with patch("core_buyer.negotiation_client._authenticated_json", capture):
            negotiate_with_seller(
                seller_url="http://seller",
                principal=BUYER.identity,
                signer=BUYER,
                listing_id="L1",
                resolve_seller_principals=lambda: TrustedIdentitySet(
                    identities=(SELLER.identity,)
                ),
                initial_price=250,
                max_price=250,
                unit_count=1,
                provision_terms={"kind": "example.v1", "version": 1, "payload": {}},
                escrow_proposal=None,
                encode_escrow_proposal=lambda proposal: proposal,
                settlement_selection=SettlementSelection(
                    mechanism=PAYMENT.mechanism, option_id=PAYMENT.option_id
                ),
                policy_params=policy_params,
            )
        return sent[0]["proposal"]

    selected = opening(
        {"_selected_settlement_option": PAYMENT.model_dump(mode="json")}
    )
    assert selected["fields"]["amount"] == "250"
    unselected = opening({})
    assert "amount" not in (unselected.get("fields") or {})


@pytest.mark.parametrize(
    "selection",
    [
        SettlementSelection(mechanism=PAYMENT.mechanism, option_id="f" * 64),
        SettlementSelection(mechanism="unknown.v1", option_id=PAYMENT.option_id),
    ],
    ids=["unadvertised-option-id", "unadvertised-mechanism"],
)
def test_a_selection_the_listing_does_not_advertise_exits_before_negotiating(
    selection: SettlementSelection,
) -> None:
    revalidated: list[SettlementOption] = []

    def negotiate(**_kwargs: Any) -> NegotiationOutcome:
        raise AssertionError("the seller must not be contacted")

    with (
        patch("core_buyer.orchestration.fetch_listing_dict", side_effect=AssertionError),
        patch("core_buyer.orchestration.negotiate_with_seller", negotiate),
    ):
        result = _hook(selection, revalidated)([_listing()], lambda *_args: None)

    assert revalidated == []
    assert result.outcome is None
    assert [attempt["error"] for attempt in result.attempts] == [
        "unadvertised_settlement_selection"
    ]
