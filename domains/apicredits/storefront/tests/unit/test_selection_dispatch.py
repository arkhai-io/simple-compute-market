"""Exact-selection acceptance dispatches obligations through the registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from apicredits_storefront.domain_runtime import get_market_domain_contract
from apicredits_storefront.negotiation_runtime import (
    _accepted_selection_artifacts,
    _decode_terms,
)
from market_core.schemas import (
    ProvisionTerms,
    SettlementPlan,
    derive_settlement_option_id,
)
from market_identity import Ed25519Signer
from market_negotiation_runtime import OfferUnfulfillableError
from market_settlement_runtime import (
    AcceptedObligationArtifacts,
    MechanismReadiness,
    MechanismRegistration,
    SettlementConfig,
    SettlementConfigurationRegistry,
)
from pydantic import BaseModel, ConfigDict

_BUYER = Ed25519Signer(bytes.fromhex("11" * 32)).identity
_SELLER = Ed25519Signer(bytes.fromhex("22" * 32)).identity
_DOMAIN = get_market_domain_contract()

INTRO_MECHANISM = "demo.intro.v1"


class DemoIntroConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False


def _intro_registration() -> MechanismRegistration:
    def preflight(section: BaseModel, resources: Mapping[str, Any], role: str):
        return MechanismReadiness(
            mechanism=INTRO_MECHANISM,
            configured=True,
            enabled=True,
            ready=True,
        )

    def build_obligation(
        section: BaseModel, option: Any, context: Mapping[str, Any]
    ) -> AcceptedObligationArtifacts:
        raw = option if isinstance(option, Mapping) else option.model_dump()
        params = dict(raw["params"])
        return AcceptedObligationArtifacts(
            obligation={
                "payer": "buyer",
                "claimant": "seller",
                "payer_principal": dict(context["buyer_principal"]),
                "claimant_principal": dict(context["seller_principal"]),
                "expiration_unix": int(context["expiration_unix"]),
                "conditions": [],
                "mechanism": INTRO_MECHANISM,
                "params": params,
            },
            amount=None,
            service_terms={
                INTRO_MECHANISM: {
                    "channel": params.get("channel"),
                    "listing_id": context.get("listing_id"),
                }
            },
        )

    return MechanismRegistration(
        mechanism_id=INTRO_MECHANISM,
        config_key="demo_intro",
        config_model=DemoIntroConfig,
        roles=frozenset({"buyer", "seller"}),
        negotiates_scalar_amount=False,
        preflight=preflight,
        client_factory=lambda section, resources, role: object(),
        option_builder=lambda section, readiness, resources, role: {
            "accepted_escrows": [],
            "settlement_options": [],
        },
        buyer_compatibility=lambda section, option, public_context: True,
        accepted_obligation_builder=build_obligation,
        clause_fields=(),
        publication_input_model=DemoIntroConfig,
        publication_input_validator=lambda section, value, role: value,
    )


def _intro_dispatch():
    registry = SettlementConfigurationRegistry((_intro_registration(),))
    config = SettlementConfig(
        priority=(INTRO_MECHANISM,),
        mechanisms={"demo_intro": DemoIntroConfig(enabled=True)},
    )

    def build(option: Mapping[str, Any], context: Mapping[str, Any]):
        return registry.build_accepted_obligation(
            INTRO_MECHANISM, option, config, role="seller", context=context
        )

    return {INTRO_MECHANISM: build}


def _intro_option() -> dict[str, Any]:
    params = {
        "profile": "default",
        "channel": "telegram",
        "terms": "Net-30 prose contract.",
        "claimant_principal": _SELLER.model_dump(mode="json"),
    }
    return {
        "option_id": derive_settlement_option_id(
            mechanism=INTRO_MECHANISM,
            asset="introduction",
            rates=[],
            params=params,
        ),
        "mechanism": INTRO_MECHANISM,
        "asset": "introduction",
        "rates": [],
        "params": params,
    }


def _selection(option: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "mechanism": option["mechanism"],
        "option_id": option["option_id"],
        "expiration_unix": 1_900_000_000,
    }


def _terms(quantity: int = 3):
    return _decode_terms(
        _DOMAIN,
        ProvisionTerms(
            kind="api_credits.v1",
            version=1,
            payload={"quantity": quantity, "key": {"mode": "new"}},
        ),
    ).decoded


def _listing(option: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "listing_id": "L-intro",
        "settlement_options": [dict(option)],
    }


def test_non_scalar_selection_accepts_amountless_with_mechanism_terms() -> None:
    option = _intro_option()
    artifacts = _accepted_selection_artifacts(
        _intro_dispatch(),
        selection=_selection(option),
        option=option,
        agreed_amount=0,
        buyer_principal=_BUYER,
        seller_principal=_SELLER,
        listing=_listing(option),
        provision_terms=_terms(),
    )
    plan = SettlementPlan.model_validate(artifacts["settlement_plan"])
    obligation = plan.obligations[0]
    assert obligation.amount is None
    assert obligation.mechanism == INTRO_MECHANISM
    assert plan.service_terms[INTRO_MECHANISM]["channel"] == "telegram"
    assert plan.service_terms["api_credits.v1"]["quantity"] == 3


def test_non_scalar_selection_rejects_a_proposed_amount() -> None:
    option = _intro_option()
    with pytest.raises(OfferUnfulfillableError, match="not_negotiable"):
        _accepted_selection_artifacts(
            _intro_dispatch(),
            selection=_selection(option),
            option=option,
            agreed_amount=250,
            buyer_principal=_BUYER,
            seller_principal=_SELLER,
            listing=_listing(option),
            provision_terms=_terms(),
        )
