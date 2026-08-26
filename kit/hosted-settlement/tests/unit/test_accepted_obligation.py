"""The hosted mechanism rebuilds the canonical accepted obligation itself."""

from __future__ import annotations

from typing import Any

import pytest
from market_core.schemas import RateValue, derive_settlement_option_id
from market_settlement_runtime import (
    SettlementConfig,
    SettlementConfigurationRegistry,
)

from market_hosted_settlement import (
    MECHANISM,
    create_stripe_registration,
    default_hosted_selection_dispatch,
)

from test_settlement_config import _condition, _config, _identity

_BUYER = _identity(1).model_dump(mode="json")
_SELLER = _identity(2).model_dump(mode="json")


def _option(**param_overrides: Any) -> dict[str, Any]:
    params = {
        "authority_id": "authority-main",
        "account_ref": "seller-main",
        "country": "US",
        "environment": "production",
        "claimant_principal": dict(_SELLER),
        "funds_flow": "separate_charges_transfers",
        "funding_profile": "card.v1",
        "interaction": "interactive",
        "contract_fingerprint": "sha256:" + "ab" * 32,
        "condition": _condition(),
        "bare_metal": {"site_id": "site-1"},
    }
    params.update(param_overrides)
    params = {key: value for key, value in params.items() if value is not None}
    rates = [{"field": "amount", "per": "hour", "value": "125"}]
    return {
        "option_id": derive_settlement_option_id(
            mechanism=MECHANISM,
            asset="usd",
            rates=[RateValue.model_validate(rate) for rate in rates],
            params=params,
        ),
        "mechanism": MECHANISM,
        "asset": "usd",
        "rates": rates,
        "params": params,
    }


def _context(**overrides: Any) -> dict[str, Any]:
    context = {
        "buyer_principal": dict(_BUYER),
        "seller_principal": dict(_SELLER),
        "expiration_unix": 1_900_000_000,
        "duration_seconds": 7200,
        "domain_param_keys": ("bare_metal",),
    }
    context.update(overrides)
    return context


def _registry_config() -> tuple[SettlementConfigurationRegistry, SettlementConfig]:
    registry = SettlementConfigurationRegistry((create_stripe_registration(),))
    config = SettlementConfig(
        priority=(MECHANISM,),
        mechanisms={"stripe": _config()},
    )
    return registry, config


def test_builder_rebuilds_the_duration_scaled_obligation() -> None:
    registry, config = _registry_config()
    built = registry.build_accepted_obligation(
        MECHANISM,
        _option(),
        config,
        role="seller",
        context=_context(),
    )
    assert built.amount == 250
    obligation = built.obligation
    assert obligation["amount"] == 250
    assert obligation["payer_principal"] == _BUYER
    assert obligation["claimant_principal"] == _SELLER
    assert obligation["conditions"] == [obligation["params"]["condition"]]
    assert obligation["conditions"][0]["condition_id"] == "vm-fulfillment"
    assert obligation["mechanism"] == MECHANISM
    assert "bare_metal" not in obligation["params"]
    assert "funding_authorization_ref" not in obligation["params"]


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


def test_builder_rejects_pre_authorized_funding() -> None:
    registry, config = _registry_config()
    with pytest.raises(ValueError, match="pre-authorize"):
        registry.build_accepted_obligation(
            MECHANISM,
            _option(funding_authorization_ref="sneaky"),
            config,
            role="seller",
            context=_context(),
        )


def _counted_option(**param_overrides: Any) -> dict[str, Any]:
    option = _option(bare_metal=None, **param_overrides)
    rates = [{"field": "amount", "per": "credit", "value": "100"}]
    option["rates"] = rates
    option["option_id"] = derive_settlement_option_id(
        mechanism=MECHANISM,
        asset="usd",
        rates=[RateValue.model_validate(rate) for rate in rates],
        params=option["params"],
    )
    return option


def test_builder_scales_a_counted_rate_by_unit_quantity() -> None:
    registry, config = _registry_config()
    built = registry.build_accepted_obligation(
        MECHANISM,
        _counted_option(),
        config,
        role="seller",
        context=_context(duration_seconds=0, unit_quantity=7, domain_param_keys=()),
    )
    assert built.amount == 700
    assert built.obligation["amount"] == 700


def test_builder_requires_a_unit_quantity_for_counted_rates() -> None:
    registry, config = _registry_config()
    for bad_quantity in (None, 0, -3, True, "7"):
        with pytest.raises(ValueError, match="unit quantity"):
            registry.build_accepted_obligation(
                MECHANISM,
                _counted_option(),
                config,
                role="seller",
                context=_context(
                    unit_quantity=bad_quantity, domain_param_keys=()
                ),
            )


def test_time_rates_scale_by_duration_even_with_a_quantity_present() -> None:
    registry, config = _registry_config()
    built = registry.build_accepted_obligation(
        MECHANISM,
        _option(),
        config,
        role="seller",
        context=_context(unit_quantity=9),
    )
    assert built.amount == 250


def test_default_dispatch_builds_through_the_kit_registration() -> None:
    dispatch = default_hosted_selection_dispatch()
    assert set(dispatch) == {MECHANISM}
    built = dispatch[MECHANISM](_option(), _context())
    assert built.amount == 250
    assert built.obligation["mechanism"] == MECHANISM


def test_builder_requires_positive_duration_and_expiration() -> None:
    registry, config = _registry_config()
    with pytest.raises(ValueError, match="positive duration"):
        registry.build_accepted_obligation(
            MECHANISM,
            _option(),
            config,
            role="seller",
            context=_context(duration_seconds=0),
        )
    with pytest.raises(ValueError, match="requires an expiration"):
        registry.build_accepted_obligation(
            MECHANISM,
            _option(),
            config,
            role="seller",
            context=_context(expiration_unix=0),
        )
