from __future__ import annotations

from typing import Any

import pytest
from market_core.query_dsl import QuerySyntaxError
from market_core.schemas import SettlementOption, derive_settlement_option_id
from market_settlement_runtime import (
    ComparisonOperator,
    FieldDescriptor,
    MechanismReadiness,
    MechanismRegistration,
    MissingValueRule,
    QueryValueType,
    SettlementClauseField,
    SettlementConfigurationRegistry,
    compile_settlement_clause,
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


def _registry(*, example_compatible: bool = True) -> SettlementConfigurationRegistry:
    return SettlementConfigurationRegistry(
        (
            _registration(
                "example.payment.v1",
                "example",
                (
                    _field(
                        "example.method",
                        lambda option: option.params.get("methods"),
                    ),
                    _field(
                        "example.optional",
                        lambda option: option.params.get("optional"),
                        on_missing=MissingValueRule.PASS,
                    ),
                ),
                compatible=example_compatible,
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


def test_empty_clause_is_rejected_instead_of_matching_everything() -> None:
    with pytest.raises(QuerySyntaxError) as caught:
        compile_settlement_clause("", _registry())
    assert caught.value.code == "empty_query"
