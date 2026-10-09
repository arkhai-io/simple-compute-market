"""The shared capability-shape utility, with a schema local to these tests."""

from __future__ import annotations

import pytest

from market_capability_shape import (
    SHAPE_DIGEST_PREFIX,
    CapabilitySchema,
    CapabilityShapeError,
    FieldKind,
    ShapeField,
    canonical_shape,
    flatten_shape,
    shape_digest,
    shape_problems,
    shape_structure_problems,
    unflatten_shape,
)

SCHEMA = CapabilitySchema(
    fields=(
        ShapeField("widget", "count", FieldKind.QUANTITY, "widget_count", required=True),
        ShapeField("widget", "colour", FieldKind.ATTRIBUTE, "widget_colour", required=True),
        ShapeField("space", "units", FieldKind.QUANTITY, "space_units"),
    )
)


def _paths(problems) -> set[str]:
    return {problem.path for problem in problems}


# --- structure, without a schema --------------------------------------------


@pytest.mark.parametrize(
    "shape",
    [
        {"widget": {"count": 1}},
        {"widget": {"count": 1, "colour": "red"}, "anything": {"flag": True, "ratio": 0.5}},
    ],
)
def test_structure_accepts_well_formed_shapes(shape):
    assert shape_structure_problems(shape) == ()


@pytest.mark.parametrize(
    ("shape", "path"),
    [
        ([], ""),
        ({}, ""),
        ({"widget": 3}, "widget"),
        ({"widget": {}}, "widget"),
        ({"widget": {"count": [1]}}, "widget.count"),
        ({"widget": {"count": None}}, "widget.count"),
        ({"widget": {"count": float("nan")}}, "widget.count"),
        ({"widget": {"count": {"nested": 1}}}, "widget.count"),
    ],
)
def test_structure_refuses_malformed_shapes(shape, path):
    problems = shape_structure_problems(shape)
    assert problems and path in _paths(problems)


def test_structure_reports_every_problem_not_only_the_first():
    problems = shape_structure_problems({"a": 1, "b": {"x": None}})
    assert _paths(problems) == {"a", "b.x"}


# --- flattening with a schema -----------------------------------------------


def test_flatten_splits_quantities_and_attributes_by_flat_name():
    flat = flatten_shape({"widget": {"count": 2, "colour": "red"}, "space": {"units": 9}}, SCHEMA)
    assert dict(flat.quantities) == {"widget_count": 2, "space_units": 9}
    assert dict(flat.attributes) == {"widget_colour": "red"}


def test_an_optional_family_may_be_omitted():
    flat = flatten_shape({"widget": {"count": 1, "colour": "red"}}, SCHEMA)
    assert dict(flat.quantities) == {"widget_count": 1}


def test_a_missing_required_field_is_named():
    with pytest.raises(CapabilityShapeError) as refused:
        flatten_shape({"widget": {"count": 1}}, SCHEMA)
    assert _paths(refused.value.problems) == {"widget.colour"}


@pytest.mark.parametrize(
    ("shape", "path"),
    [
        ({"widget": {"count": 1, "colour": "red"}, "unknown": {"units": 1}}, "unknown.units"),
        ({"widget": {"count": 1, "colour": "red", "size": 3}}, "widget.size"),
    ],
)
def test_an_undefined_family_or_field_is_named(shape, path):
    assert path in _paths(shape_problems(shape, SCHEMA))


@pytest.mark.parametrize(
    ("value", "path"),
    [
        (True, "widget.count"),
        (0, "widget.count"),
        (-1, "widget.count"),
        (1.5, "widget.count"),
        ("1", "widget.count"),
    ],
)
def test_a_quantity_must_be_a_positive_integer(value, path):
    problems = shape_problems({"widget": {"count": value, "colour": "red"}}, SCHEMA)
    assert _paths(problems) == {path}


@pytest.mark.parametrize("value", ["", "   ", 3, True])
def test_an_attribute_must_be_a_non_empty_string(value):
    problems = shape_problems({"widget": {"count": 1, "colour": value}}, SCHEMA)
    assert _paths(problems) == {"widget.colour"}


def test_structural_problems_are_reported_before_schema_problems():
    assert _paths(shape_problems({"widget": 1}, SCHEMA)) == {"widget"}


def test_a_schema_refuses_ambiguous_definitions():
    with pytest.raises(ValueError):
        CapabilitySchema(
            fields=(
                ShapeField("a", "x", FieldKind.QUANTITY, "same"),
                ShapeField("b", "y", FieldKind.QUANTITY, "same"),
            )
        )
    with pytest.raises(ValueError):
        CapabilitySchema(
            fields=(
                ShapeField("a", "x", FieldKind.QUANTITY, "one"),
                ShapeField("a", "x", FieldKind.ATTRIBUTE, "two"),
            )
        )


# --- canonical form and digest ----------------------------------------------


def test_digest_is_stable_under_key_order():
    first = {"widget": {"count": 1, "colour": "red"}, "space": {"units": 4}}
    second = {"space": {"units": 4}, "widget": {"colour": "red", "count": 1}}
    assert canonical_shape(first) == canonical_shape(second)
    assert shape_digest(first) == shape_digest(second)
    assert shape_digest(first).startswith(SHAPE_DIGEST_PREFIX)


def test_digest_distinguishes_different_shapes():
    assert shape_digest({"widget": {"count": 1}}) != shape_digest({"widget": {"count": 2}})


def test_digest_is_unchanged_when_a_schema_renames_a_flat_name():
    shape = {"widget": {"count": 1, "colour": "red"}}
    renamed = CapabilitySchema(
        fields=(
            ShapeField("widget", "count", FieldKind.QUANTITY, "renamed_count", required=True),
            ShapeField("widget", "colour", FieldKind.ATTRIBUTE, "widget_colour", required=True),
        )
    )
    assert dict(flatten_shape(shape, renamed).quantities) == {"renamed_count": 1}
    # The digest takes no schema, so no flat name can reach it.
    assert shape_digest(shape) == shape_digest(dict(shape))


def test_digest_refuses_a_malformed_shape():
    with pytest.raises(CapabilityShapeError):
        shape_digest({"widget": {}})


# --- unflattening -------------------------------------------------------------


def test_unflatten_is_the_inverse_of_flatten():
    shape = {"widget": {"count": 3, "colour": "red"}, "space": {"units": 2}}
    flat = flatten_shape(shape, SCHEMA)

    rebuilt = unflatten_shape(flat.quantities, flat.attributes, SCHEMA)

    assert rebuilt == canonical_shape(shape)
    again = flatten_shape(rebuilt, SCHEMA)
    assert dict(again.quantities) == dict(flat.quantities)
    assert dict(again.attributes) == dict(flat.attributes)


def test_a_derived_shape_digests_as_the_same_shape_stated_by_hand():
    derived = unflatten_shape(
        {"space_units": 2, "widget_count": 3}, {"widget_colour": "red"}, SCHEMA
    )

    assert shape_digest(derived) == shape_digest(
        {"widget": {"colour": "red", "count": 3}, "space": {"units": 2}}
    )


@pytest.mark.parametrize(
    ("quantities", "attributes", "path"),
    [
        ({"widget_count": 1, "gadget_count": 1}, {"widget_colour": "red"}, "gadget_count"),
        ({"widget_count": 1}, {"widget_colour": "red", "shade": "dark"}, "shade"),
    ],
)
def test_unflatten_refuses_a_flat_name_the_schema_does_not_define(quantities, attributes, path):
    with pytest.raises(CapabilityShapeError) as refused:
        unflatten_shape(quantities, attributes, SCHEMA)

    assert path in _paths(refused.value.problems)


def test_unflatten_refuses_a_flat_name_supplied_as_the_other_kind():
    with pytest.raises(CapabilityShapeError) as refused:
        unflatten_shape({"widget_count": 1, "widget_colour": "red"}, {}, SCHEMA)

    assert "widget_colour" in _paths(refused.value.problems)


def test_unflatten_refuses_what_flattening_would_refuse():
    with pytest.raises(CapabilityShapeError) as refused:
        unflatten_shape({"widget_count": 0}, {}, SCHEMA)

    assert _paths(refused.value.problems) == {"widget.count", "widget.colour"}
