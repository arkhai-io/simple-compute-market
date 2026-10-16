"""Exact-selection acceptance refuses a mechanism the composition lacks, and a
mechanism it builds no obligation for unless that mechanism settles from the
Agreement alone."""

from __future__ import annotations

import pytest
from market_core.schemas import RateValue, derive_settlement_option_id
from market_identity import Ed25519Signer
from market_negotiation_runtime import OfferUnfulfillableError
from market_storefront.negotiation_runtime import _accepted_selection_artifacts

_BUYER = Ed25519Signer(b"\x51" * 32).identity
_SELLER = Ed25519Signer(b"\x52" * 32).identity


def _option() -> dict:
    rates = [RateValue(field="amount", per="hour", value=200)]
    params = {"claimant_principal": _SELLER.model_dump(mode="json")}
    return {
        "option_id": derive_settlement_option_id(
            mechanism="demo.intro.v1",
            asset="usd",
            rates=rates,
            params=params,
        ),
        "mechanism": "demo.intro.v1",
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
        "listing_resource": {"resource_id": "vm-1"},
    }


def _provision() -> dict:
    return {
        "kind": "compute.v1",
        "version": 1,
        "payload": {"duration_seconds": 7200, "ssh_public_key": "ssh-rsa AAAA"},
    }


def test_uncomposed_mechanism_selection_is_refused() -> None:
    option = _option()
    option = {**option, "mechanism": "demo.intro.v1"}
    option["option_id"] = derive_settlement_option_id(
        mechanism=option["mechanism"],
        asset=option["asset"],
        rates=[RateValue.model_validate(rate) for rate in option["rates"]],
        params=option["params"],
    )
    with pytest.raises(OfferUnfulfillableError, match="mechanism_unsupported"):
        _accepted_selection_artifacts(
            {},
            selection=_selection(option),
            option=option,
            agreed_amount=0,
            duration_seconds=7200,
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
            listing=_listing(option),
            provision_terms=_provision(),
            settles_from_agreement=False,
        )


def _select_without_a_builder(*, settles_from_agreement: bool) -> dict:
    option = _option()
    return _accepted_selection_artifacts(
        {"demo.intro.v1": None},
        selection=_selection(option),
        option=option,
        agreed_amount=0,
        duration_seconds=7200,
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        listing=_listing(option),
        provision_terms=_provision(),
        settles_from_agreement=settles_from_agreement,
    )


def test_a_selection_needing_a_plan_its_mechanism_cannot_build_is_refused() -> None:
    with pytest.raises(OfferUnfulfillableError, match="settlement_selection_requires_plan"):
        _select_without_a_builder(settles_from_agreement=False)


def test_a_selection_settling_from_the_agreement_is_accepted_without_a_plan() -> None:
    artifacts = _select_without_a_builder(settles_from_agreement=True)

    assert "settlement_plan" not in artifacts
    assert artifacts["settlement_selection"]["mechanism"] == "demo.intro.v1"
