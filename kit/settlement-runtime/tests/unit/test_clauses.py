from __future__ import annotations

from typing import Any

import pytest
from market_core.query_dsl import QuerySyntaxError, QueryValidationError
from market_core.schemas import SettlementOption, derive_settlement_option_id
from market_settlement_runtime import (
    ComparisonOperator,
    FieldDescriptor,
    MechanismReadiness,
    MechanismRegistration,
    MissingValueRule,
    QueryValueType,
    SettlementClauseField,
    SettlementConfig,
    SettlementConfigurationRegistry,
    compile_settlement_clause,
    select_settlement_candidates,
    settlement_clause_matches,
)
from pydantic import BaseModel, ConfigDict


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False


class _PublicationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile: str = ""


def _field(
    name: str,
    projector,
    *,
    on_missing: MissingValueRule = MissingValueRule.FAIL,
) -> SettlementClauseField:
    return SettlementClauseField(
        descriptor=FieldDescriptor(
            name=name,
            value_type=QueryValueType.STRING,
            operators=frozenset(
                {
                    ComparisonOperator.EQUAL,
                    ComparisonOperator.NOT_EQUAL,
                    ComparisonOperator.IN,
                    ComparisonOperator.NOT_IN,
                }
            ),
            on_missing=on_missing,
        ),
        roles=frozenset({"buyer"}),
        projector=projector,
    )


def _registration(
    mechanism: str,
    key: str,
    fields: tuple[SettlementClauseField, ...],
    *,
    compatible: bool = True,
) -> MechanismRegistration:
    return MechanismRegistration(
        mechanism_id=mechanism,
        config_key=key,
        config_model=_Section,
        roles=frozenset({"buyer"}),
        preflight=lambda section, resources, role: MechanismReadiness(
            mechanism=mechanism,
            configured=True,
            enabled=section.enabled,
            ready=section.enabled,
        ),
        client_factory=lambda section, resources, role: object(),
        option_builder=lambda section, readiness, resources, role: (),
        buyer_compatibility=lambda section, option, context: (
            compatible and option.mechanism == mechanism
        ),
        clause_fields=fields,
        publication_input_model=_PublicationInput,
        publication_input_validator=lambda section, value, role: value,
    )


def _registry(*, stripe_compatible: bool = True) -> SettlementConfigurationRegistry:
    return SettlementConfigurationRegistry(
        (
            _registration(
                "fiat.stripe.v1",
                "stripe",
                (
                    _field(
                        "stripe.method",
                        lambda option: option.params.get("methods"),
                    ),
                    _field(
                        "stripe.optional",
                        lambda option: option.params.get("optional"),
                        on_missing=MissingValueRule.PASS,
                    ),
                ),
                compatible=stripe_compatible,
            ),
            _registration(
                "alkahest.v1",
                "alkahest",
                (
                    _field(
                        "alkahest.chain",
                        lambda option: option.params.get("chain"),
                    ),
                ),
            ),
        )
    )


def _config(
    *,
    priority: tuple[str, ...] = ("fiat.stripe.v1", "alkahest.v1"),
) -> SettlementConfig:
    return SettlementConfig(
        priority=priority,
        mechanisms={
            "stripe": _Section(enabled="fiat.stripe.v1" in priority),
            "alkahest": _Section(enabled="alkahest.v1" in priority),
        },
    )


def _option(
    mechanism: str,
    asset: str,
    **params: Any,
) -> SettlementOption:
    option_id = derive_settlement_option_id(
        mechanism=mechanism,
        asset=asset,
        rates=[],
        params=params,
    )
    return SettlementOption(
        option_id=option_id,
        mechanism=mechanism,
        asset=asset,
        params=params,
    )


def test_compilation_normalizes_config_key_and_rejects_unknown_mechanism() -> None:
    registry = _registry()

    compiled = compile_settlement_clause(
        "mechanism=stripe stripe.method=card",
        registry,
    )

    assert compiled.render() == "mechanism=fiat.stripe.v1 stripe.method=card"
    with pytest.raises(QueryValidationError) as caught:
        compile_settlement_clause("mechanism=ghost", registry)
    assert caught.value.code == "unknown_mechanism"


def test_one_clause_never_combines_values_from_different_options() -> None:
    registry = _registry()
    usd_bank = _option("fiat.stripe.v1", "usd", methods=["bank"])
    eur_card = _option("fiat.stripe.v1", "eur", methods=["card"])
    clause = compile_settlement_clause(
        "asset=usd stripe.method=card",
        registry,
    )

    result = select_settlement_candidates(
        (usd_bank, eur_card),
        registry=registry,
        config=_config(priority=("fiat.stripe.v1",)),
        clauses=(clause,),
    )

    assert result.candidates == ()
    assert settlement_clause_matches(clause, usd_bank, registry) is False
    assert settlement_clause_matches(clause, eur_card, registry) is False


def test_first_surviving_clause_precedes_mechanism_priority() -> None:
    registry = _registry()
    stripe = _option("fiat.stripe.v1", "usd", methods=["card"])
    alkahest = _option("alkahest.v1", "usdc", chain="base_sepolia")

    result = select_settlement_candidates(
        (stripe, alkahest),
        registry=registry,
        config=_config(),
        clauses=(
            "mechanism=alkahest alkahest.chain=base_sepolia",
            "mechanism=stripe stripe.method=card",
        ),
    )

    assert result.matched_clause_index == 0
    assert [candidate.option for candidate in result.candidates] == [alkahest]


def test_no_clause_preserves_priority_and_option_id_order() -> None:
    registry = _registry()
    stripe_b = _option("fiat.stripe.v1", "usd", methods=["card"], profile="b")
    stripe_a = _option("fiat.stripe.v1", "usd", methods=["card"], profile="a")
    alkahest = _option("alkahest.v1", "usdc", chain="base_sepolia")

    result = select_settlement_candidates(
        (alkahest, stripe_b, stripe_a),
        registry=registry,
        config=_config(),
    )

    assert result.matched_clause_index is None
    assert [candidate.option.option_id for candidate in result.candidates] == [
        *sorted((stripe_a.option_id, stripe_b.option_id)),
        alkahest.option_id,
    ]


def test_missing_projection_rule_and_mechanism_qualification_are_enforced() -> None:
    registry = _registry()
    stripe = _option("fiat.stripe.v1", "usd", methods=["card"])
    alkahest = _option("alkahest.v1", "usdc", chain="base_sepolia")

    optional = compile_settlement_clause("stripe.optional=anything", registry)
    required = compile_settlement_clause("stripe.method=card", registry)

    assert settlement_clause_matches(optional, stripe, registry) is True
    assert settlement_clause_matches(optional, alkahest, registry) is False
    assert settlement_clause_matches(required, alkahest, registry) is False


def test_incompatible_and_disabled_options_are_removed_before_clauses() -> None:
    stripe = _option("fiat.stripe.v1", "usd", methods=["card"])
    alkahest = _option("alkahest.v1", "usdc", chain="base_sepolia")

    incompatible = select_settlement_candidates(
        (stripe, alkahest),
        registry=_registry(stripe_compatible=False),
        config=_config(),
        clauses=("asset in [usd,usdc]",),
    )
    disabled = select_settlement_candidates(
        (stripe, alkahest),
        registry=_registry(),
        config=_config(priority=("alkahest.v1",)),
        clauses=("asset in [usd,usdc]",),
    )

    assert [item.option for item in incompatible.candidates] == [alkahest]
    assert [item.option for item in disabled.candidates] == [alkahest]


def test_empty_clause_is_rejected_instead_of_matching_everything() -> None:
    with pytest.raises(QuerySyntaxError) as caught:
        compile_settlement_clause("", _registry())
    assert caught.value.code == "empty_query"
