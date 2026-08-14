"""Dependency-light comparison DSL shared by marketplace query compilers.

This module owns syntax, source spans, generic field descriptors, typed
validation, canonical rendering, and safe diagnostics. Registry and settlement
packages provide vocabularies and interpret validated comparisons; this module
contains no role, domain, registry, mechanism, or provider knowledge.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterable, TypeAlias


class ComparisonOperator(str, Enum):
    EQUAL = "="
    NOT_EQUAL = "!="
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="
    IN = "in"
    NOT_IN = "notin"


class QueryValueType(str, Enum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"


class MissingValueRule(str, Enum):
    FAIL = "fail"
    PASS = "pass"


class TokenKind(str, Enum):
    ATOM = "atom"
    STRING = "string"
    OPERATOR = "operator"
    LEFT_BRACKET = "left_bracket"
    RIGHT_BRACKET = "right_bracket"
    COMMA = "comma"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start: int
    end: int

    def __post_init__(self) -> None:
        if self.start < 0 or self.end < self.start:
            raise ValueError("invalid source span")


@dataclass(frozen=True, slots=True)
class QueryToken:
    kind: TokenKind
    text: str
    span: SourceSpan
    value: str | None = None


ScalarValue: TypeAlias = str | int | Decimal | bool
LiteralValue: TypeAlias = ScalarValue | tuple[ScalarValue, ...]


@dataclass(frozen=True, slots=True)
class QueryLiteral:
    value: LiteralValue
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class QueryComparison:
    field: str
    operator: ComparisonOperator
    literal: QueryLiteral
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class QueryExpression:
    source: str
    comparisons: tuple[QueryComparison, ...]


@dataclass(frozen=True, slots=True)
class FieldDescriptor:
    name: str
    value_type: QueryValueType
    operators: frozenset[ComparisonOperator]
    aliases: tuple[str, ...] = ()
    on_missing: MissingValueRule = MissingValueRule.FAIL
    repeated: bool = False
    description: str | None = None

    def __post_init__(self) -> None:
        names = (self.name, *self.aliases)
        if any(not _FIELD_RE.fullmatch(name) for name in names):
            raise ValueError(f"invalid query field name in descriptor {self.name!r}")
        if len(set(names)) != len(names):
            raise ValueError(f"duplicate query field alias in descriptor {self.name!r}")
        if not self.operators:
            raise ValueError(f"query field {self.name!r} must allow an operator")


@dataclass(frozen=True, slots=True)
class ValidatedComparison:
    field: str
    operator: ComparisonOperator
    value: LiteralValue
    span: SourceSpan


@dataclass(frozen=True, slots=True)
class ValidatedQuery:
    comparisons: tuple[ValidatedComparison, ...]

    def render(self) -> str:
        return render_canonical_query(self)


class QueryError(ValueError):
    """Source-positioned, value-redacted query failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        position: int,
        field: str | None = None,
        accepted_fields: Iterable[str] = (),
    ) -> None:
        super().__init__(message)
        self.code = code
        self.position = position
        self.field = field
        self.accepted_fields = tuple(sorted(set(accepted_fields)))

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": self.code,
            "message": str(self),
            "position": self.position,
        }
        if self.field is not None:
            result["field"] = self.field
        if self.accepted_fields:
            result["accepted_fields"] = list(self.accepted_fields)
        return result


class QuerySyntaxError(QueryError):
    pass


class QueryValidationError(QueryError):
    pass


_FIELD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
_INTEGER_RE = re.compile(r"[+-]?\d+")
_DECIMAL_RE = re.compile(
    r"[+-]?(?:(?:\d+\.\d*)|(?:\d*\.\d+)|(?:\d+[eE][+-]?\d+)|"
    r"(?:\d+\.\d*[eE][+-]?\d+)|(?:\d*\.\d+[eE][+-]?\d+))"
)
_SAFE_STRING_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_./:@+-]*")
_SYMBOLIC_OPERATORS = ("!=", "<=", ">=", "=", "<", ">")


def lex_query(source: str) -> tuple[QueryToken, ...]:
    """Tokenize one already shell-decoded query string."""

    tokens: list[QueryToken] = []
    index = 0
    while index < len(source):
        char = source[index]
        if char.isspace():
            index += 1
            continue
        if char in "()":
            tokens.append(
                QueryToken(
                    TokenKind.UNSUPPORTED,
                    char,
                    SourceSpan(index, index + 1),
                )
            )
            index += 1
            continue
        if char == "[":
            tokens.append(
                QueryToken(TokenKind.LEFT_BRACKET, char, SourceSpan(index, index + 1))
            )
            index += 1
            continue
        if char == "]":
            tokens.append(
                QueryToken(TokenKind.RIGHT_BRACKET, char, SourceSpan(index, index + 1))
            )
            index += 1
            continue
        if char == ",":
            tokens.append(QueryToken(TokenKind.COMMA, char, SourceSpan(index, index + 1)))
            index += 1
            continue
        if char == '"':
            token, index = _lex_string(source, index)
            tokens.append(token)
            continue
        operator = next(
            (candidate for candidate in _SYMBOLIC_OPERATORS if source.startswith(candidate, index)),
            None,
        )
        if operator is not None:
            end = index + len(operator)
            tokens.append(
                QueryToken(TokenKind.OPERATOR, operator, SourceSpan(index, end))
            )
            index = end
            continue
        end = index
        while end < len(source) and not source[end].isspace() and source[end] not in "[]=!<>,()":
            end += 1
        if end == index:
            raise QuerySyntaxError(
                "unsupported_character",
                f"unsupported character at position {index}",
                position=index,
            )
        text = source[index:end]
        kind = TokenKind.OPERATOR if text in {"in", "notin"} else TokenKind.ATOM
        tokens.append(QueryToken(kind, text, SourceSpan(index, end), value=text))
        index = end
    return tuple(tokens)


def _lex_string(source: str, start: int) -> tuple[QueryToken, int]:
    escaped = False
    end = start + 1
    while end < len(source):
        char = source[end]
        if char == '"' and not escaped:
            end += 1
            text = source[start:end]
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise QuerySyntaxError(
                    "invalid_string_escape",
                    f"invalid quoted string at position {start}",
                    position=start,
                ) from exc
            if not isinstance(value, str):
                raise AssertionError("JSON string lexer returned a non-string")
            return (
                QueryToken(TokenKind.STRING, text, SourceSpan(start, end), value=value),
                end,
            )
        if char == "\\" and not escaped:
            escaped = True
        else:
            escaped = False
        end += 1
    raise QuerySyntaxError(
        "unterminated_string",
        f"unterminated quoted string at position {start}",
        position=start,
    )


def parse_query(source: str) -> QueryExpression:
    """Parse comparisons without assigning field-specific meaning."""

    tokens = lex_query(source)
    comparisons: list[QueryComparison] = []
    index = 0
    while index < len(tokens):
        field_token = tokens[index]
        if field_token.kind is TokenKind.UNSUPPORTED:
            raise QuerySyntaxError(
                "unsupported_syntax",
                f"unsupported token {field_token.text!r} at position {field_token.span.start}",
                position=field_token.span.start,
            )
        if field_token.kind is not TokenKind.ATOM or not _FIELD_RE.fullmatch(field_token.text):
            raise QuerySyntaxError(
                "expected_field",
                f"expected a field name at position {field_token.span.start}",
                position=field_token.span.start,
            )
        index += 1
        if index >= len(tokens):
            raise QuerySyntaxError(
                "expected_operator",
                f"expected an operator after field {field_token.text!r}",
                position=field_token.span.end,
                field=field_token.text,
            )
        operator_token = tokens[index]
        try:
            operator = ComparisonOperator(operator_token.text)
        except ValueError as exc:
            raise QuerySyntaxError(
                "expected_operator",
                f"expected an operator at position {operator_token.span.start}",
                position=operator_token.span.start,
                field=field_token.text,
            ) from exc
        index += 1
        if index >= len(tokens):
            raise QuerySyntaxError(
                "expected_value",
                f"expected a value for field {field_token.text!r}",
                position=operator_token.span.end,
                field=field_token.text,
            )
        literal, index = _parse_literal(tokens, index, field_token.text)
        comparisons.append(
            QueryComparison(
                field=field_token.text,
                operator=operator,
                literal=literal,
                span=SourceSpan(field_token.span.start, literal.span.end),
            )
        )
    return QueryExpression(source=source, comparisons=tuple(comparisons))


def _parse_literal(
    tokens: tuple[QueryToken, ...], index: int, field: str
) -> tuple[QueryLiteral, int]:
    token = tokens[index]
    if token.kind is TokenKind.UNSUPPORTED:
        raise QuerySyntaxError(
            "unsupported_syntax",
            f"unsupported token {token.text!r} at position {token.span.start}",
            position=token.span.start,
            field=field,
        )
    if token.kind is TokenKind.LEFT_BRACKET:
        start = token.span.start
        index += 1
        values: list[ScalarValue] = []
        expect_value = True
        while index < len(tokens):
            token = tokens[index]
            if token.kind is TokenKind.RIGHT_BRACKET:
                if expect_value and values:
                    raise QuerySyntaxError(
                        "expected_list_value",
                        f"expected a list value at position {token.span.start}",
                        position=token.span.start,
                        field=field,
                    )
                return QueryLiteral(tuple(values), SourceSpan(start, token.span.end)), index + 1
            if expect_value:
                if token.kind not in {TokenKind.ATOM, TokenKind.STRING}:
                    raise QuerySyntaxError(
                        "expected_list_value",
                        f"expected a list value at position {token.span.start}",
                        position=token.span.start,
                        field=field,
                    )
                values.append(_token_scalar(token))
                expect_value = False
                index += 1
                continue
            if token.kind is not TokenKind.COMMA:
                raise QuerySyntaxError(
                    "expected_comma",
                    f"expected ',' at position {token.span.start}",
                    position=token.span.start,
                    field=field,
                )
            expect_value = True
            index += 1
        raise QuerySyntaxError(
            "unterminated_list",
            f"unterminated list at position {start}",
            position=start,
            field=field,
        )
    if token.kind not in {TokenKind.ATOM, TokenKind.STRING}:
        raise QuerySyntaxError(
            "expected_value",
            f"expected a value at position {token.span.start}",
            position=token.span.start,
            field=field,
        )
    return QueryLiteral(_token_scalar(token), token.span), index + 1


def _token_scalar(token: QueryToken) -> ScalarValue:
    if token.kind is TokenKind.STRING:
        assert token.value is not None
        return token.value
    text = token.text
    if text == "true":
        return True
    if text == "false":
        return False
    if _INTEGER_RE.fullmatch(text):
        return int(text)
    if _DECIMAL_RE.fullmatch(text):
        try:
            return Decimal(text)
        except InvalidOperation as exc:
            raise QuerySyntaxError(
                "invalid_decimal",
                f"invalid decimal at position {token.span.start}",
                position=token.span.start,
            ) from exc
    return text


def validate_query(
    expression: QueryExpression,
    descriptors: Iterable[FieldDescriptor],
) -> ValidatedQuery:
    """Resolve fields and validate operators, literal shapes, and types."""

    by_name, canonical = _descriptor_maps(descriptors)
    accepted = tuple(sorted(by_name))
    seen: set[str] = set()
    validated: list[ValidatedComparison] = []
    for comparison in expression.comparisons:
        descriptor = by_name.get(comparison.field)
        if descriptor is None:
            raise QueryValidationError(
                "unknown_field",
                f"unknown field {comparison.field!r} at position {comparison.span.start}",
                position=comparison.span.start,
                field=comparison.field,
                accepted_fields=accepted,
            )
        if comparison.operator not in descriptor.operators:
            allowed = ", ".join(sorted(operator.value for operator in descriptor.operators))
            raise QueryValidationError(
                "unsupported_operator",
                f"field {descriptor.name!r} does not support {comparison.operator.value!r}; allowed: {allowed}",
                position=comparison.span.start,
                field=descriptor.name,
                accepted_fields=accepted,
            )
        if descriptor.name in seen and not descriptor.repeated:
            raise QueryValidationError(
                "duplicate_field",
                f"field {descriptor.name!r} may appear only once",
                position=comparison.span.start,
                field=descriptor.name,
                accepted_fields=accepted,
            )
        value = _validate_literal_shape(comparison, descriptor, accepted)
        seen.add(descriptor.name)
        validated.append(
            ValidatedComparison(
                field=canonical[descriptor.name].name,
                operator=comparison.operator,
                value=value,
                span=comparison.span,
            )
        )
    return ValidatedQuery(tuple(validated))


def compile_query(
    source: str,
    descriptors: Iterable[FieldDescriptor],
) -> ValidatedQuery:
    return validate_query(parse_query(source), descriptors)


def _descriptor_maps(
    descriptors: Iterable[FieldDescriptor],
) -> tuple[dict[str, FieldDescriptor], dict[str, FieldDescriptor]]:
    by_name: dict[str, FieldDescriptor] = {}
    canonical: dict[str, FieldDescriptor] = {}
    for descriptor in descriptors:
        if descriptor.name in canonical:
            raise ValueError(f"duplicate query field descriptor: {descriptor.name!r}")
        canonical[descriptor.name] = descriptor
        for name in (descriptor.name, *descriptor.aliases):
            if name in by_name:
                raise ValueError(f"duplicate query field or alias: {name!r}")
            by_name[name] = descriptor
    return by_name, canonical


def _validate_literal_shape(
    comparison: QueryComparison,
    descriptor: FieldDescriptor,
    accepted: tuple[str, ...],
) -> LiteralValue:
    value = comparison.literal.value
    expects_list = comparison.operator in {
        ComparisonOperator.IN,
        ComparisonOperator.NOT_IN,
    }
    if expects_list != isinstance(value, tuple):
        expected = "a list" if expects_list else "a scalar"
        raise QueryValidationError(
            "invalid_value_shape",
            f"field {descriptor.name!r} requires {expected} for operator {comparison.operator.value!r}",
            position=comparison.literal.span.start,
            field=descriptor.name,
            accepted_fields=accepted,
        )
    if isinstance(value, tuple):
        if not value:
            raise QueryValidationError(
                "empty_list",
                f"field {descriptor.name!r} requires a non-empty list",
                position=comparison.literal.span.start,
                field=descriptor.name,
                accepted_fields=accepted,
            )
        return tuple(
            _validate_scalar(item, descriptor, comparison.literal.span.start, accepted)
            for item in value
        )
    return _validate_scalar(value, descriptor, comparison.literal.span.start, accepted)


def _validate_scalar(
    value: ScalarValue,
    descriptor: FieldDescriptor,
    position: int,
    accepted: tuple[str, ...],
) -> ScalarValue:
    valid = False
    normalized: ScalarValue = value
    if descriptor.value_type is QueryValueType.STRING:
        valid = isinstance(value, str)
    elif descriptor.value_type is QueryValueType.INTEGER:
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif descriptor.value_type is QueryValueType.DECIMAL:
        valid = (isinstance(value, (int, Decimal)) and not isinstance(value, bool))
        if valid:
            normalized = Decimal(value)
    elif descriptor.value_type is QueryValueType.BOOLEAN:
        valid = isinstance(value, bool)
    if not valid:
        raise QueryValidationError(
            "invalid_value_type",
            f"field {descriptor.name!r} requires {descriptor.value_type.value}",
            position=position,
            field=descriptor.name,
            accepted_fields=accepted,
        )
    return normalized


def render_canonical_query(query: ValidatedQuery) -> str:
    return " ".join(
        f"{comparison.field}{comparison.operator.value}{_render_literal(comparison.value)}"
        for comparison in query.comparisons
    )


def _render_literal(value: LiteralValue) -> str:
    if isinstance(value, tuple):
        return "[" + ",".join(_render_scalar(item) for item in value) + "]"
    return _render_scalar(value)


def _render_scalar(value: ScalarValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, Decimal):
        if value == 0:
            return "0"
        return format(value.normalize(), "f")
    if isinstance(value, int):
        return str(value)
    if _SAFE_STRING_RE.fullmatch(value) and value not in {"true", "false", "in", "notin"}:
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def field_reference_json(
    descriptors: Iterable[FieldDescriptor],
) -> list[dict[str, Any]]:
    """Return deterministic, public descriptor metadata for JSON help."""

    ordered = sorted(descriptors, key=lambda descriptor: descriptor.name)
    _descriptor_maps(ordered)
    return [
        {
            "name": descriptor.name,
            "aliases": list(sorted(descriptor.aliases)),
            "value_type": descriptor.value_type.value,
            "operators": [
                operator.value
                for operator in sorted(descriptor.operators, key=lambda item: item.value)
            ],
            "on_missing": descriptor.on_missing.value,
            "repeated": descriptor.repeated,
            **(
                {"description": descriptor.description}
                if descriptor.description is not None
                else {}
            ),
        }
        for descriptor in ordered
    ]


def render_field_reference(descriptors: Iterable[FieldDescriptor]) -> str:
    """Render the same deterministic field metadata for human help."""

    lines: list[str] = []
    for item in field_reference_json(descriptors):
        aliases = f" aliases={','.join(item['aliases'])}" if item["aliases"] else ""
        repeated = " repeated" if item["repeated"] else ""
        description = f" — {item['description']}" if "description" in item else ""
        lines.append(
            f"{item['name']}: {item['value_type']} "
            f"operators={','.join(item['operators'])} "
            f"missing={item['on_missing']}{aliases}{repeated}{description}"
        )
    return "\n".join(lines)
