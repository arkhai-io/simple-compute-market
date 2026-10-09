"""Capability shape admissibility, against a schema local to these tests.

The schema names no compute vocabulary, so every case here also shows the kit
behaving as it does for any domain's schema.
"""

from __future__ import annotations

import itertools
import math
import random
from fractions import Fraction

import pytest
from market_capability_admissibility import (
    AdmissibilityRequestError,
    Declaration,
    ProblemCode,
    ResolvedPolicy,
    TierBound,
    parse_declaration,
    resolve,
    split_listing_shape,
    split_listing_shapes,
)
from market_capability_shape import CapabilitySchema, FieldKind, ShapeField

SCHEMA = CapabilitySchema(
    fields=(
        ShapeField("widget", "count", FieldKind.QUANTITY, "widget_count", required=True),
        ShapeField("widget", "colour", FieldKind.ATTRIBUTE, "widget_colour", required=True),
        ShapeField("space", "units", FieldKind.QUANTITY, "space_units"),
        ShapeField("power", "watts", FieldKind.QUANTITY, "power_watts"),
    )
)


def _declaration(raw, *, tier="listing", schema=SCHEMA) -> Declaration:
    parsed = parse_declaration(raw, tier=tier, schema=schema)
    assert parsed.problems == (), parsed.problems
    assert parsed.declaration is not None
    return parsed.declaration


def _policy(*raw_tiers) -> ResolvedPolicy:
    """A policy from constraint-only declarations, highest tier first."""
    declarations = [
        _declaration(raw, tier=f"tier{rank}") for rank, raw in enumerate(raw_tiers)
    ]
    resolution = resolve(declarations, SCHEMA)
    assert resolution.problems == (), resolution.problems
    assert resolution.policy is not None
    return resolution.policy


def _listing_policy(raw_shape, *lower_tiers) -> ResolvedPolicy:
    split = split_listing_shape(raw_shape, tier="listing", schema=SCHEMA)
    assert split.problems == (), split.problems
    declarations = [split.declaration] + [
        _declaration(raw, tier=f"default{rank}") for rank, raw in enumerate(lower_tiers)
    ]
    resolution = resolve(declarations, SCHEMA)
    assert resolution.problems == (), resolution.problems
    return resolution.policy


def _codes(problems) -> list[ProblemCode]:
    return [problem.code for problem in problems]


# --- evaluation -------------------------------------------------------------


def test_a_shape_outside_one_bound_names_that_path_and_the_tier_that_set_it():
    policy = _policy({"widget": {"count": {"max": 4}}}, {"space": {"units": {"min": 2, "max": 10}}})

    problems = policy.admissibility_problems(
        {"widget": {"count": 5, "colour": "red"}, "space": {"units": 3}}
    )

    assert len(problems) == 1
    assert problems[0].paths == ("widget.count",)
    assert problems[0].code is ProblemCode.ABOVE_MAXIMUM
    assert problems[0].tier == "tier0"


def test_a_shape_below_a_minimum_names_the_tier_that_set_the_minimum():
    policy = _policy({"space": {"units": {"max": 10}}}, {"space": {"units": {"min": 2}}})

    (problem,) = policy.admissibility_problems({"space": {"units": 1}})

    assert problem.code is ProblemCode.BELOW_MINIMUM
    assert problem.tier == "tier1"


def test_a_shape_inside_every_bound_has_no_problems():
    policy = _policy({"widget": {"count": {"min": 1, "max": 4}}, "space": {"units": {"max": 10}}})

    assert policy.admissibility_problems({"widget": {"count": 4, "colour": "red"}, "space": {"units": 10}}) == ()


def test_a_shape_omitting_a_bounded_field_is_admissible():
    policy = _policy({"space": {"units": {"min": 8}}})

    assert policy.admissibility_problems({"widget": {"count": 1, "colour": "red"}}) == ()


def test_required_fields_are_not_checked_by_evaluation():
    policy = _policy({"space": {"units": {"max": 8}}})

    assert policy.admissibility_problems({"space": {"units": 2}}) == ()


@pytest.mark.parametrize(
    "shape",
    [
        [],
        {"widget": {"count": "two"}},
        {"widget": {"count": 0}},
        {"nowhere": {"count": 1}},
        {"widget": {"colour": 3}},
    ],
)
def test_a_malformed_shape_is_reported_as_problems(shape):
    policy = _policy({"widget": {"count": {"max": 4}}})

    problems = policy.admissibility_problems(shape)

    assert problems
    assert set(_codes(problems)) == {ProblemCode.MALFORMED_SHAPE}


def test_admissible_values_for_one_dimension_are_its_resolved_range():
    policy = _policy({"widget": {"count": {"min": 2, "max": 6}}, "space": {"units": {"max": 10}}})

    values = policy.admissible_values("widget.count", {"widget": {"colour": "red"}, "space": {"units": 4}})

    assert not values.is_empty
    assert [v for v in range(0, 9) if values.contains(v)] == [2, 3, 4, 5, 6]
    assert (values.minimum, values.maximum) == (2, 6)
    assert values.at_most(5) == 5
    assert values.at_most(9) == 6
    assert values.at_most(1) is None
    assert values.at_least(1) == 2
    assert values.at_least(7) is None


@pytest.mark.parametrize(
    "threshold",
    [-3, 0, 1, 1.5, 2, 3.5, Fraction(7, 2), 4, 4.0001, 6, 6.5, 7, 10**9 + 0.5],
)
def test_every_accessor_answer_is_a_member_of_the_set(threshold):
    values = _policy({"widget": {"count": {"min": 2, "max": 6}}}).admissible_values("widget.count", {})

    for answer in (values.at_most(threshold), values.at_least(threshold)):
        assert answer is None or (type(answer) is int and values.contains(answer))


def test_a_non_integral_threshold_answers_the_nearest_member_on_its_side():
    values = _policy({"widget": {"count": {"min": 2, "max": 6}}}).admissible_values("widget.count", {})

    assert values.at_most(3.5) == 3
    assert values.at_least(3.5) == 4


@pytest.mark.parametrize(
    ("threshold", "error"),
    [(True, TypeError), ("3", TypeError), (None, TypeError), (math.inf, ValueError), (math.nan, ValueError)],
)
def test_an_accessor_refuses_a_threshold_that_is_not_a_finite_real_number(threshold, error):
    values = _policy({"widget": {"count": {"max": 6}}}).admissible_values("widget.count", {})

    with pytest.raises(error):
        values.at_most(threshold)
    with pytest.raises(error):
        values.at_least(threshold)


def test_admissible_values_ignore_a_value_stated_for_the_dimension_itself():
    policy = _policy({"widget": {"count": {"max": 6}}})

    values = policy.admissible_values("widget.count", {"widget": {"count": 99, "colour": "red"}})

    assert (values.minimum, values.maximum) == (1, 6)


def test_an_unbounded_dimension_has_no_maximum():
    policy = _policy({"widget": {"count": {"min": 3}}})

    values = policy.admissible_values("widget.count", {})

    assert values.minimum == 3
    assert values.maximum is None
    assert values.contains(10**9)
    assert values.at_most(10**9) == 10**9


def test_admissible_values_from_an_empty_partial_shape_are_the_resolved_range():
    policy = _policy({"space": {"units": {"min": 2, "max": 5}}})

    values = policy.admissible_values("space.units", {})

    assert (values.minimum, values.maximum) == (2, 5)


def test_an_already_inadmissible_partial_shape_has_no_admissible_values():
    policy = _policy({"widget": {"count": {"max": 4}}, "space": {"units": {"max": 10}}})

    values = policy.admissible_values("space.units", {"widget": {"count": 5}})

    assert values.is_empty
    assert not values.contains(1)
    assert values.at_most(5) is None
    assert values.at_least(1) is None
    assert values.minimum is None
    assert values.maximum is None


@pytest.mark.parametrize("dimension", ["widget.colour", "widget.size", "nowhere.count", "widget", ""])
def test_values_for_a_path_that_is_not_a_quantity_raise_naming_it(dimension):
    policy = _policy({"widget": {"count": {"max": 4}}})

    with pytest.raises(AdmissibilityRequestError) as raised:
        policy.admissible_values(dimension, {})

    (problem,) = raised.value.problems
    assert problem.paths == (dimension,)
    assert problem.code is ProblemCode.NOT_A_QUANTITY


@pytest.mark.parametrize(
    "partial_shape",
    [None, {"widget": {"count": "two"}}, {"widget": {}}, {"nowhere": {"x": 1}}],
)
def test_values_given_a_malformed_partial_shape_raise(partial_shape):
    policy = _policy({"space": {"units": {"max": 4}}})

    with pytest.raises(AdmissibilityRequestError) as raised:
        policy.admissible_values("space.units", partial_shape)

    assert raised.value.problems
    assert set(_codes(raised.value.problems)) == {ProblemCode.MALFORMED_SHAPE}


def test_evaluation_values_do_not_expose_contents():
    policy = _policy({"space": {"units": {"max": 4}}})

    assert "4" not in repr(policy)
    assert "4" not in repr(policy.admissible_values("space.units", {}))
    assert "4" not in repr(_declaration({"space": {"units": {"max": 4}}}))


# --- the one-dimension-at-a-time guarantee ----------------------------------

_QUANTITIES = ("widget.count", "space.units", "power.watts")


def _random_policy(rng: random.Random) -> ResolvedPolicy:
    tiers = []
    for _ in range(rng.randint(0, 3)):
        tier: dict[str, dict[str, dict[str, int]]] = {}
        for path in _QUANTITIES:
            bounds = {}
            low = rng.randint(1, 6)
            if rng.random() < 0.5:
                bounds["min"] = low
            if rng.random() < 0.5:
                bounds["max"] = low + rng.randint(0, 6)
            if bounds:
                family, field = path.split(".")
                tier.setdefault(family, {})[field] = bounds
        tiers.append(tier)
    declarations = [_declaration(raw, tier=f"t{rank}") for rank, raw in enumerate(tiers)]
    resolution = resolve(declarations, SCHEMA)
    # Random tiers may merge to an empty range; those policies do not exist.
    return resolution.policy


def test_a_counter_shape_built_one_dimension_at_a_time_never_dead_ends():
    rng = random.Random(20261007)
    checked = 0
    while checked < 200:
        policy = _random_policy(rng)
        if policy is None:
            continue
        checked += 1
        for order in itertools.permutations(_QUANTITIES):
            shape: dict[str, dict[str, int]] = {}
            for dimension in order:
                values = policy.admissible_values(dimension, shape)
                assert not values.is_empty, (order, shape)
                choice = rng.choice(
                    [values.minimum, values.at_most(rng.randint(1, 20)) or values.minimum]
                )
                assert values.contains(choice)
                family, field = dimension.split(".")
                shape.setdefault(family, {})[field] = choice
            assert policy.admissibility_problems(shape) == (), (order, shape)


# --- resolution -------------------------------------------------------------


def test_tiers_merge_per_field():
    policy = _policy({"space": {"units": {"max": 4}}}, {"space": {"units": {"min": 2, "max": 16}}})

    values = policy.admissible_values("space.units", {})

    assert (values.minimum, values.maximum) == (2, 4)


def test_a_higher_tier_may_widen_a_lower_tiers_bound():
    policy = _policy({"space": {"units": {"max": 32}}}, {"space": {"units": {"max": 16}}})

    assert policy.admissible_values("space.units", {}).maximum == 32


def test_a_higher_tier_omitting_a_bound_keeps_the_lower_tiers():
    policy = _policy({"widget": {"count": {"max": 4}}}, {"space": {"units": {"min": 2, "max": 8}}})

    values = policy.admissible_values("space.units", {})

    assert (values.minimum, values.maximum) == (2, 8)


def test_tiers_merging_to_an_empty_range_name_the_field_and_each_tier():
    listing = _declaration({"space": {"units": {"max": 4}}}, tier="listing")
    default = _declaration({"space": {"units": {"min": 8}}}, tier="configured_default")

    resolution = resolve([listing, default], SCHEMA)

    assert resolution.policy is None
    (problem,) = resolution.problems
    assert problem.code is ProblemCode.EMPTY_RANGE
    assert problem.paths == ("space.units",)
    assert set(problem.bounds) == {
        TierBound("configured_default", "min", 8),
        TierBound("listing", "max", 4),
    }
    assert "listing" in problem.message and "configured_default" in problem.message


def test_no_declarations_resolve_to_a_policy_constraining_nothing():
    resolution = resolve([], SCHEMA)

    assert resolution.policy.admissibility_problems({"space": {"units": 10**6}}) == ()


def test_resolution_refuses_a_path_that_is_not_a_quantity_of_its_schema():
    split = split_listing_shape(
        {"widget": {"count": 1, "colour": "red"}, "thing": {"size": {"max": 3}}}, tier="hint"
    )
    assert split.problems == ()

    resolution = resolve([split.declaration], SCHEMA)

    assert resolution.policy is None
    (problem,) = resolution.problems
    assert (problem.code, problem.paths, problem.tier) == (ProblemCode.NOT_A_QUANTITY, ("thing.size",), "hint")


def test_resolution_takes_declarations_only():
    with pytest.raises(TypeError):
        resolve([{"space": {"units": {"max": 4}}}], SCHEMA)


# --- splitting a stated listing shape ---------------------------------------


def test_scalars_are_kept_and_constrained_fields_reduce_to_their_offer():
    split = split_listing_shape(
        {
            "widget": {"colour": "red", "count": {"offer": 1, "min": 1, "max": 4}},
            "space": {"units": 16},
            "power": {"watts": {"max": 512}},
        },
        tier="hint",
        schema=SCHEMA,
    )

    assert split.problems == ()
    assert split.base_shape == {"space": {"units": 16}, "widget": {"colour": "red", "count": 1}}
    assert isinstance(split.declaration, Declaration)


def test_a_field_constraining_without_offering_is_omitted_and_bounds_a_shape_stating_it():
    policy = _listing_policy(
        {"widget": {"count": 1, "colour": "red"}, "power": {"watts": {"max": 512}}}
    )

    assert policy.admissibility_problems({"widget": {"count": 1, "colour": "red"}}) == ()
    (problem,) = policy.admissibility_problems({"power": {"watts": 513}})
    assert problem.paths == ("power.watts",)
    assert problem.tier == "listing"


def test_an_offer_alone_does_not_constrain():
    split = split_listing_shape(
        {"widget": {"count": 1, "colour": "red"}, "space": {"units": 16}}, tier="hint", schema=SCHEMA
    )
    policy = resolve([split.declaration], SCHEMA).policy

    assert split.base_shape["space"] == {"units": 16}
    assert policy.admissibility_problems({"space": {"units": 3}}) == ()


def test_an_offer_mapping_is_the_scalar_it_is_shorthand_for():
    scalar = split_listing_shape({"widget": {"count": 2, "colour": "red"}}, tier="hint", schema=SCHEMA)
    mapping = split_listing_shape(
        {"widget": {"count": {"offer": 2}, "colour": "red"}}, tier="hint", schema=SCHEMA
    )

    assert scalar.base_shape == mapping.base_shape
    assert scalar.declaration == mapping.declaration


def test_a_fixed_value_is_a_range_equal_to_the_offer():
    policy = _listing_policy({"widget": {"count": {"offer": 2, "min": 2, "max": 2}, "colour": "red"}})

    assert policy.admissibility_problems({"widget": {"count": 2}}) == ()
    assert policy.admissibility_problems({"widget": {"count": 3}})


@pytest.mark.parametrize("schema", [None, SCHEMA])
def test_a_field_carrying_an_unknown_key_is_a_constraint_problem(schema):
    split = split_listing_shape(
        {"widget": {"count": {"offer": 1, "step": 2}, "colour": "red"}}, tier="hint", schema=schema
    )

    assert split.declaration is None
    assert split.base_problems == ()
    (problem,) = split.constraint_problems
    assert (problem.code, problem.paths, problem.tier) == (
        ProblemCode.UNKNOWN_CONSTRAINT_KEY,
        ("widget.count",),
        "hint",
    )


@pytest.mark.parametrize(
    "raw",
    [
        {"widget": {"count": 1, "colour": {"offer": "red"}}},
        {"widget": {"count": 1, "colour": "red"}, "thing": {"size": {"max": 3}}},
        {"widget": {"count": 1, "colour": "red", "size": {"min": 2}}},
    ],
)
def test_a_constraint_on_an_attribute_or_an_undefined_field_is_a_constraint_problem(raw):
    split = split_listing_shape(raw, tier="hint", schema=SCHEMA)

    assert split.base_problems == ()
    assert split.declaration is None
    assert _codes(split.constraint_problems) == [ProblemCode.NOT_A_QUANTITY]


@pytest.mark.parametrize("schema", [None, SCHEMA])
@pytest.mark.parametrize("mapping", [{"offer": 5, "max": 4}, {"offer": 1, "min": 2}])
def test_an_offer_outside_its_own_range_is_a_constraint_problem(schema, mapping):
    split = split_listing_shape({"widget": {"count": mapping, "colour": "red"}}, tier="hint", schema=schema)

    assert split.declaration is None
    assert _codes(split.constraint_problems) == [ProblemCode.OFFER_OUTSIDE_RANGE]


@pytest.mark.parametrize("schema", [None, SCHEMA])
def test_an_empty_constraint_mapping_is_a_constraint_problem_naming_its_path(schema):
    split = split_listing_shape(
        {"widget": {"count": 1, "colour": "red"}, "space": {"units": {}}}, tier="hint", schema=schema
    )

    assert split.base_problems == ()
    (problem,) = split.constraint_problems
    assert (problem.code, problem.paths) == (ProblemCode.EMPTY_CONSTRAINT, ("space.units",))


@pytest.mark.parametrize(
    ("mapping", "code"),
    [
        ({"offer": 1, "max": 0}, ProblemCode.INVALID_CONSTRAINT_VALUE),
        ({"offer": 1, "max": True}, ProblemCode.INVALID_CONSTRAINT_VALUE),
        ({"offer": 1, "max": 2.0}, ProblemCode.INVALID_CONSTRAINT_VALUE),
        ({"offer": 1, "min": "1"}, ProblemCode.INVALID_CONSTRAINT_VALUE),
        ({"min": 4, "max": 2}, ProblemCode.INVERTED_RANGE),
    ],
)
def test_constraint_values_are_positive_integers_in_order(mapping, code):
    split = split_listing_shape(
        {"widget": {"count": 1, "colour": "red"}, "space": {"units": mapping}}, tier="hint", schema=SCHEMA
    )

    assert _codes(split.constraint_problems) == [code]


def test_without_a_schema_an_unreadable_offer_is_a_constraint_problem():
    split = split_listing_shape({"widget": {"count": {"offer": 0, "max": 4}}}, tier="hint")

    assert split.base_problems == ()
    assert _codes(split.constraint_problems) == [ProblemCode.INVALID_CONSTRAINT_VALUE]


def test_with_a_schema_an_unreadable_offer_is_a_base_shape_problem():
    split = split_listing_shape(
        {"widget": {"count": {"offer": 0, "max": 4}, "colour": "red"}}, tier="hint", schema=SCHEMA
    )

    assert split.base_shape is None
    assert split.declaration is None
    assert _codes(split.base_problems) == [ProblemCode.MALFORMED_SHAPE]
    assert split.constraint_problems == ()


@pytest.mark.parametrize(
    "raw",
    [
        {"widget": {"count": {"min": 2}, "colour": "red"}},
        {"widget": {"count": 1, "colour": {"max": 4}}},
    ],
)
def test_a_constraint_removing_a_required_field_is_a_base_shape_problem(raw):
    split = split_listing_shape(raw, tier="hint", schema=SCHEMA)

    assert split.declaration is None
    assert split.constraint_problems == ()
    (problem,) = split.base_problems
    assert problem.code is ProblemCode.MALFORMED_SHAPE
    assert "required" in problem.message
    assert problem.tier == "hint"


@pytest.mark.parametrize(
    "raw",
    [None, [], {}, {"power": {"watts": {"max": 4}}}, {"widget": {}}, {"widget": {"count": [1]}}],
)
def test_a_base_shape_that_is_not_a_shape_has_no_declaration(raw):
    split = split_listing_shape(raw, tier="hint")

    assert split.base_shape is None
    assert split.declaration is None
    assert split.base_problems


def test_a_tier_label_is_required():
    with pytest.raises(ValueError):
        split_listing_shape({"widget": {"count": 1}}, tier="")


# --- splitting a stated list ------------------------------------------------


@pytest.mark.parametrize("schema", [None, SCHEMA])
def test_a_list_stating_one_base_shape_with_different_constraints_names_both_entries(schema):
    split = split_listing_shapes(
        [
            {"widget": {"count": {"offer": 1, "max": 4}, "colour": "red"}},
            {"widget": {"count": 8, "colour": "red"}},
            {"widget": {"count": {"offer": 1, "max": 8}, "colour": "red"}},
        ],
        tier="hint",
        schema=schema,
    )

    first, second = split.shapes
    assert first.base_shape == {"widget": {"colour": "red", "count": 1}}
    assert first.declaration is None
    (conflict,) = first.constraint_problems
    assert conflict.code is ProblemCode.CONFLICTING_DUPLICATE
    assert conflict.entries == (0, 2)
    assert conflict.paths == ("widget.count",)
    assert second.entries == (1,)
    assert second.declaration is not None


def test_a_list_repeating_an_identical_entry_yields_it_once():
    split = split_listing_shapes(
        [
            {"widget": {"count": {"offer": 1, "max": 4}, "colour": "red"}},
            {"widget": {"colour": "red", "count": {"max": 4, "offer": 1}}},
        ],
        tier="hint",
        schema=SCHEMA,
    )

    (only,) = split.shapes
    assert split.problems == ()
    assert only.entries == (0, 1)
    assert only.declaration is not None


def test_a_scalar_and_its_offer_mapping_are_identical_entries():
    split = split_listing_shapes(
        [{"widget": {"count": 1, "colour": "red"}}, {"widget": {"count": {"offer": 1}, "colour": "red"}}],
        tier="hint",
    )

    (only,) = split.shapes
    assert split.problems == ()


@pytest.mark.parametrize(
    ("entries", "schema", "code"),
    [
        (
            [{"widget": {"count": 1, "colour": "red"}}, {"widget": {"count": 1, "colour": {"offer": "red"}}}],
            SCHEMA,
            ProblemCode.NOT_A_QUANTITY,
        ),
        ([{"widget": {"count": 0}}, {"widget": {"count": {"offer": 0}}}], None, ProblemCode.INVALID_CONSTRAINT_VALUE),
    ],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_an_unreadable_offer_mapping_is_reported_whatever_its_position(entries, schema, code, reverse):
    ordered = list(reversed(entries)) if reverse else entries
    malformed = 0 if reverse else 1

    split = split_listing_shapes(ordered, tier="hint", schema=schema)

    (only,) = split.shapes
    assert only.declaration is None
    (problem,) = only.constraint_problems
    assert problem.code is code
    assert problem.entries == (malformed,)
    assert only.entries == (0, 1)


def test_an_empty_constraint_mapping_differs_from_stating_nothing():
    split = split_listing_shapes(
        [
            {"widget": {"count": 1, "colour": "red"}, "space": {"units": {}}},
            {"widget": {"count": 1, "colour": "red"}},
        ],
        tier="hint",
    )

    (only,) = split.shapes
    assert _codes(only.constraint_problems) == [
        ProblemCode.CONFLICTING_DUPLICATE,
        ProblemCode.EMPTY_CONSTRAINT,
    ]


def test_an_entry_with_an_unreadable_base_shape_is_reported_in_place():
    split = split_listing_shapes(
        [{"widget": {"count": 1, "colour": "red"}}, {"widget": {"count": {"min": 2}}}, {"widget": {"count": 3, "colour": "red"}}],
        tier="hint",
        schema=SCHEMA,
    )

    assert [shape.entries for shape in split.shapes] == [(0,), (1,), (2,)]
    (problem,) = split.base_problems
    assert problem.entries == (1,)
    assert split.shapes[1].base_shape is None


def test_a_list_must_be_a_sequence():
    with pytest.raises(TypeError):
        split_listing_shapes({"widget": {"count": 1}}, tier="hint")


# --- constraint-only declarations ------------------------------------------


def test_a_declaration_uses_listing_syntax_without_an_offer():
    parsed = parse_declaration(
        {"widget": {"count": {"min": 1, "max": 16}}, "power": {"watts": {"max": 512}}},
        tier="configured_default",
        schema=SCHEMA,
    )

    assert parsed.problems == ()
    assert isinstance(parsed.declaration, Declaration)


@pytest.mark.parametrize("raw", [{}, {"widget": {}}])
def test_an_empty_declaration_constrains_nothing(raw):
    declaration = _declaration(raw)

    policy = resolve([declaration], SCHEMA).policy
    assert policy.admissible_values("widget.count", {}).maximum is None


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ({"widget": {"count": {"offer": 1, "max": 4}}}, ProblemCode.OFFER_IN_DECLARATION),
        ({"widget": {"count": 4}}, ProblemCode.OFFER_IN_DECLARATION),
        ({"widget": {"count": {"max": 4, "step": 2}}}, ProblemCode.UNKNOWN_CONSTRAINT_KEY),
        ({"widget": {"count": {"min": 5, "max": 4}}}, ProblemCode.INVERTED_RANGE),
        ({"widget": {"count": {"max": -1}}}, ProblemCode.INVALID_CONSTRAINT_VALUE),
        ({"widget": {"count": {}}}, ProblemCode.EMPTY_CONSTRAINT),
        ({"widget": {"colour": {"max": 4}}}, ProblemCode.NOT_A_QUANTITY),
        ({"thing": {"size": {"max": 4}}}, ProblemCode.NOT_A_QUANTITY),
        ({"widget": 3}, ProblemCode.MALFORMED_DECLARATION),
        ([], ProblemCode.MALFORMED_DECLARATION),
    ],
)
def test_a_malformed_declaration_has_no_declaration(raw, code):
    parsed = parse_declaration(raw, tier="configured_default", schema=SCHEMA)

    assert parsed.declaration is None
    assert _codes(parsed.problems) == [code]
    assert parsed.problems[0].tier == "configured_default"
