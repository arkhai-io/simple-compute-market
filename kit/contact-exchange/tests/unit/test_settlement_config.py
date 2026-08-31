from __future__ import annotations

from typing import Any

import pytest
from market_contact_exchange import (
    ContactExchangeClient,
    ContactSettlementConfig,
    contact_buyer_compatibility,
    create_contact_exchange_registration,
)
from market_core.schemas import SettlementOption
from market_settlement_runtime import (
    SettlementConfigurationError,
    SettlementConfigurationRegistry,
)

_CLAIMANT = {"scheme": "ed25519", "identifier": "seller-signing-key"}


def _seller_raw(**overrides: Any) -> dict[str, Any]:
    section: dict[str, Any] = {
        "enabled": True,
        "contact_payload": {"telegram": "@capacity_broker", "email": "deals@x.example"},
        "profiles": {
            "default": {
                "channel": "telegram",
                "terms": "Net-30, minimum 8 GPUs, prose contract on request.",
            }
        },
    }
    section.update(overrides)
    return {"priority": ["contact-exchange.v1"], "contact": section}


def _registry() -> SettlementConfigurationRegistry:
    return SettlementConfigurationRegistry((create_contact_exchange_registration(),))


def test_registration_declines_scalar_negotiation() -> None:
    assert create_contact_exchange_registration().negotiates_scalar_amount is False


async def test_seller_readiness_reports_channels_only() -> None:
    registry = _registry()
    config = registry.resolve(_seller_raw(), role="seller")
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    assert readiness.ready
    assert readiness.public_details == {"channels": ["telegram"]}
    assert "@capacity_broker" not in str(readiness.safe_projection())


async def test_seller_readiness_blocks_without_payload_or_profiles() -> None:
    registry = _registry()
    config = registry.resolve(
        _seller_raw(contact_payload={}, profiles={}),
        role="seller",
    )
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    assert not readiness.ready
    assert {blocker.code for blocker in readiness.blockers} == {
        "no_contact_profiles",
        "no_contact_payload",
    }


async def test_option_builder_produces_one_canonical_rateless_option() -> None:
    registry = _registry()
    config = registry.resolve(_seller_raw(), role="seller")
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    built = registry.build_option(
        readiness,
        config,
        role="seller",
        resources={
            "publication_clause": {
                "mechanism": "contact-exchange.v1",
                "asset": "introduction",
                "mechanism_input": {"profile": "default"},
            },
            "claimant_principal": _CLAIMANT,
        },
    )
    assert built["accepted_escrows"] == []
    option = SettlementOption.model_validate(built["settlement_options"][0])
    assert option.rates == []
    assert option.params["channel"] == "telegram"
    assert option.params["claimant_principal"] == _CLAIMANT
    assert "@capacity_broker" not in str(built)


async def test_option_builder_rejects_scalar_rate_clauses() -> None:
    registry = _registry()
    config = registry.resolve(_seller_raw(), role="seller")
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    with pytest.raises(ValueError, match="declines scalar"):
        registry.build_option(
            readiness,
            config,
            role="seller",
            resources={
                "publication_clause": {
                    "mechanism": "contact-exchange.v1",
                    "asset": "introduction",
                    "rate": "100",
                    "per": "hour",
                    "mechanism_input": {"profile": "default"},
                },
                "claimant_principal": _CLAIMANT,
            },
        )


async def test_option_builder_refuses_leaking_contact_into_the_option() -> None:
    registry = _registry()
    config = registry.resolve(
        _seller_raw(contact_payload={"telegram": "seller-signing-key"}),
        role="seller",
    )
    (readiness,) = await registry.ordered_readiness(config, role="seller")
    with pytest.raises(ValueError, match="must not reach a published option"):
        registry.build_option(
            readiness,
            config,
            role="seller",
            resources={
                "publication_clause": {
                    "mechanism": "contact-exchange.v1",
                    "asset": "introduction",
                    "mechanism_input": {"profile": "default"},
                },
                "claimant_principal": _CLAIMANT,
            },
        )


def test_config_rejects_contact_leaked_into_published_profiles() -> None:
    with pytest.raises(ValueError, match="must not appear in published profiles"):
        ContactSettlementConfig.model_validate(
            {
                "enabled": True,
                "contact_payload": {"telegram": "@capacity_broker"},
                "profiles": {
                    "default": {
                        "channel": "telegram",
                        "terms": "Reach me at @capacity_broker anytime.",
                    }
                },
            }
        )


def test_publication_input_rejects_unoffered_profiles() -> None:
    registry = _registry()
    config = registry.resolve(_seller_raw(), role="seller")
    with pytest.raises(SettlementConfigurationError, match="invalid publication input"):
        registry.validate_publication_input(
            "contact-exchange.v1",
            {"profile": "unlisted"},
            config,
            role="seller",
        )


def test_buyer_compatibility_requires_a_rateless_introduction_option() -> None:
    section = ContactSettlementConfig.model_validate({"enabled": True})
    option = {
        "mechanism": "contact-exchange.v1",
        "asset": "introduction",
        "rates": [],
        "params": {},
    }
    assert contact_buyer_compatibility(section, option, {})
    assert not contact_buyer_compatibility(
        section,
        {**option, "rates": [{"field": "amount", "per": "hour", "value": "1"}]},
        {},
    )
    disabled = ContactSettlementConfig.model_validate({"enabled": False})
    assert not contact_buyer_compatibility(disabled, option, {})


def test_buyer_role_resolves_a_minimal_enabled_section() -> None:
    registry = _registry()
    config = registry.resolve(
        {"priority": ["contact-exchange.v1"], "contact": {"enabled": True}},
        role="buyer",
    )
    clients = registry.runtime_clients(config, role="buyer")
    assert isinstance(clients["contact-exchange.v1"], ContactExchangeClient)
