"""Configured, market-neutral validation for RFQ request and search bodies."""

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import re
from typing import Annotated, Any, Never

from jsonpath_ng.exceptions import JsonPathLexerError, JsonPathParserError
from jsonschema import Draft202012Validator, FormatChecker, validators
from jsonschema.exceptions import SchemaError
from market_core.rfq import RfqReference
from pydantic import BaseModel, ConfigDict, Field

from core_registry.filter_eval import Criterion, scalar_criterion
from core_registry.filter_models import FilterDecl

_Field = Annotated[str, Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")]
_SIMPLE_PATH = re.compile(r"\$(?:\.[A-Za-z_][A-Za-z0-9_]*(?:\[\*\])?)+")
_FORMATS = FormatChecker()


@_FORMATS.checks("date", raises=ValueError)
def _calendar_date(value: Any) -> bool:
    return not isinstance(value, str) or date.fromisoformat(value).isoformat() == value


@_FORMATS.checks("date-time", raises=(ValueError, OverflowError))
def _instant(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    instant = datetime.fromisoformat(value)
    return instant.tzinfo is not None and bool(instant.astimezone(timezone.utc))


def _is_integer(_checker, value: Any) -> bool:
    return type(value) is int


def _is_number(_checker, value: Any) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


_Validator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine_many(
        {"integer": _is_integer, "number": _is_number}
    ),
)


class RfqInputError(ValueError):
    """The RFQ body does not meet its configured contract."""


class _RfqFields(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    quantity: _Field
    offered_quantity: _Field
    start_earliest: _Field
    start_latest: _Field
    respond_by: _Field
    set_fields: list[_Field] = Field(default_factory=list)
    prose_fields: list[_Field] = Field(default_factory=list)


class _RfqSpecDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: RfqReference
    version: int = Field(ge=1, le=1)
    requirements: dict[str, Any]
    search: dict[str, Any]
    response_quantity: dict[str, Any]
    fields: _RfqFields
    filters: list[FilterDecl]


def _walk_schema(node: Any) -> Iterator[dict[str, Any]]:
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk_schema(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk_schema(value)


def _check_schema(schema: dict[str, Any]) -> None:
    Draft202012Validator.check_schema(schema)
    # Version 1 uses inline schemas, so validation cannot fetch an external
    # resource or recurse through a definition at request time.
    for node in _walk_schema(schema):
        if node.keys() & {"$id", "$ref", "$dynamicRef", "$schema"}:
            raise ValueError("RFQ schemas use inline rules in the registry's dialect")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise ValueError("RFQ schemas must define closed object bodies")


def _field_schema(schema: dict[str, Any], path: str) -> dict[str, Any]:
    node = schema
    for segment in path.split(".")[1:]:
        if node.get("type") != "object":
            return {}
        field = segment.removesuffix("[*]")
        node = node.get("properties", {}).get(field, {})
        if segment != field:
            if not isinstance(node, dict) or node.get("type") != "array" or node.get("prefixItems"):
                return {}
            node = node.get("items", {})
        if not isinstance(node, dict):
            return {}
    return node


def _check_fields(spec: _RfqSpecDocument) -> None:
    fields = spec.fields
    required = set(spec.requirements.get("required", []))
    if len({fields.quantity, fields.start_earliest, fields.start_latest, fields.respond_by}) != 4:
        raise ValueError("RFQ requirement field mappings must be distinct")
    for name, kind, format_name in (
        (fields.quantity, "integer", None),
        (fields.start_earliest, "string", "date"),
        (fields.start_latest, "string", "date"),
        (fields.respond_by, "string", "date-time"),
    ):
        field = _field_schema(spec.requirements, f"$.{name}")
        if name not in required or field.get("type") != kind or field.get("format") != format_name:
            raise ValueError("invalid RFQ requirement field mapping")
        if format_name is not None and "pattern" not in field:
            raise ValueError("invalid RFQ temporal field mapping")
    for quantity in (
        _field_schema(spec.requirements, f"$.{fields.quantity}"),
        _field_schema(spec.response_quantity, f"$.{fields.offered_quantity}"),
    ):
        if quantity.get("type") != "integer" or quantity.get("minimum", 0) < 1:
            raise ValueError("RFQ quantities must declare positive integers")

    normalized = fields.set_fields + fields.prose_fields + [fields.respond_by]
    if len(set(normalized)) != len(normalized):
        raise ValueError("RFQ normalization field mappings must be distinct")
    for name in fields.set_fields:
        if _field_schema(spec.requirements, f"$.{name}[*]").get("type") != "string":
            raise ValueError("RFQ set fields must contain strings")
    for name in fields.prose_fields:
        if _field_schema(spec.requirements, f"$.{name}").get("type") != "string":
            raise ValueError("RFQ prose fields must be strings")

    names = {item.name for item in spec.filters}
    if (
        len(names) != len(spec.filters)
        or names != spec.search.get("properties", {}).keys()
        or spec.search.get("patternProperties")
    ):
        raise ValueError("RFQ search fields require one filter mapping each")
    for item in spec.filters:
        valid_operator = (
            item.op == "in" and item.value_type == "string" and item.alias_kind is None
        ) or (
            item.op == "range" and item.value_type == "integer" and item.alias_kind == "lower_bound"
        )
        if (
            not valid_operator
            or not _SIMPLE_PATH.fullmatch(item.path)
            or _field_schema(spec.requirements, item.path).get("type") != item.value_type
            or _field_schema(spec.search, f"$.{item.name}").get("type") != item.value_type
            or item.on_missing != "fail"
            or item.query_name is not None
            or item.query_aliases
            or item.requires
        ):
            raise ValueError("invalid RFQ filter mapping")
        scalar_criterion(item, 0 if item.value_type == "integer" else "", item.on_missing)


@dataclass(frozen=True)
class RfqSpec:
    document: _RfqSpecDocument
    _requirements: Any
    _search: Any
    _response: Any

    @property
    def kind(self) -> str:
        return self.document.kind

    def validate_requirements(self, body: Any) -> None:
        if not self._requirements.is_valid(body):
            raise RfqInputError("invalid_rfq_requirements")
        fields = self.document.fields
        if date.fromisoformat(body[fields.start_latest]) < date.fromisoformat(body[fields.start_earliest]):
            raise RfqInputError("inverted_rfq_start_window")

    def response_deadline(self, body: dict[str, Any]) -> datetime:
        instant = datetime.fromisoformat(body[self.document.fields.respond_by])
        return instant.astimezone(timezone.utc).replace(tzinfo=None)

    def canonical_terms(self, body: dict[str, Any]) -> str:
        fields = self.document.fields
        normalized = dict(body)
        normalized[fields.respond_by] = self.response_deadline(body).isoformat()
        for name in fields.set_fields:
            if name in body:
                normalized[name] = sorted(set(body[name]))
        for name in fields.prose_fields:
            if name in body:
                normalized[name] = body[name].strip()
        # JSON retains scalar type distinctions that equality on Python values
        # loses, including booleans versus integers and integers versus floats.
        return json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)

    def search_criteria(self, body: Any) -> list[Criterion]:
        if not self._search.is_valid(body):
            raise RfqInputError("invalid_rfq_search")
        return [
            scalar_criterion(item, body[item.name], item.on_missing)
            for item in self.document.filters if item.name in body
        ]

    def offered_quantity(self, body: Any, *, request: dict[str, Any]) -> int | None:
        if not self._response.is_valid(body):
            raise RfqInputError("invalid_rfq_response_quantity")
        offered = body.get(self.document.fields.offered_quantity)
        if offered is not None and offered > request[self.document.fields.quantity]:
            raise RfqInputError("rfq_response_quantity_exceeds_request")
        return offered


def _nonfinite_schema_constant(_: str) -> Never:
    raise ValueError("RFQ schemas require finite JSON numbers")


def _finite_schema_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        _nonfinite_schema_constant(value)
    return parsed


def load_rfq_spec(path: str | None) -> RfqSpec | None:
    if not path:
        return None
    try:
        document = _RfqSpecDocument.model_validate(json.loads(
            Path(path).read_bytes(),
            parse_constant=_nonfinite_schema_constant,
            parse_float=_finite_schema_float,
        ))
        schemas = (document.requirements, document.search, document.response_quantity)
        for schema in schemas:
            _check_schema(schema)
        _check_fields(document)
        return RfqSpec(document, *(_Validator(schema, format_checker=_FORMATS) for schema in schemas))
    except (OSError, ValueError, SchemaError, JsonPathLexerError, JsonPathParserError) as exc:
        raise RuntimeError("invalid REGISTRY_RFQ_SPEC_PATH configuration") from exc
