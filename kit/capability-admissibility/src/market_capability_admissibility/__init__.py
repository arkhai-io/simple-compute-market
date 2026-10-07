"""Capability shape admissibility: which shapes a seller will sell for a listing.

A stated listing shape may give any quantity field a constraint mapping in
place of its scalar:

    {"gpu": {"model": "H100", "count": {"offer": 1, "min": 1, "max": 4}},
     "memory": {"gib": {"max": 512}}}

``offer`` is what the listing sells and is carried by its base shape; ``min``
and ``max`` bound what an agreed shape may state for the field. A plain scalar
is shorthand for ``{"offer": v}``, and an offer alone constrains nothing. A
constraint-only declaration, such as a storefront's configured default, uses
the same field syntax without ``offer``.

This kit is the only reader of a constraint. Callers hold a ``Declaration``
and a ``ResolvedPolicy`` as opaque values and obtain a listing's base shape
from the kit. Evaluation takes whole shapes and never returns a range for a
dimension independent of the rest of the shape: a static ``min``/``max`` per
field is a box, but a seller's policy may later couple dimensions, and a
caller that compared numbers itself would encode the box. The values one
dimension may take are answered only for a given partial shape.

A shape is admissible exactly when it can be completed to an admissible shape,
so a dimension a shape omits never makes it inadmissible by its absence.

The kit knows no family or field name: a domain supplies its
``CapabilitySchema``. It imports only the standard library and the shape kit,
so storefronts, buyers, and pool administration can all depend on it. See
openspec/specs/market-composition/spec.md.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from market_capability_shape import (
    CapabilitySchema,
    FieldKind,
    ShapeProblem,
    canonical_shape,
    shape_digest,
    shape_problems,
    shape_structure_problems,
)

OFFER = "offer"
MIN = "min"
MAX = "max"
_LISTING_KEYS = (OFFER, MIN, MAX)
_DECLARATION_KEYS = (MIN, MAX)

_Path = tuple[str, str]


class ProblemCode(str, Enum):
    """Why a shape, declaration, or resolution was refused."""

    MALFORMED_SHAPE = "malformed_shape"
    """A shape, or a listing's base shape, cannot be read under the schema."""
    MALFORMED_DECLARATION = "malformed_declaration"
    """A constraint-only declaration is not a mapping of family to fields."""
    EMPTY_CONSTRAINT = "empty_constraint"
    """A constraint mapping states no key."""
    UNKNOWN_CONSTRAINT_KEY = "unknown_constraint_key"
    """A constraint mapping holds a key this kit does not define."""
    OFFER_IN_DECLARATION = "offer_in_declaration"
    """A constraint-only declaration states an offer."""
    INVALID_CONSTRAINT_VALUE = "invalid_constraint_value"
    """An ``offer``, ``min``, or ``max`` is not a positive integer."""
    INVERTED_RANGE = "inverted_range"
    """A constraint mapping states ``min`` above ``max``."""
    OFFER_OUTSIDE_RANGE = "offer_outside_range"
    """A constraint mapping's ``offer`` lies outside its own range."""
    NOT_A_QUANTITY = "not_a_quantity"
    """A constraint, or a requested dimension, names no quantity of the schema."""
    CONFLICTING_DUPLICATE = "conflicting_duplicate"
    """A stated list states one base shape with different constraints."""
    EMPTY_RANGE = "empty_range"
    """Merged tiers leave a field no admissible value."""
    BELOW_MINIMUM = "below_minimum"
    """A shape states a quantity below the resolved minimum."""
    ABOVE_MAXIMUM = "above_maximum"
    """A shape states a quantity above the resolved maximum."""


@dataclass(frozen=True)
class TierBound:
    """One tier's bound on a field, named by an empty-range problem."""

    tier: str
    bound: str
    value: int


@dataclass(frozen=True)
class AdmissibilityProblem:
    """One reason a shape, declaration, or resolution was refused.

    ``paths`` names every ``family.field`` path the problem involves, so a
    constraint relating several dimensions names all of them; it is empty for
    a problem with the whole document. ``tier`` is the label of the
    declaration the problem is about, or of the tier that set a violated
    bound; it is ``None`` for a problem with an evaluated shape itself.
    ``entries`` names the positions in a stated list the problem concerns,
    and ``bounds`` each tier's conflicting value for an empty range.
    """

    paths: tuple[str, ...]
    code: ProblemCode
    message: str
    tier: str | None
    entries: tuple[int, ...] = ()
    bounds: tuple[TierBound, ...] = ()

    def __str__(self) -> str:
        where = ", ".join(self.paths)
        return f"{where}: {self.message}" if where else self.message


class AdmissibilityRequestError(ValueError):
    """A question the kit cannot answer. Carries every problem found."""

    def __init__(self, problems: tuple[AdmissibilityProblem, ...]) -> None:
        self.problems = problems
        super().__init__("; ".join(str(problem) for problem in problems))


@dataclass(frozen=True, repr=False)
class Declaration:
    """One tier's parsed constraints. Opaque: only this kit reads it."""

    _tier: str
    _bounds: Mapping[_Path, Mapping[str, int]]

    def __repr__(self) -> str:
        return f"Declaration(tier={self._tier!r})"


@dataclass(frozen=True)
class _Leaf:
    minimum: int | None = None
    minimum_tier: str | None = None
    maximum: int | None = None
    maximum_tier: str | None = None


class AdmissibleValues:
    """The values one dimension may take given one partial shape.

    Answers questions rather than exposing its representation, so a later
    constraint that produces steps or gaps changes no caller. An answer is
    valid only for the partial shape it was computed from. Every
    value-returning accessor answers ``None`` on an empty set, so check
    ``is_empty`` first.
    """

    __slots__ = ("_low", "_high")

    def __init__(self, low: int | None, high: int | None) -> None:
        # ``low`` is None only for the empty set; ``high`` is None when unbounded.
        self._low = low
        self._high = high

    @property
    def is_empty(self) -> bool:
        return self._low is None

    def contains(self, value: int) -> bool:
        if self._low is None or not _is_positive_int(value):
            return False
        return value >= self._low and (self._high is None or value <= self._high)

    def at_most(self, value: int) -> int | None:
        """The greatest admissible value not above ``value``."""
        if self._low is None or value < self._low:
            return None
        return value if self._high is None else min(value, self._high)

    def at_least(self, value: int) -> int | None:
        """The least admissible value not below ``value``."""
        if self._low is None:
            return None
        candidate = max(value, self._low)
        if self._high is not None and candidate > self._high:
            return None
        return candidate

    @property
    def minimum(self) -> int | None:
        return self._low

    @property
    def maximum(self) -> int | None:
        """The greatest admissible value, or ``None`` when unbounded or empty."""
        return None if self._low is None else self._high

    def __repr__(self) -> str:
        return "AdmissibleValues(<opaque>)"


class ResolvedPolicy:
    """One listing's merged constraints under one schema. Opaque.

    Built only by ``resolve``. It keeps the schema it was resolved with.
    """

    __slots__ = ("_schema", "_open_schema", "_leaves")

    def __init__(self, schema: CapabilitySchema, leaves: Mapping[_Path, _Leaf]) -> None:
        self._schema = schema
        # The schema with no field required: admissibility judges the
        # dimensions a shape states, and a required field is the domain's to
        # check, so a partial shape is not malformed for omitting one.
        self._open_schema = CapabilitySchema(
            fields=tuple(dataclasses.replace(field, required=False) for field in schema.fields)
        )
        self._leaves = dict(leaves)

    def __repr__(self) -> str:
        return "ResolvedPolicy(<opaque>)"

    def admissibility_problems(self, shape: Any) -> tuple[AdmissibilityProblem, ...]:
        """Every problem with ``shape``; empty when it is admissible.

        A shape malformed under the schema is reported as problems; the
        schema's required fields are not checked. A field the shape omits
        never violates. Each bound violation names the tier that set it.
        """
        malformed = shape_problems(shape, self._open_schema)
        if malformed:
            return _shape_kit_problems(malformed, tier=None)
        return tuple(self._violations(shape))

    def admissible_values(self, dimension: str, partial_shape: Any) -> AdmissibleValues:
        """The values ``dimension`` may take given ``partial_shape``.

        Those ``v`` for which the partial shape, with the dimension set to
        ``v``, can still be completed to an admissible shape. Dimensions the
        partial shape omits are free, a value it states for ``dimension`` is
        ignored, and ``{}`` states nothing. Fixing dimensions one at a time,
        in any order, each to a value from the current answer, never empties
        a later answer and ends at an admissible shape.

        Raises ``AdmissibilityRequestError`` when ``dimension`` is not a
        quantity the schema defines or ``partial_shape`` is malformed under
        the schema, so an empty answer always means a well-formed partial
        shape with no completion.
        """
        path = self._quantity_path(dimension)
        rest = _without_field(partial_shape, path)
        if not (isinstance(rest, Mapping) and not rest):
            malformed = shape_problems(rest, self._open_schema)
            if malformed:
                raise AdmissibilityRequestError(_shape_kit_problems(malformed, tier=None))
            if any(True for _ in self._violations(rest)):
                return AdmissibleValues(None, None)
        leaf = self._leaves.get(path, _Leaf())
        return AdmissibleValues(leaf.minimum or 1, leaf.maximum)

    def _quantity_path(self, dimension: Any) -> _Path:
        if isinstance(dimension, str):
            family, separator, field = dimension.partition(".")
            definition = self._schema.lookup(family, field) if separator else None
            if definition is not None and definition.kind is FieldKind.QUANTITY:
                return family, field
        raise AdmissibilityRequestError(
            (
                AdmissibilityProblem(
                    paths=(str(dimension),),
                    code=ProblemCode.NOT_A_QUANTITY,
                    message="is not a quantity this schema defines",
                    tier=None,
                ),
            )
        )

    def _violations(self, shape: Mapping[str, Mapping[str, Any]]):
        for family in sorted(shape):
            for field in sorted(shape[family]):
                leaf = self._leaves.get((family, field))
                if leaf is None:
                    continue
                value = shape[family][field]
                path = f"{family}.{field}"
                if leaf.minimum is not None and value < leaf.minimum:
                    yield AdmissibilityProblem(
                        paths=(path,),
                        code=ProblemCode.BELOW_MINIMUM,
                        message=f"{value} is below the minimum {leaf.minimum}",
                        tier=leaf.minimum_tier,
                    )
                if leaf.maximum is not None and value > leaf.maximum:
                    yield AdmissibilityProblem(
                        paths=(path,),
                        code=ProblemCode.ABOVE_MAXIMUM,
                        message=f"{value} is above the maximum {leaf.maximum}",
                        tier=leaf.maximum_tier,
                    )


@dataclass(frozen=True)
class ShapeSplit:
    """A stated listing shape split into its base shape and its constraints.

    When ``base_problems`` is empty, ``base_shape`` is the canonical base
    shape and exactly one of ``declaration`` and ``constraint_problems`` is
    set. When the base shape cannot be read, ``base_shape`` and
    ``declaration`` are ``None`` and no constraint is judged. ``entries``
    names the positions in a stated list this split stands for.
    """

    base_shape: dict[str, dict[str, Any]] | None
    declaration: Declaration | None
    base_problems: tuple[AdmissibilityProblem, ...]
    constraint_problems: tuple[AdmissibilityProblem, ...]
    entries: tuple[int, ...] = ()

    @property
    def problems(self) -> tuple[AdmissibilityProblem, ...]:
        return self.base_problems + self.constraint_problems


@dataclass(frozen=True)
class ShapeListSplit:
    """A stated list split entry by entry.

    ``shapes`` holds one split per distinct base shape, in the order the list
    first states it, and one per entry whose base shape cannot be read.
    Entries identical in base shape and constraints are one split; a base
    shape stated with different constraints is one split carrying a
    ``CONFLICTING_DUPLICATE`` problem and no declaration.
    """

    shapes: tuple[ShapeSplit, ...]

    @property
    def base_problems(self) -> tuple[AdmissibilityProblem, ...]:
        return tuple(problem for split in self.shapes for problem in split.base_problems)

    @property
    def problems(self) -> tuple[AdmissibilityProblem, ...]:
        return tuple(problem for split in self.shapes for problem in split.problems)


@dataclass(frozen=True)
class DeclarationParse:
    """A parsed constraint-only declaration, or every problem with it."""

    declaration: Declaration | None
    problems: tuple[AdmissibilityProblem, ...]


@dataclass(frozen=True)
class Resolution:
    """A resolved policy, or every problem that prevented one."""

    policy: ResolvedPolicy | None
    problems: tuple[AdmissibilityProblem, ...]


def split_listing_shape(
    raw: Any, *, tier: str, schema: CapabilitySchema | None = None
) -> ShapeSplit:
    """Split one stated listing shape into its base shape and its constraints.

    The base shape holds every field's committed value: scalars as stated,
    constrained fields reduced to their ``offer``, constraint-only fields
    omitted. It is read first, structurally without a schema and under the
    schema given one; a base shape that cannot be read is reported with no
    declaration, including when a constraint-only mapping removed a required
    field. Only a readable base shape has its constraints judged. Given a
    schema, every constrained path must also be a quantity it defines.
    """
    _require_tier(tier)
    return _split(raw, tier=tier, schema=schema, entries=())


def split_listing_shapes(
    raw_list: Sequence[Any], *, tier: str, schema: CapabilitySchema | None = None
) -> ShapeListSplit:
    """Split a stated list of listing shapes entry by entry.

    Each entry splits as ``split_listing_shape`` splits it. Entries whose
    base shapes share the shape kit's digest are compared by their
    constraints, which needs no schema: identical entries collapse to one,
    and different constraints are reported naming each conflicting entry.
    Every reader of a stated list calls this rather than comparing entries.
    """
    _require_tier(tier)
    if isinstance(raw_list, (str, bytes)) or not isinstance(raw_list, Sequence):
        raise TypeError("a stated list of listing shapes must be a sequence")
    groups: dict[str, list[int]] = {}
    order: list[tuple[int, str | None]] = []
    first_splits: dict[int, ShapeSplit] = {}
    for index, raw in enumerate(raw_list):
        split = _split(raw, tier=tier, schema=schema, entries=(index,))
        if split.base_problems:
            order.append((index, None))
            first_splits[index] = split
            continue
        assert split.base_shape is not None
        digest = shape_digest(split.base_shape)
        if digest not in groups:
            groups[digest] = []
            order.append((index, digest))
        groups[digest].append(index)
    shapes: list[ShapeSplit] = []
    for index, digest in order:
        if digest is None:
            shapes.append(first_splits[index])
        else:
            shapes.append(_split_group(raw_list, groups[digest], tier=tier, schema=schema))
    return ShapeListSplit(shapes=tuple(shapes))


def parse_declaration(
    raw: Any, *, tier: str, schema: CapabilitySchema | None = None
) -> DeclarationParse:
    """Parse a constraint-only declaration: listing-shape syntax with no ``offer``.

    A mapping of family to a mapping of field to a constraint mapping holding
    ``min``, ``max``, or both. An empty mapping, or an empty family, states no
    constraint. Given a schema, every path must be a quantity it defines.
    """
    _require_tier(tier)

    def problem(paths: tuple[str, ...], code: ProblemCode, message: str) -> AdmissibilityProblem:
        return AdmissibilityProblem(paths=paths, code=code, message=message, tier=tier)

    if not isinstance(raw, Mapping):
        return DeclarationParse(
            None,
            (problem((), ProblemCode.MALFORMED_DECLARATION, "a declaration must be a mapping of family to fields"),),
        )
    problems: list[AdmissibilityProblem] = []
    bounds: dict[_Path, dict[str, int]] = {}
    for family, fields in raw.items():
        if not isinstance(family, str) or not family:
            problems.append(
                problem((repr(family),), ProblemCode.MALFORMED_DECLARATION, "a family name must be a non-empty string")
            )
            continue
        if not isinstance(fields, Mapping):
            problems.append(
                problem((family,), ProblemCode.MALFORMED_DECLARATION, "a family must be a mapping of field to constraints")
            )
            continue
        for field, value in fields.items():
            if not isinstance(field, str) or not field:
                problems.append(
                    problem(
                        (f"{family}.{field!r}",),
                        ProblemCode.MALFORMED_DECLARATION,
                        "a field name must be a non-empty string",
                    )
                )
                continue
            path = f"{family}.{field}"
            if not isinstance(value, Mapping):
                problems.append(
                    problem(
                        (path,),
                        ProblemCode.OFFER_IN_DECLARATION,
                        f"a declaration states constraints, not an offer; {value!r} is an offer",
                    )
                )
                continue
            if schema is not None and not _is_quantity(schema, family, field):
                problems.append(_not_a_quantity(path, tier=tier))
                continue
            found = _constraint_problems(path, value, allowed=_DECLARATION_KEYS, tier=tier)
            if found:
                problems.extend(found)
            elif any(key in value for key in _DECLARATION_KEYS):
                bounds[(family, field)] = {key: value[key] for key in _DECLARATION_KEYS if key in value}
    if problems:
        return DeclarationParse(None, tuple(problems))
    return DeclarationParse(Declaration(tier, bounds), ())


def resolve(declarations: Sequence[Declaration], schema: CapabilitySchema) -> Resolution:
    """Merge ``declarations``, given highest tier first, into one policy.

    For each field's ``min`` and ``max``, the highest tier stating it wins,
    and a tier that does not state one leaves a lower tier's value in place.
    A merged ``min`` above the merged ``max`` is an empty range, reported
    naming each tier and its value. Every path must be a quantity ``schema``
    defines. On any problem no policy is returned.
    """
    if isinstance(declarations, Declaration) or not isinstance(declarations, Sequence):
        raise TypeError("declarations must be a sequence, highest tier first")
    for declaration in declarations:
        if not isinstance(declaration, Declaration):
            raise TypeError(f"{declaration!r} is not a Declaration")
    problems: list[AdmissibilityProblem] = []
    # Each leaf records the value and the rank of the tier that set it; a
    # lower rank is a higher tier. Applying lowest first lets higher overwrite.
    leaves: dict[_Path, dict[str, tuple[int, int, str]]] = {}
    for rank in reversed(range(len(declarations))):
        declaration = declarations[rank]
        for (family, field), stated in declaration._bounds.items():
            if not _is_quantity(schema, family, field):
                problems.append(_not_a_quantity(f"{family}.{field}", tier=declaration._tier))
                continue
            for bound, value in stated.items():
                leaves.setdefault((family, field), {})[bound] = (value, rank, declaration._tier)
    resolved: dict[_Path, _Leaf] = {}
    for (family, field), bounds in leaves.items():
        low, high = bounds.get(MIN), bounds.get(MAX)
        if low is not None and high is not None and low[0] > high[0]:
            higher = low if low[1] < high[1] else high
            problems.append(
                AdmissibilityProblem(
                    paths=(f"{family}.{field}",),
                    code=ProblemCode.EMPTY_RANGE,
                    message=(
                        f"min {low[0]} from {low[2]} is above max {high[0]} from {high[2]}"
                    ),
                    tier=higher[2],
                    bounds=(TierBound(low[2], MIN, low[0]), TierBound(high[2], MAX, high[0])),
                )
            )
            continue
        resolved[(family, field)] = _Leaf(
            minimum=None if low is None else low[0],
            minimum_tier=None if low is None else low[2],
            maximum=None if high is None else high[0],
            maximum_tier=None if high is None else high[2],
        )
    if problems:
        return Resolution(None, tuple(problems))
    return Resolution(ResolvedPolicy(schema, resolved), ())


def _split(
    raw: Any, *, tier: str, schema: CapabilitySchema | None, entries: tuple[int, ...]
) -> ShapeSplit:
    base, constrained = _separate(raw)
    base_problems = (
        shape_structure_problems(base) if schema is None else shape_problems(base, schema)
    )
    if base_problems:
        return ShapeSplit(
            base_shape=None,
            declaration=None,
            base_problems=_shape_kit_problems(base_problems, tier=tier, entries=entries),
            constraint_problems=(),
            entries=entries,
        )
    problems: list[AdmissibilityProblem] = []
    bounds: dict[_Path, dict[str, int]] = {}
    for (family, field), mapping in constrained.items():
        path = f"{family}.{field}"
        if schema is not None and not _is_quantity(schema, family, field):
            problems.append(_not_a_quantity(path, tier=tier, entries=entries))
            continue
        found = _constraint_problems(path, mapping, allowed=_LISTING_KEYS, tier=tier, entries=entries)
        if found:
            problems.extend(found)
        elif any(key in mapping for key in _DECLARATION_KEYS):
            bounds[(family, field)] = {key: mapping[key] for key in _DECLARATION_KEYS if key in mapping}
    return ShapeSplit(
        base_shape=canonical_shape(base),
        declaration=None if problems else Declaration(tier, bounds),
        base_problems=(),
        constraint_problems=tuple(problems),
        entries=entries,
    )


def _separate(raw: Any) -> tuple[Any, dict[_Path, Mapping[Any, Any]]]:
    """The base shape ``raw`` states, and each constraint mapping by path.

    Anything that is not a well-named constraint mapping is left in the base
    shape unchanged, so the shape kit reports it where it stands.
    """
    if not isinstance(raw, Mapping):
        return raw, {}
    base: dict[Any, Any] = {}
    constrained: dict[_Path, Mapping[Any, Any]] = {}
    for family, fields in raw.items():
        if not isinstance(family, str) or not isinstance(fields, Mapping) or not fields:
            base[family] = fields
            continue
        kept: dict[Any, Any] = {}
        for field, value in fields.items():
            if isinstance(field, str) and field and isinstance(value, Mapping):
                constrained[(family, field)] = value
                if OFFER in value:
                    kept[field] = value[OFFER]
            else:
                kept[field] = value
        # A family whose every field constrains without offering is omitted.
        if kept:
            base[family] = kept
    return base, constrained


def _split_group(
    raw_list: Sequence[Any],
    indices: list[int],
    *,
    tier: str,
    schema: CapabilitySchema | None,
) -> ShapeSplit:
    """One split for every entry stating one base shape.

    Every entry is split on its own, so an entry whose constraints cannot be
    read is reported whichever position it holds; entries compare equal only
    when each also splits cleanly.
    """
    splits = {
        index: _split(raw_list[index], tier=tier, schema=schema, entries=(index,))
        for index in indices
    }
    own = tuple(problem for index in indices for problem in splits[index].constraint_problems)
    every = tuple(indices)
    by_signature: dict[tuple[Any, ...], list[int]] = {}
    for index in indices:
        by_signature.setdefault(_constraint_signature(raw_list[index]), []).append(index)
    if len(by_signature) == 1:
        first = splits[indices[0]]
        return ShapeSplit(
            base_shape=first.base_shape,
            declaration=None if own else first.declaration,
            base_problems=(),
            constraint_problems=own,
            entries=every,
        )
    stated = [dict(signature) for signature in by_signature]
    differing = sorted(
        path
        for path in {path for constraints in stated for path in constraints}
        if len({constraints.get(path) for constraints in stated}) > 1
    )
    conflict = AdmissibilityProblem(
        paths=tuple(differing),
        code=ProblemCode.CONFLICTING_DUPLICATE,
        message=(
            "one base shape is stated by entries "
            + ", ".join(str(index) for index in every)
            + " with different constraints"
        ),
        tier=tier,
        entries=every,
    )
    return ShapeSplit(
        base_shape=splits[indices[0]].base_shape,
        declaration=None,
        base_problems=(),
        constraint_problems=(conflict, *own),
        entries=every,
    )


def _constraint_signature(raw: Mapping[str, Mapping[Any, Any]]) -> tuple[Any, ...]:
    """What an entry states beyond its base shape, comparable without a schema.

    A mapping holding only ``offer`` states nothing beyond its base shape, as
    the scalar it is shorthand for does; every other mapping, empty or
    malformed, is part of what the entry states.
    """
    _, constrained = _separate(raw)
    signature = []
    for (family, field), mapping in constrained.items():
        stated = tuple(sorted((repr(key), repr(value)) for key, value in mapping.items() if key != OFFER))
        if stated or not mapping:
            signature.append((f"{family}.{field}", stated))
    return tuple(sorted(signature))


def _constraint_problems(
    path: str,
    mapping: Mapping[Any, Any],
    *,
    allowed: tuple[str, ...],
    tier: str,
    entries: tuple[int, ...] = (),
) -> list[AdmissibilityProblem]:
    def problem(code: ProblemCode, message: str) -> AdmissibilityProblem:
        return AdmissibilityProblem(
            paths=(path,), code=code, message=message, tier=tier, entries=entries
        )

    if not mapping:
        return [
            problem(
                ProblemCode.EMPTY_CONSTRAINT,
                f"a constraint mapping must state at least one of {', '.join(allowed)}",
            )
        ]
    problems: list[AdmissibilityProblem] = []
    unknown = sorted(repr(key) for key in mapping if key not in _LISTING_KEYS)
    if unknown:
        problems.append(
            problem(ProblemCode.UNKNOWN_CONSTRAINT_KEY, f"unknown constraint keys {', '.join(unknown)}")
        )
    if OFFER in mapping and OFFER not in allowed:
        problems.append(problem(ProblemCode.OFFER_IN_DECLARATION, "a declaration states no offer"))
    readable: dict[str, int] = {}
    for key in allowed:
        if key not in mapping:
            continue
        if _is_positive_int(mapping[key]):
            readable[key] = mapping[key]
        else:
            problems.append(
                problem(
                    ProblemCode.INVALID_CONSTRAINT_VALUE,
                    f"{key} must be a positive integer, not {mapping[key]!r}",
                )
            )
    low, high, offer = readable.get(MIN), readable.get(MAX), readable.get(OFFER)
    if low is not None and high is not None and low > high:
        problems.append(problem(ProblemCode.INVERTED_RANGE, f"min {low} is above max {high}"))
    elif offer is not None and (
        (low is not None and offer < low) or (high is not None and offer > high)
    ):
        problems.append(
            problem(ProblemCode.OFFER_OUTSIDE_RANGE, f"offer {offer} lies outside its own range")
        )
    return problems


def _without_field(partial_shape: Any, path: _Path) -> Any:
    """``partial_shape`` without the field at ``path``; anything else unchanged."""
    family, field = path
    if not isinstance(partial_shape, Mapping):
        return partial_shape
    fields = partial_shape.get(family)
    if not isinstance(fields, Mapping) or field not in fields:
        return partial_shape
    rest = {key: value for key, value in partial_shape.items() if key != family}
    remaining = {key: value for key, value in fields.items() if key != field}
    if remaining:
        rest[family] = remaining
    return rest


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_quantity(schema: CapabilitySchema, family: str, field: str) -> bool:
    definition = schema.lookup(family, field)
    return definition is not None and definition.kind is FieldKind.QUANTITY


def _not_a_quantity(
    path: str, *, tier: str, entries: tuple[int, ...] = ()
) -> AdmissibilityProblem:
    return AdmissibilityProblem(
        paths=(path,),
        code=ProblemCode.NOT_A_QUANTITY,
        message="constraints apply only to a quantity this schema defines",
        tier=tier,
        entries=entries,
    )


def _shape_kit_problems(
    problems: tuple[ShapeProblem, ...], *, tier: str | None, entries: tuple[int, ...] = ()
) -> tuple[AdmissibilityProblem, ...]:
    return tuple(
        AdmissibilityProblem(
            paths=(problem.path,) if problem.path else (),
            code=ProblemCode.MALFORMED_SHAPE,
            message=problem.message,
            tier=tier,
            entries=entries,
        )
        for problem in problems
    )


def _require_tier(tier: Any) -> None:
    if not isinstance(tier, str) or not tier:
        raise ValueError(f"a tier label must be a non-empty string, not {tier!r}")


__all__ = [
    "AdmissibilityProblem",
    "AdmissibilityRequestError",
    "AdmissibleValues",
    "Declaration",
    "DeclarationParse",
    "ProblemCode",
    "ResolvedPolicy",
    "Resolution",
    "ShapeListSplit",
    "ShapeSplit",
    "TierBound",
    "parse_declaration",
    "resolve",
    "split_listing_shape",
    "split_listing_shapes",
]
