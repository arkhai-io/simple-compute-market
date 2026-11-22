"""The compute family's RFQ wire contracts and registry validation artifact."""

from datetime import date, datetime, timezone
import json
import math
import re
import sys
from typing import Any, Literal, NotRequired, TypedDict, cast, get_args

from market_capability_shape import CapabilityShapeError, FieldKind, unflatten_shape

from arkhai_compute.capability_schema import COMPUTE_CAPABILITY_SCHEMA, GPU_MODEL_ATTRIBUTE

_MetadataValue = str | bool | int | float
_TermUnit = Literal["day", "month"]
_TERM_UNITS = get_args(_TermUnit)
_DIMENSIONS = frozenset(COMPUTE_CAPABILITY_SCHEMA.flat_names(FieldKind.QUANTITY))
_METADATA_KEY = re.compile(r"[A-Za-z0-9_.-]{1,40}")
_MAX_METADATA_ENTRIES = 50
_MAX_METADATA_TEXT = 500
_MAX_DESCRIPTION = 4000
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_INSTANT = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])"
)


class ComputeRfqTerm(TypedDict):
    value: int
    unit: _TermUnit


class ComputeRfqRequirements(TypedDict):
    shape: dict[str, str | int]
    node_count: int
    regions: list[str]
    start_earliest: str
    start_latest: str
    term: ComputeRfqTerm
    respond_by: str
    description: NotRequired[str]
    metadata: NotRequired[dict[str, _MetadataValue]]


class ComputeRfqFilters(TypedDict):
    gpu_model: NotRequired[str]
    min_node_count: NotRequired[int]
    region: NotRequired[str]


class ComputeRfqResponseQuantity(TypedDict):
    offered_node_count: NotRequired[int]


def _object(body: object, required: frozenset[str], optional: frozenset[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(body, dict) or required - body.keys() or body.keys() - required - optional:
        raise ValueError("invalid RFQ fields")
    return body


def _quantity(value: object) -> bool:
    return type(value) is int and value > 0


def _name(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_shape(value: object) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError("a compute RFQ requires a hardware shape")
    try:
        unflatten_shape(
            {name: count for name, count in value.items() if name in _DIMENSIONS},
            {name: label for name, label in value.items() if name not in _DIMENSIONS},
            COMPUTE_CAPABILITY_SCHEMA,
        )
    except CapabilityShapeError:
        raise ValueError("invalid or incomplete compute hardware shape") from None


def _calendar_date(value: object) -> date:
    if not isinstance(value, str) or not _DATE.fullmatch(value):
        raise ValueError("an RFQ date requires YYYY-MM-DD")
    return date.fromisoformat(value)


def _validate_instant(value: object) -> None:
    if not isinstance(value, str) or not _INSTANT.fullmatch(value):
        raise ValueError("an RFQ instant requires a date, time and timezone")
    try:
        datetime.fromisoformat(value).astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError("the RFQ instant is outside the UTC calendar") from exc


def _metadata_scalar(value: object) -> bool:
    return (
        type(value) in (bool, int)
        or (isinstance(value, float) and math.isfinite(value))
        or (isinstance(value, str) and len(value) <= _MAX_METADATA_TEXT)
    )


def _validate_metadata(value: object) -> None:
    if (
        not isinstance(value, dict)
        or len(value) > _MAX_METADATA_ENTRIES
        or any(
            not isinstance(name, str) or not _METADATA_KEY.fullmatch(name) or not _metadata_scalar(item)
            for name, item in value.items()
        )
    ):
        raise ValueError("RFQ metadata requires bounded keys and scalar values")


def validate_requirements(body: object) -> ComputeRfqRequirements:
    requirements = _object(
        body, ComputeRfqRequirements.__required_keys__, ComputeRfqRequirements.__optional_keys__
    )
    _validate_shape(requirements["shape"])
    if not _quantity(requirements["node_count"]):
        raise ValueError("an RFQ requires a positive node count")
    regions = requirements["regions"]
    if not isinstance(regions, list) or not regions or not all(map(_name, regions)):
        raise ValueError("an RFQ requires one or more region names")
    if _calendar_date(requirements["start_latest"]) < _calendar_date(requirements["start_earliest"]):
        raise ValueError("the latest start precedes the earliest start")
    term = _object(requirements["term"], ComputeRfqTerm.__required_keys__)
    if not _quantity(term["value"]) or term["unit"] not in _TERM_UNITS:
        raise ValueError("an RFQ term requires a positive number of days or months")
    _validate_instant(requirements["respond_by"])
    if "description" in requirements:
        description = requirements["description"]
        if not isinstance(description, str) or len(description) > _MAX_DESCRIPTION:
            raise ValueError("invalid RFQ description")
    if "metadata" in requirements:
        _validate_metadata(requirements["metadata"])
    return cast(ComputeRfqRequirements, requirements)


def validate_filters(body: object) -> ComputeRfqFilters:
    filters = _object(body, ComputeRfqFilters.__required_keys__, ComputeRfqFilters.__optional_keys__)
    for name in ("gpu_model", "region"):
        if name in filters and not _name(filters[name]):
            raise ValueError("invalid RFQ search field")
    if "min_node_count" in filters and not _quantity(filters["min_node_count"]):
        raise ValueError("a minimum node count must be positive")
    return cast(ComputeRfqFilters, filters)


def validate_response_quantity(body: object) -> ComputeRfqResponseQuantity:
    response = _object(
        body, ComputeRfqResponseQuantity.__required_keys__, ComputeRfqResponseQuantity.__optional_keys__
    )
    if "offered_node_count" in response and not _quantity(response["offered_node_count"]):
        raise ValueError("an offered node count must be positive")
    return cast(ComputeRfqResponseQuantity, response)


_QUANTITY_SCHEMA = {"type": "integer", "minimum": 1}
_NAME_SCHEMA = {"type": "string", "pattern": r"\S"}


def _object_schema(properties: dict[str, Any], required: frozenset[str] = frozenset()) -> dict[str, Any]:
    return {
        "type": "object", "additionalProperties": False, "properties": properties,
        **({"required": sorted(required)} if required else {}),
    }


def _shape_schema() -> dict[str, Any]:
    properties = {}
    dependent = {}
    for field in COMPUTE_CAPABILITY_SCHEMA.fields:
        properties[field.flat_name] = _QUANTITY_SCHEMA if field.kind is FieldKind.QUANTITY else _NAME_SCHEMA
        required = [
            sibling.flat_name for sibling in COMPUTE_CAPABILITY_SCHEMA.fields
            if sibling.family == field.family and sibling.required and sibling != field
        ]
        if required:
            dependent[field.flat_name] = required
    return _object_schema(properties) | {"minProperties": 1, "dependentRequired": dependent}


def _metadata_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "maxProperties": _MAX_METADATA_ENTRIES,
        "propertyNames": {"not": {"pattern": "[^A-Za-z0-9_.-]"}},
        "patternProperties": {
            f"^{_METADATA_KEY.pattern}$": {
                "anyOf": [
                    {"type": "string", "maxLength": _MAX_METADATA_TEXT},
                    {"type": "boolean"},
                    {"type": "number"},
                ],
            },
        },
    }


def registry_schema() -> dict[str, Any]:
    """Build the schema and mappings that a neutral registry can load."""
    return {
        "kind": "compute",
        "version": 1,
        "requirements": _object_schema(
            {
                "shape": _shape_schema(),
                "node_count": _QUANTITY_SCHEMA,
                "regions": {"type": "array", "minItems": 1, "items": _NAME_SCHEMA},
                "start_earliest": {"type": "string", "format": "date", "pattern": f"^{_DATE.pattern}$"},
                "start_latest": {"type": "string", "format": "date", "pattern": f"^{_DATE.pattern}$"},
                "term": _object_schema(
                    {"value": _QUANTITY_SCHEMA, "unit": {"type": "string", "enum": list(_TERM_UNITS)}},
                    ComputeRfqTerm.__required_keys__,
                ),
                "respond_by": {"type": "string", "format": "date-time", "pattern": f"^{_INSTANT.pattern}$"},
                "description": {"type": "string", "maxLength": _MAX_DESCRIPTION},
                "metadata": _metadata_schema(),
            },
            ComputeRfqRequirements.__required_keys__,
        ),
        "search": _object_schema({
            "gpu_model": _NAME_SCHEMA, "min_node_count": _QUANTITY_SCHEMA, "region": _NAME_SCHEMA,
        }),
        "response_quantity": _object_schema({"offered_node_count": _QUANTITY_SCHEMA}),
        "fields": {
            "quantity": "node_count",
            "offered_quantity": "offered_node_count",
            "start_earliest": "start_earliest",
            "start_latest": "start_latest",
            "respond_by": "respond_by",
        },
        "filters": [
            {"name": "gpu_model", "path": f"$.shape.{GPU_MODEL_ATTRIBUTE}", "op": "in", "value_type": "string"},
            {
                "name": "min_node_count", "path": "$.node_count", "op": "range",
                "value_type": "integer", "alias_kind": "lower_bound",
            },
            {"name": "region", "path": "$.regions[*]", "op": "in", "value_type": "string"},
        ],
    }


def main() -> None:
    json.dump(registry_schema(), sys.stdout, indent=2, sort_keys=True, allow_nan=False)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
