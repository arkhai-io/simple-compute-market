"""Compile the shared resource-query DSL against one registry filter spec."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from market_core import (
    ComparisonOperator,
    FieldDescriptor,
    MissingValueRule,
    QueryValueType,
    ValidatedComparison,
    compile_query,
)

from registry_client.models import FilterSpecResponse


class FilterVocabularyError(ValueError):
    """The authenticated registry advertised an unusable filter vocabulary."""


class ResourceQueryCompilationError(ValueError):
    """A valid resource comparison cannot be represented by the advertised filter."""


@dataclass(frozen=True, slots=True)
class CompiledResourceQuery:
    """Immutable registry-bound query parameters and their source contract."""

    registry_url: str
    etag: str
    schema_id: str | None
    schema_version: int | None
    canonical_query: str
    parameters: tuple[tuple[str, str], ...]

    def as_params(self) -> dict[str, str]:
        return dict(self.parameters)


@dataclass(frozen=True, slots=True)
class _ResourceField:
    descriptor: FieldDescriptor
    parameter: str
    filter_op: str
    alias_kind: str | None


def resource_query_descriptors(
    filter_spec: FilterSpecResponse,
) -> tuple[FieldDescriptor, ...]:
    """Return the exact DSL vocabulary declared by one registry."""

    return tuple(field.descriptor for field in _resource_fields(filter_spec.filters))


def compile_resource_query(
    source: str,
    *,
    filter_spec: FilterSpecResponse,
    registry_url: str,
) -> CompiledResourceQuery:
    """Validate and compile ``source`` for one URL+ETag-bound registry spec."""

    normalized_url = registry_url.rstrip("/")
    if not normalized_url:
        raise ValueError("registry_url must not be empty")
    if not filter_spec.etag:
        raise FilterVocabularyError("registry filter spec is missing its etag")

    fields = _resource_fields(filter_spec.filters)
    validated = compile_query(source, (field.descriptor for field in fields))
    by_name = {field.descriptor.name: field for field in fields}
    parameters = tuple(
        _compile_comparison(comparison, by_name[comparison.field])
        for comparison in validated.comparisons
    )
    return CompiledResourceQuery(
        registry_url=normalized_url,
        etag=filter_spec.etag,
        schema_id=filter_spec.schema_id,
        schema_version=filter_spec.schema_version,
        canonical_query=validated.render(),
        parameters=parameters,
    )


def _resource_fields(filters: Iterable[dict[str, Any]]) -> tuple[_ResourceField, ...]:
    fields: list[_ResourceField] = []
    for index, raw in enumerate(filters):
        if not isinstance(raw, dict):
            raise FilterVocabularyError(
                f"registry filter declaration {index} must be an object"
            )
        parameter = _required_string(raw, "name", index)
        query_name = raw.get("query_name") or parameter
        if not isinstance(query_name, str):
            raise FilterVocabularyError(
                f"registry filter declaration {index} has invalid query_name"
            )
        aliases_raw = raw.get("query_aliases") or []
        if not isinstance(aliases_raw, list) or not all(
            isinstance(alias, str) for alias in aliases_raw
        ):
            raise FilterVocabularyError(
                f"registry filter declaration {index} has invalid query_aliases"
            )
        filter_op = _required_string(raw, "op", index)
        alias_kind = raw.get("alias_kind")
        if alias_kind is not None and alias_kind not in {"lower_bound", "upper_bound"}:
            raise FilterVocabularyError(
                f"registry filter declaration {index} has invalid alias_kind"
            )
        on_missing_raw = raw.get("on_missing", "fail")
        try:
            on_missing = MissingValueRule(on_missing_raw)
        except ValueError as exc:
            raise FilterVocabularyError(
                f"registry filter declaration {index} has invalid on_missing"
            ) from exc
        fields.append(
            _ResourceField(
                descriptor=FieldDescriptor(
                    name=query_name,
                    aliases=tuple(aliases_raw),
                    value_type=_value_type(raw.get("value_type"), index),
                    operators=_operators(filter_op, alias_kind, index),
                    on_missing=on_missing,
                    description=f"registry filter parameter {parameter}",
                ),
                parameter=parameter,
                filter_op=filter_op,
                alias_kind=alias_kind,
            )
        )

    # Shared validation performs the cross-declaration collision check.
    try:
        compile_query("", (field.descriptor for field in fields))
    except ValueError as exc:
        raise FilterVocabularyError("registry filter query names are ambiguous") from exc
    return tuple(fields)


def _required_string(raw: dict[str, Any], key: str, index: int) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise FilterVocabularyError(
            f"registry filter declaration {index} has invalid {key}"
        )
    return value


def _value_type(value: Any, index: int) -> QueryValueType:
    mapping = {
        "string": QueryValueType.STRING,
        "address": QueryValueType.STRING,
        "integer": QueryValueType.INTEGER,
        "number": QueryValueType.DECIMAL,
        "boolean": QueryValueType.BOOLEAN,
    }
    try:
        return mapping[value]
    except (KeyError, TypeError) as exc:
        raise FilterVocabularyError(
            f"registry filter declaration {index} has invalid value_type"
        ) from exc


def _operators(
    filter_op: str, alias_kind: str | None, index: int
) -> frozenset[ComparisonOperator]:
    if filter_op == "in":
        return frozenset({ComparisonOperator.EQUAL, ComparisonOperator.IN})
    if filter_op == "not_in":
        return frozenset({ComparisonOperator.NOT_EQUAL, ComparisonOperator.NOT_IN})
    if filter_op == "exists":
        return frozenset({ComparisonOperator.EQUAL})
    if filter_op == "range":
        if alias_kind == "lower_bound":
            return frozenset(
                {ComparisonOperator.GREATER_THAN, ComparisonOperator.GREATER_THAN_OR_EQUAL}
            )
        if alias_kind == "upper_bound":
            return frozenset(
                {ComparisonOperator.LESS_THAN, ComparisonOperator.LESS_THAN_OR_EQUAL}
            )
        return frozenset(
            {
                ComparisonOperator.LESS_THAN,
                ComparisonOperator.LESS_THAN_OR_EQUAL,
                ComparisonOperator.GREATER_THAN,
                ComparisonOperator.GREATER_THAN_OR_EQUAL,
            }
        )
    raise FilterVocabularyError(
        f"registry filter declaration {index} has invalid op"
    )


def _compile_comparison(
    comparison: ValidatedComparison, field: _ResourceField
) -> tuple[str, str]:
    operator = comparison.operator
    value = comparison.value
    if field.filter_op == "in":
        if operator is ComparisonOperator.EQUAL:
            assert not isinstance(value, tuple)
            return field.parameter, _scalar(value)
        assert isinstance(value, tuple)
        return field.parameter, f"in:{_list(value)}"
    if field.filter_op == "not_in":
        values = value if isinstance(value, tuple) else (value,)
        return field.parameter, f"not_in:{_list(values)}"
    if field.filter_op == "exists":
        assert isinstance(value, bool)
        return field.parameter, f"exists:{_scalar(value)}"

    assert field.filter_op == "range"
    assert not isinstance(value, tuple)
    rendered = _scalar(value)
    if (
        operator is ComparisonOperator.GREATER_THAN_OR_EQUAL
        and field.alias_kind == "lower_bound"
    ) or (
        operator is ComparisonOperator.LESS_THAN_OR_EQUAL
        and field.alias_kind == "upper_bound"
    ):
        return field.parameter, rendered
    if operator is ComparisonOperator.GREATER_THAN:
        interval = f"({rendered},)"
    elif operator is ComparisonOperator.GREATER_THAN_OR_EQUAL:
        interval = f"[{rendered},)"
    elif operator is ComparisonOperator.LESS_THAN:
        interval = f"(,{rendered})"
    else:
        assert operator is ComparisonOperator.LESS_THAN_OR_EQUAL
        interval = f"(,{rendered}]"
    return field.parameter, f"range:{interval}"


def _list(values: tuple[Any, ...]) -> str:
    rendered: list[str] = []
    for value in values:
        item = _scalar(value)
        if item.strip() != item or any(delimiter in item for delimiter in ",[]"):
            raise ResourceQueryCompilationError(
                "registry set-form cannot represent one supplied list value"
            )
        rendered.append(item)
    return "[" + ",".join(rendered) + "]"


def _scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        return format(value.normalize(), "f")
    return str(value)
