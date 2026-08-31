"""Registry dispatch for mechanism-owned accepted-obligation construction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

import pytest
from pydantic import BaseModel

from market_settlement_runtime import (
    AcceptedObligationArtifacts,
    SettlementConfig,
    SettlementConfigurationError,
    SettlementConfigurationRegistry,
)

from test_configuration import DemoSettings, _registration


def _config() -> SettlementConfig:
    return SettlementConfig(
        priority=("demo.pay.v1",),
        mechanisms={"demo": DemoSettings(enabled=True)},
    )


def _builder(amount: int | None, mechanism: str = "demo.pay.v1"):
    def build(
        section: BaseModel, option: Any, context: Mapping[str, Any]
    ) -> AcceptedObligationArtifacts:
        return AcceptedObligationArtifacts(
            obligation={
                "payer": "buyer",
                "claimant": "seller",
                "mechanism": mechanism,
                "params": dict(context.get("params", {})),
            },
            amount=amount,
        )

    return build


def test_registration_without_the_hook_cannot_build() -> None:
    registry = SettlementConfigurationRegistry((_registration(),))
    with pytest.raises(SettlementConfigurationError, match="does not build"):
        registry.build_accepted_obligation(
            "demo.pay.v1", {}, _config(), role="seller"
        )


def test_scalar_mechanism_builds_an_obligation_with_an_amount() -> None:
    registration = replace(
        _registration(), accepted_obligation_builder=_builder(42)
    )
    registry = SettlementConfigurationRegistry((registration,))
    built = registry.build_accepted_obligation(
        "demo.pay.v1",
        {},
        _config(),
        role="seller",
        context={"params": {"kind": "hosted"}},
    )
    assert built.amount == 42
    assert built.obligation["params"] == {"kind": "hosted"}


def test_scalar_mechanism_must_produce_an_amount() -> None:
    registration = replace(
        _registration(), accepted_obligation_builder=_builder(None)
    )
    registry = SettlementConfigurationRegistry((registration,))
    with pytest.raises(SettlementConfigurationError, match="without an amount"):
        registry.build_accepted_obligation("demo.pay.v1", {}, _config(), role="seller")


def test_non_scalar_mechanism_must_not_produce_an_amount() -> None:
    registration = replace(
        _registration(),
        negotiates_scalar_amount=False,
        accepted_obligation_builder=_builder(42),
    )
    registry = SettlementConfigurationRegistry((registration,))
    with pytest.raises(SettlementConfigurationError, match="declines scalar"):
        registry.build_accepted_obligation("demo.pay.v1", {}, _config(), role="seller")


def test_non_scalar_mechanism_builds_an_amountless_obligation() -> None:
    registration = replace(
        _registration(),
        negotiates_scalar_amount=False,
        accepted_obligation_builder=_builder(None),
    )
    registry = SettlementConfigurationRegistry((registration,))
    built = registry.build_accepted_obligation(
        "demo.pay.v1", {}, _config(), role="seller"
    )
    assert built.amount is None


def test_mechanism_service_terms_must_use_the_mechanism_namespace() -> None:
    def build(
        section: BaseModel, option: Any, context: Mapping[str, Any]
    ) -> AcceptedObligationArtifacts:
        return AcceptedObligationArtifacts(
            obligation={"mechanism": "demo.pay.v1"},
            amount=1,
            service_terms={"bare_metal.v1": {"stolen": True}},
        )

    registration = replace(_registration(), accepted_obligation_builder=build)
    registry = SettlementConfigurationRegistry((registration,))
    with pytest.raises(SettlementConfigurationError, match="foreign"):
        registry.build_accepted_obligation("demo.pay.v1", {}, _config(), role="seller")


def test_built_obligation_must_carry_the_dispatching_mechanism() -> None:
    registration = replace(
        _registration(),
        accepted_obligation_builder=_builder(42, mechanism="other.v1"),
    )
    registry = SettlementConfigurationRegistry((registration,))
    with pytest.raises(SettlementConfigurationError, match="different mechanism"):
        registry.build_accepted_obligation("demo.pay.v1", {}, _config(), role="seller")
