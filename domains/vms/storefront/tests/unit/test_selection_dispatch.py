"""Exact-selection acceptance dispatches obligations through the registry."""

from __future__ import annotations

import pytest
from market_core.schemas import RateValue, derive_settlement_option_id
from market_hosted_settlement import (
    StripeSettlementConfig,
    default_hosted_selection_dispatch,
)
from market_identity import Ed25519Signer
from market_negotiation_runtime import OfferUnfulfillableError
from market_settlement_runtime import SettlementConfig
from market_storefront.negotiation_runtime import _accepted_selection_artifacts
from market_storefront.settlement_composition import (
    VmSettlementComposition,
    build_storefront_settlement_registry,
)

_BUYER = Ed25519Signer(b"\x51" * 32).identity
_SELLER = Ed25519Signer(b"\x52" * 32).identity


def _hosted_option() -> dict:
    rates = [RateValue(field="amount", per="hour", value=200)]
    params = {
        "account_ref": "acct-vm",
        "authority_id": "hosted-authority-1",
        "environment": "test",
        "country": "US",
        "claimant_principal": _SELLER.model_dump(mode="json"),
        "funds_flow": "separate_charges_transfers",
        "funding_profile": "card.v1",
        "interaction": "interactive",
        "contract_fingerprint": "sha256:" + "22" * 32,
        "condition": {
            "protocol": "arkhai.condition.v1",
            "condition_id": "vm-fulfilled",
            "evaluator": {
                "kind": "builtin.v1",
                "version": "trivial.v1",
                "resolver_id": "vm",
                "params": {"kind": "trivial"},
            },
            "demand": {
                "encoding": "application/jcs+json",
                "value": {"kind": "vm.v1"},
            },
        },
    }
    return {
        "option_id": derive_settlement_option_id(
            mechanism="fiat.stripe.v1",
            asset="usd",
            rates=rates,
            params=params,
        ),
        "mechanism": "fiat.stripe.v1",
        "asset": "usd",
        "rates": [rate.model_dump(mode="json") for rate in rates],
        "params": params,
    }


def _selection(option: dict) -> dict:
    return {
        "mechanism": option["mechanism"],
        "option_id": option["option_id"],
        "expiration_unix": 1_900_000_000,
    }


def _listing(option: dict) -> dict:
    return {
        "listing_id": "L-vm",
        "settlement_options": [dict(option)],
        "offer_resource": {"resource_id": "vm-1"},
    }


def _provision() -> dict:
    return {
        "kind": "compute.v1",
        "version": 1,
        "payload": {"duration_seconds": 7200, "ssh_public_key": "ssh-rsa AAAA"},
    }


def test_scalar_amount_must_match_the_mechanism_build() -> None:
    option = _hosted_option()
    dispatch = default_hosted_selection_dispatch()
    artifacts = _accepted_selection_artifacts(
        dispatch,
        selection=_selection(option),
        option=option,
        agreed_amount=400,
        duration_seconds=7200,
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        listing=_listing(option),
        provision_terms=_provision(),
    )
    obligation = artifacts["settlement_plan"]["obligations"][0]
    assert obligation["amount"] == "400"
    assert artifacts["settlement_plan"]["service_terms"]["vm.v1"]["listing_id"] == (
        "L-vm"
    )
    with pytest.raises(OfferUnfulfillableError, match="duration_scaled"):
        _accepted_selection_artifacts(
            dispatch,
            selection=_selection(option),
            option=option,
            agreed_amount=399,
            duration_seconds=7200,
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
            listing=_listing(option),
            provision_terms=_provision(),
        )


def test_uncomposed_mechanism_selection_is_refused() -> None:
    option = _hosted_option()
    option = {**option, "mechanism": "demo.intro.v1"}
    option["option_id"] = derive_settlement_option_id(
        mechanism=option["mechanism"],
        asset=option["asset"],
        rates=[RateValue.model_validate(rate) for rate in option["rates"]],
        params=option["params"],
    )
    with pytest.raises(OfferUnfulfillableError, match="mechanism_unsupported"):
        _accepted_selection_artifacts(
            default_hosted_selection_dispatch(),
            selection=_selection(option),
            option=option,
            agreed_amount=0,
            duration_seconds=7200,
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
            listing=_listing(option),
            provision_terms=_provision(),
        )


def test_composition_dispatch_surfaces_only_obligation_builders() -> None:
    registry = build_storefront_settlement_registry()
    config = SettlementConfig(
        priority=("alkahest.v1", "fiat.stripe.v1"),
        mechanisms={"stripe": StripeSettlementConfig()},
    )
    composition = VmSettlementComposition(
        domain=None,
        repository=None,
        runtime=None,
        coordinator=None,
        worker=None,
        local_principal=_SELLER,
        mechanism_clients={},
        evidence_clients={},
        settlement_config=config,
        configuration_registry=registry,
        mechanism_resources={},
    )
    dispatch = composition.accepted_obligation_dispatch()
    assert set(dispatch) == {"fiat.stripe.v1"}
    built = dispatch["fiat.stripe.v1"](
        _hosted_option(),
        {
            "buyer_principal": _BUYER.model_dump(mode="json"),
            "seller_principal": _SELLER.model_dump(mode="json"),
            "expiration_unix": 1_900_000_000,
            "duration_seconds": 3600,
            "domain_param_keys": (),
        },
    )
    assert built.amount == 200
