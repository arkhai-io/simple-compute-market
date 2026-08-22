"""Exact-selection acceptance dispatches obligations through the registry."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from core_storefront.models.negotiation_models import NegotiateNewRequest
from market_core.schemas import derive_settlement_option_id
from market_identity import Eip191Signer
from market_settlement_runtime import (
    AcceptedObligationArtifacts,
    MechanismRegistration,
    MechanismReadiness,
    SettlementConfig,
    SettlementConfigurationRegistry,
)
from pydantic import BaseModel, ConfigDict

from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.negotiation_service import (
    BareMetalNegotiationService,
    NegotiationRequestError,
)
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from market_hosted_settlement import StripeSettlementConfig

BUYER_SIGNER = Eip191Signer(bytes.fromhex("22" * 32))
SELLER_SIGNER = Eip191Signer(bytes.fromhex("11" * 32))

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
        "claimant_principal": SELLER_SIGNER.identity.model_dump(mode="json"),
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


async def _service(tmp_path) -> tuple[BareMetalNegotiationService, dict[str, Any]]:
    domain = get_market_domain_contract()
    db = SQLiteClient(str(tmp_path / "storefront.db"), domain=domain)
    option = _intro_option()
    await db.upsert_bare_metal_listing(
        listing_id="intro-listing",
        status="open",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        seller_principal=SELLER_SIGNER.identity,
        storefront_url="http://seller:8000",
        site_id="site-a",
        pool_id="pool-a",
        physical_resource_id="resource-1",
        listing={
            "kind": "bare_metal.v1",
            "machine_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
        settlement_options=[option],
    )
    service = BareMetalNegotiationService(
        db=db,
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        round_hook=None,  # type: ignore[arg-type]
        build_plan=lambda **kwargs: {},
        accepted_obligation_dispatch=_intro_dispatch(),
    )
    return service, option


def _request(option: dict[str, Any], *, fields: dict[str, Any] | None = None):
    return NegotiateNewRequest(
        listing_id="intro-listing",
        buyer_principal=BUYER_SIGNER.identity,
        buyer_agent_url="https://buyer.example",
        provision_terms={
            "kind": "bare_metal.v1",
            "version": 1,
            "payload": {"duration_seconds": 3600, "access_method": "none"},
        },
        proposal={
            "settlement_selection": {
                "mechanism": option["mechanism"],
                "option_id": option["option_id"],
                "expiration_unix": 1_900_000_000,
            },
            "fields": fields or {},
        },
    )


async def test_non_scalar_selection_accepts_without_provisioning_inputs(
    tmp_path,
) -> None:
    service, option = await _service(tmp_path)
    response = await service.open(
        request=_request(option),
        buyer_principal=BUYER_SIGNER.identity,
    )
    assert response.action == "accept"
    assert response.proposal["fields"] == {}
    plan = response.settlement_plan
    assert plan is not None
    assert plan.obligations[0].amount is None
    assert plan.obligations[0].mechanism == INTRO_MECHANISM
    assert plan.service_terms[INTRO_MECHANISM]["channel"] == "telegram"
    assert plan.service_terms[INTRO_MECHANISM]["listing_id"] == "intro-listing"
    thread = await service.db.load_negotiation_thread_row(
        negotiation_id=response.negotiation_id
    )
    assert thread is not None and thread.get("settlement_plan") is not None


async def test_selection_with_uncomposed_mechanism_is_rejected(tmp_path) -> None:
    service, option = await _service(tmp_path)
    tampered = dict(option, mechanism="unknown.v1")
    with pytest.raises(NegotiationRequestError, match="unsupported mechanism"):
        await service.open(
            request=_request(tampered),
            buyer_principal=BUYER_SIGNER.identity,
        )


async def test_non_scalar_selection_rejects_a_proposed_amount(tmp_path) -> None:
    service, option = await _service(tmp_path)
    with pytest.raises(
        NegotiationRequestError, match="does not negotiate a settlement amount"
    ):
        await service.open(
            request=_request(option, fields={"amount": "100"}),
            buyer_principal=BUYER_SIGNER.identity,
        )


async def test_selection_must_exact_match_one_listing_option(tmp_path) -> None:
    service, option = await _service(tmp_path)
    tampered = dict(option, option_id="ee" * 32)
    with pytest.raises(NegotiationRequestError, match="does not exact-match"):
        await service.open(
            request=_request(tampered),
            buyer_principal=BUYER_SIGNER.identity,
        )


def test_composition_dispatch_exposes_only_priority_builders() -> None:
    composition = BareMetalStorefrontSettlementComposition(
        registry=SettlementConfigurationRegistry(
            (_intro_registration(),)
        ),
        config=SettlementConfig(
            priority=(INTRO_MECHANISM,),
            mechanisms={"demo_intro": DemoIntroConfig(enabled=True)},
        ),
    )
    dispatch = composition.accepted_obligation_dispatch()
    assert set(dispatch) == {INTRO_MECHANISM}


def test_composition_dispatch_includes_the_hosted_builder() -> None:
    composition = BareMetalStorefrontSettlementComposition.from_raw_config(
        {
            "priority": ["fiat.stripe.v1"],
            "stripe": StripeSettlementConfig(enabled=True).model_dump(
                mode="json", exclude_none=True, exclude_defaults=True
            )
            | {"enabled": True},
        }
    )
    dispatch = composition.accepted_obligation_dispatch()
    assert set(dispatch) == {"fiat.stripe.v1"}
