"""The introduction mechanism builds its own non-financial accepted obligation."""

from __future__ import annotations

from typing import Any

import pytest
from market_contact_exchange import (
    INTRODUCTION_ASSET,
    MECHANISM,
    ContactSettlementConfig,
    create_contact_exchange_registration,
)
from market_core.schemas import derive_settlement_option_id
from market_settlement_runtime import (
    SettlementConfig,
    SettlementConfigurationRegistry,
)

_BUYER = {"scheme": "ed25519", "identifier": "buyer-signing-key"}
_SELLER = {"scheme": "ed25519", "identifier": "seller-signing-key"}


def _option(**param_overrides: Any) -> dict[str, Any]:
    params: dict[str, Any] = {
        "profile": "default",
        "channel": "telegram",
        "terms": "Net-30, prose contract on request.",
        "claimant_principal": dict(_SELLER),
    }
    params.update(param_overrides)
    return {
        "option_id": derive_settlement_option_id(
            mechanism=MECHANISM,
            asset=INTRODUCTION_ASSET,
            rates=[],
            params=params,
        ),
        "mechanism": MECHANISM,
        "asset": INTRODUCTION_ASSET,
        "rates": [],
        "params": params,
    }


def _registry_config(
    contact_payload: dict[str, str] | None = None,
) -> tuple[SettlementConfigurationRegistry, SettlementConfig]:
    registry = SettlementConfigurationRegistry(
        (create_contact_exchange_registration(),)
    )
    section = ContactSettlementConfig.model_validate(
        {
            "enabled": True,
            "contact_payload": contact_payload
            or {"telegram": "@capacity_broker"},
            "profiles": {
                "default": {"channel": "telegram", "terms": "prose terms"}
            },
        }
    )
    return registry, SettlementConfig(
        priority=(MECHANISM,), mechanisms={"contact": section}
    )


def _context(**overrides: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "buyer_principal": dict(_BUYER),
        "seller_principal": dict(_SELLER),
        "expiration_unix": 1_900_000_000,
    }
    context.update(overrides)
    return context


def test_builder_produces_the_amountless_introduction_obligation() -> None:
    registry, config = _registry_config()
    built = registry.build_accepted_obligation(
        MECHANISM,
        _option(),
        config,
        role="seller",
        context=_context(
            listing_id="listing-1",
            negotiated_context={"note": "call after 6pm UTC"},
        ),
    )
    assert built.amount is None
    obligation = built.obligation
    assert "amount" not in obligation
    assert "asset" not in obligation
    assert obligation["payer_principal"] == _BUYER
    assert obligation["claimant_principal"] == _SELLER
    assert obligation["conditions"] == []
    assert obligation["params"]["channel"] == "telegram"
    package = built.service_terms[MECHANISM]
    assert package["channel"] == "telegram"
    assert package["listing_id"] == "listing-1"
    assert package["negotiated_context"] == {"note": "call after 6pm UTC"}
    assert "@capacity_broker" not in str(built.service_terms)


def test_builder_rejects_a_claimant_that_is_not_the_seller() -> None:
    registry, config = _registry_config()
    with pytest.raises(ValueError, match="claimant does not match"):
        registry.build_accepted_obligation(
            MECHANISM,
            _option(claimant_principal=dict(_BUYER)),
            config,
            role="seller",
            context=_context(),
        )


def test_builder_requires_an_expiration() -> None:
    registry, config = _registry_config()
    with pytest.raises(ValueError, match="requires an expiration"):
        registry.build_accepted_obligation(
            MECHANISM,
            _option(),
            config,
            role="seller",
            context=_context(expiration_unix=0),
        )


def test_builder_refuses_contact_leaked_into_the_obligation() -> None:
    registry, config = _registry_config(
        contact_payload={"telegram": "seller-signing-key"}
    )
    with pytest.raises(ValueError, match="must not reach an accepted obligation"):
        registry.build_accepted_obligation(
            MECHANISM, _option(), config, role="seller", context=_context()
        )
