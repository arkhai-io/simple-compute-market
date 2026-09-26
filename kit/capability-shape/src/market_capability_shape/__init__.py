"""Family-grouped capability shapes: structure, schema-driven flattening, digest.

A capability shape groups what is offered by family, and each family by field:

    {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 64}}

This module knows no family or field name. A domain supplies a
``CapabilitySchema`` saying, for each family field, whether it is a quantity or
an attribute, whether it is required, and the flat name it takes once
flattened. Kits that only need to know a value is a well-formed shape use
``shape_structure_problems``, which needs no schema.

The digest is taken over the family-grouped form, never the flat names, so a
schema that renames a flat field changes no shape's digest.

This is capacity vocabulary: flattening yields the quantities a capacity claim
requests and the attributes admission matches by equality. It is a foundation
kit rather than part of the market core because only markets that admit
capacity against declared supply have shapes; it imports nothing but the
standard library so buyers, pool administration, sites, and domains can all
depend on it. See openspec/specs/market-composition/spec.md.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

SHAPE_DIGEST_PREFIX = "capability-shape.v1:"


class FieldKind(str, Enum):
    """How a family field flattens."""

    QUANTITY = "quantity"
    """A positive integer amount, requested and reserved."""
    ATTRIBUTE = "attribute"
    """A non-empty string matched by equality."""


@dataclass(frozen=True)
class ShapeField:
    """One family field a domain defines."""

    family: str
    field: str
    kind: FieldKind
    flat_name: str
    required: bool = False

    @property
    def path(self) -> str:
        return f"{self.family}.{self.field}"


@dataclass(frozen=True)
class CapabilitySchema:
    """A domain's vocabulary for capability shapes.

    Refuses to construct with a repeated path or flat name, because either
    would make flattening ambiguous.
    """

    fields: tuple[ShapeField, ...]

    def __post_init__(self) -> None:
        paths = [field.path for field in self.fields]
        flat_names = [field.flat_name for field in self.fields]
        if len(set(paths)) != len(paths):
            raise ValueError(f"capability schema repeats a family field: {paths}")
        if len(set(flat_names)) != len(flat_names):
            raise ValueError(f"capability schema repeats a flat name: {flat_names}")
        for field in self.fields:
            if not (field.family and field.field and field.flat_name):
                raise ValueError(f"capability schema field is incompletely named: {field}")

    def lookup(self, family: str, field: str) -> ShapeField | None:
        for candidate in self.fields:
            if candidate.family == family and candidate.field == field:
                return candidate
        return None

    @property
    def families(self) -> frozenset[str]:
        return frozenset(field.family for field in self.fields)

    def flat_names(self, kind: FieldKind) -> tuple[str, ...]:
        """Flat names of every field of ``kind``, in schema order."""
        return tuple(field.flat_name for field in self.fields if field.kind is kind)


@dataclass(frozen=True)
class ShapeProblem:
    """One reason a shape is refused, located by its ``family.field`` path."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


class CapabilityShapeError(ValueError):
    """A shape was refused. Carries every problem found, not only the first."""

    def __init__(self, problems: tuple[ShapeProblem, ...]) -> None:
        self.problems = problems
        super().__init__("; ".join(str(problem) for problem in problems))


@dataclass(frozen=True)
class FlatShape:
    """A shape flattened through a schema: quantities and attributes by flat name."""

    quantities: Mapping[str, int]
    attributes: Mapping[str, str]


def _is_scalar(value: Any) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, (str, int, bool))


def shape_structure_problems(shape: Any) -> tuple[ShapeProblem, ...]:
    """Every structural problem with ``shape``, needing no schema.

    A well-formed shape is a non-empty mapping of non-empty family names to
    non-empty mappings of non-empty field names to finite scalar values
    (string, integer, boolean, or finite number). ``None`` is not a value:
    a field a shape has no value for is omitted.
    """
    if not isinstance(shape, Mapping):
        return (ShapeProblem("", "a shape must be a mapping of family to fields"),)
    if not shape:
        return (ShapeProblem("", "a shape must name at least one family"),)
    problems: list[ShapeProblem] = []
    for family, fields in shape.items():
        if not isinstance(family, str) or not family:
            problems.append(ShapeProblem(repr(family), "a family name must be a non-empty string"))
            continue
        if not isinstance(fields, Mapping):
            problems.append(ShapeProblem(family, "a family must be a mapping of field to value"))
            continue
        if not fields:
            problems.append(ShapeProblem(family, "a family must name at least one field"))
            continue
        for field, value in fields.items():
            if not isinstance(field, str) or not field:
                problems.append(
                    ShapeProblem(f"{family}.{field!r}", "a field name must be a non-empty string")
                )
            elif not _is_scalar(value):
                problems.append(
                    ShapeProblem(f"{family}.{field}", f"a field value must be a scalar, not {value!r}")
                )
    return tuple(problems)


def _require_structure(shape: Any) -> None:
    problems = shape_structure_problems(shape)
    if problems:
        raise CapabilityShapeError(problems)


def shape_problems(shape: Any, schema: CapabilitySchema) -> tuple[ShapeProblem, ...]:
    """Every problem with ``shape`` under ``schema``; empty when it flattens."""
    structural = shape_structure_problems(shape)
    if structural:
        return structural
    problems: list[ShapeProblem] = []
    for family, fields in shape.items():
        for field, value in fields.items():
            definition = schema.lookup(family, field)
            path = f"{family}.{field}"
            if definition is None:
                problems.append(ShapeProblem(path, "is not defined by this schema"))
            elif definition.kind is FieldKind.QUANTITY:
                if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                    problems.append(ShapeProblem(path, f"must be a positive integer, not {value!r}"))
            elif not isinstance(value, str) or not value.strip():
                problems.append(ShapeProblem(path, f"must be a non-empty string, not {value!r}"))
    for definition in schema.fields:
        if definition.required and definition.field not in (shape.get(definition.family) or {}):
            problems.append(ShapeProblem(definition.path, "is required"))
    return tuple(problems)


def flatten_shape(shape: Any, schema: CapabilitySchema) -> FlatShape:
    """Flatten ``shape`` into quantities and attributes named by ``schema``.

    Raises ``CapabilityShapeError`` naming every offending ``family.field``
    path when the shape is malformed, names a family or field the schema does
    not define, omits a required field, or carries a value of the wrong kind.
    """
    problems = shape_problems(shape, schema)
    if problems:
        raise CapabilityShapeError(problems)
    quantities: dict[str, int] = {}
    attributes: dict[str, str] = {}
    for family, fields in shape.items():
        for field, value in fields.items():
            definition = schema.lookup(family, field)
            assert definition is not None  # guaranteed by shape_problems
            if definition.kind is FieldKind.QUANTITY:
                quantities[definition.flat_name] = value
            else:
                attributes[definition.flat_name] = value
    return FlatShape(
        quantities=MappingProxyType(quantities),
        attributes=MappingProxyType(attributes),
    )


def unflatten_shape(
    quantities: Mapping[str, Any],
    attributes: Mapping[str, Any],
    schema: CapabilitySchema,
) -> dict[str, dict[str, Any]]:
    """Build the family-grouped shape ``schema`` flattens to these flat values.

    The exact inverse of ``flatten_shape``: flattening the result returns
    ``quantities`` and ``attributes``. Raises ``CapabilityShapeError`` naming
    every flat name the schema does not define or defines as the other kind,
    and every problem ``shape_problems`` finds in the result, so a caller
    reading flat declarations gets the same refusals as one stating a shape.
    """
    by_flat_name = {field.flat_name: field for field in schema.fields}
    problems: list[ShapeProblem] = []
    shape: dict[str, dict[str, Any]] = {}
    for values, kind in (
        (quantities, FieldKind.QUANTITY),
        (attributes, FieldKind.ATTRIBUTE),
    ):
        for flat_name, value in values.items():
            definition = by_flat_name.get(flat_name)
            if definition is None:
                problems.append(ShapeProblem(str(flat_name), "is not defined by this schema"))
            elif definition.kind is not kind:
                problems.append(
                    ShapeProblem(str(flat_name), f"is a {definition.kind.value}, not a {kind.value}")
                )
            else:
                shape.setdefault(definition.family, {})[definition.field] = value
    if problems:
        raise CapabilityShapeError(tuple(problems))
    problems.extend(shape_problems(shape, schema))
    if problems:
        raise CapabilityShapeError(tuple(problems))
    return canonical_shape(shape)


def canonical_shape(shape: Any) -> dict[str, dict[str, Any]]:
    """A structurally valid shape as plain nested dicts in sorted key order."""
    _require_structure(shape)
    return {
        family: {field: shape[family][field] for field in sorted(shape[family])}
        for family in sorted(shape)
    }


def canonical_shape_json(shape: Any) -> str:
    """The canonical JSON text of a shape: sorted keys, no insignificant whitespace."""
    return json.dumps(
        canonical_shape(shape), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )


def shape_digest(shape: Any) -> str:
    """A domain-tagged digest of the shape's canonical family-grouped form.

    Independent of key order and of any schema's flat names.
    """
    payload = canonical_shape_json(shape).encode("utf-8")
    return SHAPE_DIGEST_PREFIX + hashlib.sha256(payload).hexdigest()


__all__ = [
    "SHAPE_DIGEST_PREFIX",
    "CapabilitySchema",
    "CapabilityShapeError",
    "FieldKind",
    "FlatShape",
    "ShapeField",
    "ShapeProblem",
    "canonical_shape",
    "canonical_shape_json",
    "flatten_shape",
    "shape_digest",
    "shape_problems",
    "shape_structure_problems",
    "unflatten_shape",
]
