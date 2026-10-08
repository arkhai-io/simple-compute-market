"""Exact-selection acceptance dispatches obligations through the registry."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping
from typing import Any

import pytest
from arkhai_bare_metal.fixtures.listing import LISTING_HARDWARE
from arkhai_bare_metal_storefront.domain_runtime import get_market_domain_contract
from arkhai_bare_metal_storefront.listing_source_check import build_listing_source_check
from arkhai_bare_metal_storefront.negotiation import default_seller_round_hook
from arkhai_bare_metal_storefront.negotiation_runtime import (
    BareMetalNegotiationRefusal,
    build_bare_metal_negotiation_runtime,
)
from arkhai_bare_metal_storefront.settlement_composition import (
    BareMetalStorefrontSettlementComposition,
)
from arkhai_bare_metal_storefront.sqlite_client import SQLiteClient
from core_storefront.models.negotiation_models import (
    NegotiateNewRequest,
    NegotiateNewResponse,
)
from market_core.schemas import RateValue, SettlementOption, derive_settlement_option_id
from market_identity import Eip191Signer
from market_settlement_runtime import (
    AcceptedObligationArtifacts,
    MechanismReadiness,
    MechanismRegistration,
    SettlementConfig,
    SettlementConfigurationRegistry,
)
from market_storefront_kit import TradingPause
from pydantic import BaseModel, ConfigDict

from source_sites import SourceSites

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


class _Opening:
    """Opens a negotiation through the bare-metal runtime, as ``negotiate/new`` does."""

    def __init__(self, db: SQLiteClient, runtime: Any) -> None:
        self.db = db
        self._runtime = runtime

    async def open(
        self, *, request: NegotiateNewRequest, buyer_principal: Any
    ) -> NegotiateNewResponse:
        result = await self._runtime.start(
            repository=self.db,
            listing_id=request.listing_id,
            buyer_principal=buyer_principal,
            seller_principal=SELLER_SIGNER.identity,
            actor_principal=buyer_principal,
            proposal=request.proposal,
            terms=request.provision_terms,
            seller_agent_url="http://seller:8000",
            buyer_agent_url=request.buyer_agent_url,
        )
        return NegotiateNewResponse(**result)


async def _service(tmp_path) -> tuple[_Opening, dict[str, Any]]:
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
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
        settlement_options=[option],
    )
    runtime = build_bare_metal_negotiation_runtime(
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        round_hook=default_seller_round_hook(),
        listing_source_check=build_listing_source_check(db, SourceSites().site),
        trading_pause=TradingPause(),
        plan_builder=lambda **kwargs: {},
        accepted_obligation_dispatch=_intro_dispatch(),
        mechanism_fulfillment={INTRO_MECHANISM: False},
    )
    return _Opening(db, runtime), option


def _request(
    option: dict[str, Any],
    *,
    fields: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
):
    return NegotiateNewRequest(
        listing_id="intro-listing",
        buyer_principal=BUYER_SIGNER.identity,
        buyer_agent_url="https://buyer.example",
        provision_terms={
            "kind": "bare_metal.v2",
            "version": 1,
            "payload": payload or {"duration_seconds": 3600, "access_method": "none"},
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
    with pytest.raises(BareMetalNegotiationRefusal, match="unsupported mechanism"):
        await service.open(
            request=_request(tampered),
            buyer_principal=BUYER_SIGNER.identity,
        )


async def test_non_scalar_selection_rejects_a_proposed_amount(tmp_path) -> None:
    service, option = await _service(tmp_path)
    with pytest.raises(
        BareMetalNegotiationRefusal, match="does not negotiate a settlement amount"
    ):
        await service.open(
            request=_request(option, fields={"amount": "100"}),
            buyer_principal=BUYER_SIGNER.identity,
        )


async def test_selection_must_exact_match_one_listing_option(tmp_path) -> None:
    service, option = await _service(tmp_path)
    tampered = dict(option, option_id="ee" * 32)
    with pytest.raises(BareMetalNegotiationRefusal, match="does not exact-match"):
        await service.open(
            request=_request(tampered),
            buyer_principal=BUYER_SIGNER.identity,
        )


def test_composition_dispatch_exposes_only_priority_builders() -> None:
    composition = BareMetalStorefrontSettlementComposition(
        registry=SettlementConfigurationRegistry((_intro_registration(),)),
        config=SettlementConfig(
            priority=(INTRO_MECHANISM,),
            mechanisms={"demo_intro": DemoIntroConfig(enabled=True)},
        ),
    )
    dispatch = composition.accepted_obligation_dispatch()
    assert set(dispatch) == {INTRO_MECHANISM}


PAYMENT_MECHANISM = "demo.payment.v1"


def _payment_option() -> dict[str, Any]:
    rates = [RateValue(field="amount", per="hour", value=100)]
    return SettlementOption(
        option_id=derive_settlement_option_id(
            mechanism=PAYMENT_MECHANISM, asset="usd", rates=rates, params={}
        ),
        mechanism=PAYMENT_MECHANISM,
        asset="usd",
        rates=rates,
        params={},
    ).model_dump(mode="json")


async def _payment_service(tmp_path, settlement_data_calls: list) -> tuple[_Opening, dict[str, Any]]:
    """A listing offering one mechanism that settles from the Agreement alone."""
    domain = get_market_domain_contract()
    db = SQLiteClient(str(tmp_path / "storefront.db"), domain=domain)
    option = _payment_option()
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
            "capacity_backing": "backed",
            **LISTING_HARDWARE,
            "kind": "bare_metal.v2",
            "host_id": "machine-1",
            "physical_host_id": "physical-host-1",
            "access_methods": ["ssh"],
        },
        accepted_escrows=[],
        settlement_options=[option],
    )

    def settlement_data(agreement: dict[str, Any]) -> dict[str, Any]:
        settlement_data_calls.append(agreement)
        return {"negotiation_id": agreement["negotiation_id"], "amount": agreement["amount"]}

    runtime = build_bare_metal_negotiation_runtime(
        domain=domain,
        seller_principal=SELLER_SIGNER.identity,
        round_hook=default_seller_round_hook(),
        listing_source_check=build_listing_source_check(db, SourceSites().site),
        trading_pause=TradingPause(),
        plan_builder=lambda **kwargs: {},
        # Composed with no obligation builder: it settles from the Agreement.
        accepted_obligation_dispatch={PAYMENT_MECHANISM: None},
        settlement_data_dispatch={PAYMENT_MECHANISM: settlement_data},
        mechanism_fulfillment={PAYMENT_MECHANISM: True},
    )
    return _Opening(db, runtime), option


async def test_agreement_only_selection_is_accepted_with_its_agreement(tmp_path) -> None:
    calls: list = []
    service, option = await _payment_service(tmp_path, calls)
    # The deal provisions the listed machine, so it asks for SSH access.
    request = _request(
        option,
        payload={
            "duration_seconds": 3600,
            "access_method": "ssh",
            "ssh_public_key": "ssh-ed25519 buyer",
        },
    )
    response = await service.open(request=request, buyer_principal=BUYER_SIGNER.identity)

    assert response.action == "accept"
    assert response.settlement_plan is None
    # One hour at the option's hourly rate.
    assert response.proposal["fields"] == {"amount": "100"}
    agreement_bytes = base64.b64decode(response.agreement_bytes)
    agreement = json.loads(agreement_bytes)
    assert agreement["negotiation_id"] == response.negotiation_id
    assert agreement["settlement"]["mechanism"] == PAYMENT_MECHANISM
    # Settlement data is derived from the exact Agreement bytes both parties keep.
    assert calls == [agreement]
    assert response.settlement_data == {
        "negotiation_id": response.negotiation_id,
        "amount": agreement["amount"],
    }

    thread = await service.db.load_negotiation_thread_row(
        negotiation_id=response.negotiation_id
    )
    assert thread["agreement_bytes"] == agreement_bytes
    assert thread["settlement_data"] == response.settlement_data
    record = await service.db.load_bare_metal_settlement_record(
        negotiation_id=response.negotiation_id
    )
    assert record["mechanism"] == PAYMENT_MECHANISM
    assert record["agreement_sha256"] == hashlib.sha256(agreement_bytes).hexdigest()
    assert record["status"] == "accepted"
    # The same terms an escrow deal records: the listed host, as the buyer asked.
    terms = await service.db.load_bare_metal_terms(negotiation_id=response.negotiation_id)
    assert terms.host_id == "machine-1"
    assert terms.ssh_public_key == "ssh-ed25519 buyer"


async def test_a_provisioning_selection_is_held_to_the_listing_admission_rules(tmp_path) -> None:
    service, option = await _payment_service(tmp_path, [])
    with pytest.raises(BareMetalNegotiationRefusal, match="bare_metal_access_method"):
        await service.open(request=_request(option), buyer_principal=BUYER_SIGNER.identity)
