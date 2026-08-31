"""Typed settlement-clause compilation and same-option evaluation."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from market_core.query_dsl import (
    ComparisonOperator,
    FieldDescriptor,
    MissingValueRule,
    QueryValidationError,
    QueryValueType,
    ScalarValue,
    ValidatedComparison,
    ValidatedQuery,
    compile_query,
)
from market_core.schemas import SettlementOption

from .configuration import (
    MechanismRegistration,
    RegisteredSettlementClauseField,
    SettlementConfig,
    SettlementConfigurationError,
    SettlementConfigurationRegistry,
    SettlementRole,
)

_COMMON_OPERATORS = frozenset(
    {
        ComparisonOperator.EQUAL,
        ComparisonOperator.NOT_EQUAL,
        ComparisonOperator.IN,
        ComparisonOperator.NOT_IN,
    }
)
_COMMON_FIELDS = (
    FieldDescriptor(
        name="mechanism",
        value_type=QueryValueType.STRING,
        operators=_COMMON_OPERATORS,
        description="canonical settlement mechanism ID or configuration key",
    ),
    FieldDescriptor(
        name="asset",
        value_type=QueryValueType.STRING,
        operators=_COMMON_OPERATORS,
        description="public settlement asset",
    ),
    FieldDescriptor(
        name="option_id",
        value_type=QueryValueType.STRING,
        operators=_COMMON_OPERATORS,
        description="immutable settlement option ID",
    ),
)
_MISSING = object()


@dataclass(frozen=True, slots=True)
class CompiledSettlementClause:
    """One validated conjunction over one advertised settlement option."""

    query: ValidatedQuery

    def render(self) -> str:
        return self.query.render()


@dataclass(frozen=True, slots=True)
class SettlementCandidate:
    """One installed, enabled, role-compatible advertised option."""

    registration: MechanismRegistration
    option: SettlementOption


@dataclass(frozen=True, slots=True)
class SettlementClauseResult:
    """Priority-ordered survivors from the first accepted explicit clause."""

    candidates: tuple[SettlementCandidate, ...]
    matched_clause_index: int | None


def settlement_clause_descriptors(
    registry: SettlementConfigurationRegistry,
    *,
    role: SettlementRole,
) -> tuple[FieldDescriptor, ...]:
    """Return common and role-applicable mechanism fields deterministically."""

    contributed = tuple(
        item.field.descriptor for item in registry.clause_fields(role=role)
    )
    return (*_COMMON_FIELDS, *contributed)


def compile_settlement_clause(
    source: str,
    registry: SettlementConfigurationRegistry,
    *,
    role: SettlementRole = "buyer",
) -> CompiledSettlementClause:
    """Compile one clause and normalize public mechanism aliases."""

    query = compile_query(source, settlement_clause_descriptors(registry, role=role))
    comparisons: list[ValidatedComparison] = []
    for comparison in query.comparisons:
        if comparison.field != "mechanism":
            comparisons.append(comparison)
            continue
        value = comparison.value
        values = value if isinstance(value, tuple) else (value,)
        normalized: list[ScalarValue] = []
        for item in values:
            assert isinstance(item, str)
            try:
                normalized.append(registry.canonical_mechanism_id(item, role=role))
            except SettlementConfigurationError as exc:
                raise QueryValidationError(
                    "unknown_mechanism",
                    f"unknown or role-inapplicable settlement mechanism at position {comparison.span.start}",
                    position=comparison.span.start,
                    field="mechanism",
                    accepted_fields=("mechanism",),
                ) from exc
        comparisons.append(
            ValidatedComparison(
                field=comparison.field,
                operator=comparison.operator,
                value=tuple(normalized) if isinstance(value, tuple) else normalized[0],
                span=comparison.span,
            )
        )
    return CompiledSettlementClause(ValidatedQuery(tuple(comparisons)))


def settlement_clause_matches(
    clause: CompiledSettlementClause,
    option: SettlementOption,
    registry: SettlementConfigurationRegistry,
    *,
    role: SettlementRole = "buyer",
) -> bool:
    """Evaluate every predicate against the same immutable option."""

    contributed = _field_bindings(registry, role=role)
    descriptors = {
        descriptor.name: descriptor
        for descriptor in settlement_clause_descriptors(registry, role=role)
    }
    for comparison in clause.query.comparisons:
        descriptor = descriptors[comparison.field]
        actual: Any
        if comparison.field == "mechanism":
            actual = option.mechanism
        elif comparison.field == "asset":
            actual = option.asset
        elif comparison.field == "option_id":
            actual = option.option_id
        else:
            binding = contributed[comparison.field]
            if option.mechanism != binding.mechanism_id:
                return False
            actual = binding.field.projector(option)
            if actual is None or (
                isinstance(actual, Sequence)
                and not isinstance(actual, (str, bytes))
                and not actual
            ):
                actual = _MISSING
        if actual is _MISSING:
            if descriptor.on_missing is MissingValueRule.PASS:
                continue
            return False
        projected = _validated_projection(actual, descriptor)
        if not _comparison_matches(comparison, projected):
            return False
    return True


def select_settlement_candidates(
    advertised: Iterable[SettlementOption | Mapping[str, Any]],
    *,
    registry: SettlementConfigurationRegistry,
    config: SettlementConfig,
    clauses: Iterable[str | CompiledSettlementClause] = (),
    public_context: Mapping[str, Any] | None = None,
) -> SettlementClauseResult:
    """Admit compatible options, then apply ordered clause alternatives."""

    registry.validate(config, role="buyer")
    decoded = tuple(SettlementOption.model_validate(option) for option in advertised)
    by_mechanism: dict[str, list[SettlementOption]] = {}
    for option in decoded:
        by_mechanism.setdefault(option.mechanism, []).append(option)

    candidates: list[SettlementCandidate] = []
    for registration in registry.ordered_registrations(config, role="buyer"):
        section = config.mechanism_config(registration.config_key)
        if section is None or not bool(getattr(section, "enabled", False)):
            continue
        for option in sorted(
            by_mechanism.get(registration.mechanism_id, ()),
            key=lambda candidate: candidate.option_id,
        ):
            if registry.buyer_compatible(
                registration.mechanism_id,
                option,
                config,
                public_context=public_context,
            ):
                candidates.append(SettlementCandidate(registration, option))

    compiled = tuple(
        clause
        if isinstance(clause, CompiledSettlementClause)
        else compile_settlement_clause(clause, registry, role="buyer")
        for clause in clauses
    )
    if not compiled:
        return SettlementClauseResult(tuple(candidates), None)
    for index, clause in enumerate(compiled):
        survivors = tuple(
            candidate
            for candidate in candidates
            if settlement_clause_matches(
                clause,
                candidate.option,
                registry,
                role="buyer",
            )
        )
        if survivors:
            return SettlementClauseResult(survivors, index)
    return SettlementClauseResult((), None)


def _field_bindings(
    registry: SettlementConfigurationRegistry,
    *,
    role: SettlementRole,
) -> dict[str, RegisteredSettlementClauseField]:
    bindings: dict[str, RegisteredSettlementClauseField] = {}
    for item in registry.clause_fields(role=role):
        bindings[item.field.descriptor.name] = item
        for alias in item.field.descriptor.aliases:
            bindings[alias] = item
    return bindings


def _validated_projection(
    actual: Any,
    descriptor: FieldDescriptor,
) -> tuple[ScalarValue, ...]:
    values = (
        tuple(actual)
        if isinstance(actual, Sequence) and not isinstance(actual, (str, bytes))
        else (actual,)
    )
    if not values:
        raise SettlementConfigurationError(
            f"projector for {descriptor.name!r} returned an empty value"
        )
    normalized: list[ScalarValue] = []
    for value in values:
        if descriptor.value_type is QueryValueType.STRING:
            valid = isinstance(value, str)
            converted: ScalarValue = value
        elif descriptor.value_type is QueryValueType.INTEGER:
            valid = isinstance(value, int) and not isinstance(value, bool)
            converted = value
        elif descriptor.value_type is QueryValueType.DECIMAL:
            valid = isinstance(value, (int, Decimal)) and not isinstance(value, bool)
            converted = Decimal(value) if valid else value
        else:
            valid = isinstance(value, bool)
            converted = value
        if not valid:
            raise SettlementConfigurationError(
                f"projector for {descriptor.name!r} returned the wrong value type"
            )
        normalized.append(converted)
    return tuple(normalized)


def _comparison_matches(
    comparison: ValidatedComparison,
    actual: tuple[ScalarValue, ...],
) -> bool:
    expected = comparison.value
    operator = comparison.operator
    if operator is ComparisonOperator.EQUAL:
        assert not isinstance(expected, tuple)
        return any(value == expected for value in actual)
    if operator is ComparisonOperator.NOT_EQUAL:
        assert not isinstance(expected, tuple)
        return all(value != expected for value in actual)
    if operator is ComparisonOperator.IN:
        assert isinstance(expected, tuple)
        return any(value in expected for value in actual)
    if operator is ComparisonOperator.NOT_IN:
        assert isinstance(expected, tuple)
        return all(value not in expected for value in actual)
    assert not isinstance(expected, tuple)
    if operator is ComparisonOperator.LESS_THAN:
        return any(value < expected for value in actual)
    if operator is ComparisonOperator.LESS_THAN_OR_EQUAL:
        return any(value <= expected for value in actual)
    if operator is ComparisonOperator.GREATER_THAN:
        return any(value > expected for value in actual)
    if operator is ComparisonOperator.GREATER_THAN_OR_EQUAL:
        return any(value >= expected for value in actual)
    raise AssertionError(f"unsupported comparison operator {operator}")
