from __future__ import annotations

import pytest

import market_resource_pools
from market_resource_pools.hints import (
    ADVERTISABLE_EXCEEDS_DELIVERABLE,
    ADVERTISABLE_MODES_POLICY_TAG,
    CAPACITY_BACKED,
    CAPACITY_BACKING_POLICY_TAG,
    CAPACITY_UNBACKED,
    DELIVERABLE_MODES_POLICY_TAG,
    DEPRECATED_LISTING_MODE_POLICY_TAG,
    INVALID_ADVERTISABLE_MODES,
    INVALID_CAPACITY_BACKING,
    INVALID_DELIVERABLE_MODES,
    LISTING_CARDINALITY_MODE_POLICY_TAG,
    MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG,
    MISSING_DECLARATION,
    PRICING_POLICY_TAG,
    REGION_POLICY_TAG,
    SLA_POLICY_TAG,
    UNBACKED_POOL_DELIVERS,
    MissingPoolDeclarationError,
    PoolDeclarationError,
    PoolDeclarations,
    capped_hold_seconds,
    declared_deliverable_modes,
    listing_cardinality_mode_source,
    max_reservation_hold_seconds,
    pool_declaration_problems,
    pool_delivers_offering_mode,
    raw_listing_cardinality_mode,
    raw_pricing,
    raw_region,
    resolve_pool_declarations,
    sla_value,
    validate_deliverable_modes,
    validate_hold_preference,
    validate_pool_declarations,
    validate_sla_preference,
)


class TestDeclaredDeliverableModes:
    def test_declared_set_resolves_without_interpreting_names(self):
        tags = {DELIVERABLE_MODES_POLICY_TAG: ["vm", "future.domain.v2"]}

        assert declared_deliverable_modes(tags) == frozenset(
            {"vm", "future.domain.v2"}
        )
        assert pool_delivers_offering_mode(tags, "vm") is True
        assert pool_delivers_offering_mode(tags, "bare_metal") is False

    def test_absent_and_explicit_empty_declarations_deliver_nothing(self):
        assert declared_deliverable_modes({}) == frozenset()
        assert declared_deliverable_modes(
            {DELIVERABLE_MODES_POLICY_TAG: []}
        ) == frozenset()
        assert pool_delivers_offering_mode({}, "vm") is False

    @pytest.mark.parametrize(
        "raw",
        [
            "vm",
            {"vm": True},
            ["vm", "vm"],
            ["vm", ""],
            [" vm"],
            ["vm", 1],
        ],
    )
    def test_malformed_declaration_is_rejected_by_reader_and_validator(self, raw):
        tags = {DELIVERABLE_MODES_POLICY_TAG: raw}

        with pytest.raises(ValueError, match=DELIVERABLE_MODES_POLICY_TAG):
            declared_deliverable_modes(tags)
        assert validate_deliverable_modes(tags)


class TestRawListingCardinalityMode:
    def test_absent_returns_none(self):
        assert raw_listing_cardinality_mode({}) is None

    def test_present_returned_unvalidated(self):
        """This package doesn't know which values a domain accepts --
        anything present is returned as-is, including nonsense, for the
        domain's own resolver to interpret."""
        assert raw_listing_cardinality_mode(
            {LISTING_CARDINALITY_MODE_POLICY_TAG: "not_a_real_mode"}
        ) == "not_a_real_mode"
        assert raw_listing_cardinality_mode(
            {LISTING_CARDINALITY_MODE_POLICY_TAG: "fungible"}
        ) == "fungible"

    def test_deprecated_key_is_read_when_settled_key_absent(self):
        """The concession that keeps an unupgraded producer's declaration
        from being read as absence, which would resolve to a structural
        default rather than erroring."""
        assert raw_listing_cardinality_mode(
            {DEPRECATED_LISTING_MODE_POLICY_TAG: "specific_resource"}
        ) == "specific_resource"

    def test_settled_key_wins_when_both_present(self):
        assert raw_listing_cardinality_mode({
            LISTING_CARDINALITY_MODE_POLICY_TAG: "fungible",
            DEPRECATED_LISTING_MODE_POLICY_TAG: "specific_resource",
        }) == "fungible"

    def test_falsy_settled_value_still_wins_over_deprecated(self):
        """Presence, not truthiness, decides precedence -- an empty
        declared value is a value the domain resolver must see and reject,
        not a reason to fall back to the other spelling."""
        assert raw_listing_cardinality_mode({
            LISTING_CARDINALITY_MODE_POLICY_TAG: "",
            DEPRECATED_LISTING_MODE_POLICY_TAG: "fungible",
        }) == ""


class TestListingCardinalityModeSource:
    def test_none_when_neither_key_present(self):
        assert listing_cardinality_mode_source({}) is None

    def test_names_the_settled_key(self):
        assert listing_cardinality_mode_source(
            {LISTING_CARDINALITY_MODE_POLICY_TAG: "fungible"}
        ) == LISTING_CARDINALITY_MODE_POLICY_TAG

    def test_names_the_deprecated_key(self):
        assert listing_cardinality_mode_source(
            {DEPRECATED_LISTING_MODE_POLICY_TAG: "fungible"}
        ) == DEPRECATED_LISTING_MODE_POLICY_TAG

    def test_names_the_settled_key_when_both_present(self):
        """Must agree with raw_listing_cardinality_mode's precedence, or a
        consumer would report a deprecation an operator cannot act on."""
        assert listing_cardinality_mode_source({
            LISTING_CARDINALITY_MODE_POLICY_TAG: "fungible",
            DEPRECATED_LISTING_MODE_POLICY_TAG: "specific_resource",
        }) == LISTING_CARDINALITY_MODE_POLICY_TAG


class TestMaxReservationHoldSeconds:
    def test_absent_returns_none(self):
        assert max_reservation_hold_seconds({}) is None

    def test_valid_nonnegative_int_returned(self):
        assert max_reservation_hold_seconds(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: 90},
        ) == 90

    def test_zero_is_valid(self):
        assert max_reservation_hold_seconds(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: 0},
        ) == 0

    def test_negative_returns_none(self):
        assert max_reservation_hold_seconds(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: -1},
        ) is None

    def test_non_int_returns_none(self):
        assert max_reservation_hold_seconds(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: "90"},
        ) is None
        assert max_reservation_hold_seconds(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: 90.5},
        ) is None

    def test_bool_returns_none(self):
        """bool is technically an int subtype in Python -- explicitly
        rejected since True/False is never a meaningful hold preference."""
        assert max_reservation_hold_seconds(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: True},
        ) is None


class TestCappedHoldSeconds:
    def test_caps_when_preference_lower(self):
        assert capped_hold_seconds(
            300, {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: 60},
        ) == 60.0

    def test_does_not_raise_requested_above_its_own_value(self):
        """Advisory upper bound only -- never raises the caller's own
        requested TTL even if the preference is larger."""
        assert capped_hold_seconds(
            30, {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: 300},
        ) == 30.0

    def test_falls_back_to_requested_when_absent(self):
        assert capped_hold_seconds(45, {}) == 45

    def test_falls_back_to_requested_when_invalid(self):
        """An invalid stored preference must never block hold placement --
        matches this hint's advisory, fail-open posture."""
        assert capped_hold_seconds(
            45, {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: -1},
        ) == 45


class TestValidateHoldPreference:
    def test_absent_is_valid(self):
        assert validate_hold_preference({}) == []

    def test_nonnegative_int_is_valid(self):
        assert validate_hold_preference(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: 120},
        ) == []

    def test_zero_is_valid(self):
        assert validate_hold_preference(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: 0},
        ) == []

    def test_negative_is_invalid(self):
        problems = validate_hold_preference(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: -1},
        )
        assert len(problems) == 1

    def test_fractional_is_invalid(self):
        problems = validate_hold_preference(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: 12.5},
        )
        assert len(problems) == 1

    def test_string_is_invalid(self):
        problems = validate_hold_preference(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: "120"},
        )
        assert len(problems) == 1

    def test_bool_is_invalid(self):
        problems = validate_hold_preference(
            {MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG: False},
        )
        assert len(problems) == 1

    def test_other_keys_do_not_affect_validity(self):
        assert validate_hold_preference(
            {LISTING_CARDINALITY_MODE_POLICY_TAG: "whatever-a-domain-wants"},
        ) == []


class TestRawRegion:
    def test_absent_returns_none(self):
        assert raw_region({}) is None

    def test_present_returned_unvalidated(self):
        assert raw_region({REGION_POLICY_TAG: "California, US"}) == "California, US"
        # No validity rule enforced here -- anything a domain wants to
        # interpret is passed through as-is.
        assert raw_region({REGION_POLICY_TAG: 12345}) == 12345


class TestRawPricing:
    def test_absent_returns_none(self):
        assert raw_pricing({}) is None

    def test_present_returned_unvalidated(self):
        pricing = {"gpu": {"H100": {"min_price": "5.00"}}}
        assert raw_pricing({PRICING_POLICY_TAG: pricing}) == pricing


class TestSlaValue:
    def test_absent_returns_none(self):
        assert sla_value({}) is None

    def test_valid_nonnegative_number_returned(self):
        assert sla_value({SLA_POLICY_TAG: 99.9}) == 99.9

    def test_valid_int_returned_as_float(self):
        assert sla_value({SLA_POLICY_TAG: 100}) == 100.0

    def test_zero_is_valid(self):
        assert sla_value({SLA_POLICY_TAG: 0}) == 0.0

    def test_negative_returns_none(self):
        assert sla_value({SLA_POLICY_TAG: -0.1}) is None

    def test_non_numeric_returns_none(self):
        assert sla_value({SLA_POLICY_TAG: "99.9"}) is None

    def test_bool_returns_none(self):
        assert sla_value({SLA_POLICY_TAG: True}) is None


class TestValidateSlaPreference:
    def test_absent_is_valid(self):
        assert validate_sla_preference({}) == []

    def test_nonnegative_number_is_valid(self):
        assert validate_sla_preference({SLA_POLICY_TAG: 99.9}) == []

    def test_zero_is_valid(self):
        assert validate_sla_preference({SLA_POLICY_TAG: 0}) == []

    def test_negative_is_invalid(self):
        assert len(validate_sla_preference({SLA_POLICY_TAG: -1})) == 1

    def test_string_is_invalid(self):
        assert len(validate_sla_preference({SLA_POLICY_TAG: "99.9"})) == 1

    def test_bool_is_invalid(self):
        assert len(validate_sla_preference({SLA_POLICY_TAG: False})) == 1

    def test_other_keys_do_not_affect_validity(self):
        assert validate_sla_preference(
            {LISTING_CARDINALITY_MODE_POLICY_TAG: "whatever-a-domain-wants"},
        ) == []


# ---------------------------------------------------------------------------
# Advertisement and backing declarations
# ---------------------------------------------------------------------------


def _tags(**overrides):
    tags = {
        DELIVERABLE_MODES_POLICY_TAG: ["vm"],
        ADVERTISABLE_MODES_POLICY_TAG: ["vm"],
        CAPACITY_BACKING_POLICY_TAG: CAPACITY_BACKED,
    }
    for key, value in overrides.items():
        if value is _ABSENT:
            tags.pop(key, None)
        else:
            tags[key] = value
    return tags


_ABSENT = object()


def _codes(tags):
    return {(problem.tag, problem.code) for problem in pool_declaration_problems(tags)}


class TestAdvertisableModes:
    def test_membership_is_offered_on_resolved_declarations_only(self):
        declarations = resolve_pool_declarations(_tags(**{
            DELIVERABLE_MODES_POLICY_TAG: ["vm", "future.domain.v2"],
            ADVERTISABLE_MODES_POLICY_TAG: ["vm", "future.domain.v2"],
        }))

        assert declarations.advertisable_modes == frozenset({"vm", "future.domain.v2"})
        assert declarations.advertises("vm") is True
        assert declarations.advertises("bare_metal") is False

    def test_explicit_empty_advertises_nothing(self):
        declarations = resolve_pool_declarations(
            _tags(**{ADVERTISABLE_MODES_POLICY_TAG: []}),
        )

        assert declarations.advertisable_modes == frozenset()
        assert declarations.advertises("vm") is False

    @pytest.mark.parametrize("mode", ["", "  ", None, 3])
    def test_blank_or_non_string_mode_is_never_advertised(self, mode):
        assert resolve_pool_declarations(_tags()).advertises(mode) is False

    def test_raw_membership_is_not_public(self):
        # Reading raw tags would treat an absent declaration as empty, the
        # distinction a reader of projected declarations must keep.
        assert not hasattr(market_resource_pools, "declared_advertisable_modes")
        assert not hasattr(market_resource_pools, "pool_advertises_offering_mode")

    @pytest.mark.parametrize(
        "raw",
        ["vm", {"vm": True}, ["vm", "vm"], ["vm", ""], [" vm"], ["vm", 1], None],
    )
    def test_malformed_declaration_is_rejected(self, raw):
        tags = _tags(**{ADVERTISABLE_MODES_POLICY_TAG: raw})

        assert (ADVERTISABLE_MODES_POLICY_TAG, INVALID_ADVERTISABLE_MODES) in _codes(tags)
        with pytest.raises(PoolDeclarationError, match=ADVERTISABLE_MODES_POLICY_TAG):
            resolve_pool_declarations(tags)

    def test_advertisement_is_independent_of_deliverable_shape_rule(self):
        # The shared shape rule is one helper; a malformed advertisable set
        # must not change how deliverable_modes reads.
        tags = _tags(**{ADVERTISABLE_MODES_POLICY_TAG: "vm"})

        assert declared_deliverable_modes(tags) == frozenset({"vm"})


class TestCapacityBacking:
    @pytest.mark.parametrize("value", [CAPACITY_BACKED, CAPACITY_UNBACKED])
    def test_recognized_values_are_valid(self, value):
        tags = _tags(**{CAPACITY_BACKING_POLICY_TAG: value})
        if value == CAPACITY_UNBACKED:
            tags[DELIVERABLE_MODES_POLICY_TAG] = []

        assert pool_declaration_problems(tags) == ()

    @pytest.mark.parametrize("value", ["Backed", "yes", "", None, True, 1, ["backed"]])
    def test_unrecognized_value_is_refused_not_defaulted(self, value):
        tags = _tags(**{CAPACITY_BACKING_POLICY_TAG: value})

        assert _codes(tags) == {(CAPACITY_BACKING_POLICY_TAG, INVALID_CAPACITY_BACKING)}


class TestRequiredDeclarations:
    @pytest.mark.parametrize(
        "tag", [ADVERTISABLE_MODES_POLICY_TAG, CAPACITY_BACKING_POLICY_TAG],
    )
    def test_each_absent_tag_is_a_named_problem(self, tag):
        tags = _tags(**{tag: _ABSENT})

        assert _codes(tags) == {(tag, MISSING_DECLARATION)}
        assert any(tag in message for message in validate_pool_declarations(tags))

    def test_both_absent_reports_both(self):
        assert _codes({}) == {
            (ADVERTISABLE_MODES_POLICY_TAG, MISSING_DECLARATION),
            (CAPACITY_BACKING_POLICY_TAG, MISSING_DECLARATION),
        }

    def test_explicit_empty_advertisement_is_a_declaration(self):
        tags = _tags(**{ADVERTISABLE_MODES_POLICY_TAG: []})

        assert pool_declaration_problems(tags) == ()


class TestCrossTagRules:
    def test_backed_pool_may_advertise_a_subset_of_what_it_delivers(self):
        tags = _tags(**{
            DELIVERABLE_MODES_POLICY_TAG: ["bare_metal", "vm"],
            ADVERTISABLE_MODES_POLICY_TAG: ["vm"],
        })

        assert pool_declaration_problems(tags) == ()

    def test_backed_pool_widening_advertisement_is_refused(self):
        tags = _tags(**{
            DELIVERABLE_MODES_POLICY_TAG: ["bare_metal"],
            ADVERTISABLE_MODES_POLICY_TAG: ["bare_metal", "vm"],
        })

        problems = pool_declaration_problems(tags)
        assert {(p.tag, p.code) for p in problems} == {
            (ADVERTISABLE_MODES_POLICY_TAG, ADVERTISABLE_EXCEEDS_DELIVERABLE),
        }
        assert "vm" in problems[0].message

    def test_backed_pool_narrowing_delivery_below_advertisement_is_refused(self):
        tags = _tags(**{DELIVERABLE_MODES_POLICY_TAG: []})

        assert _codes(tags) == {
            (ADVERTISABLE_MODES_POLICY_TAG, ADVERTISABLE_EXCEEDS_DELIVERABLE),
        }

    def test_backed_pool_with_absent_delivery_is_judged_as_empty(self):
        tags = _tags(**{DELIVERABLE_MODES_POLICY_TAG: _ABSENT})

        assert _codes(tags) == {
            (ADVERTISABLE_MODES_POLICY_TAG, ADVERTISABLE_EXCEEDS_DELIVERABLE),
        }

    def test_unbacked_pool_advertises_without_any_delivery_proof(self):
        tags = {
            ADVERTISABLE_MODES_POLICY_TAG: ["vm", "bare_metal"],
            CAPACITY_BACKING_POLICY_TAG: CAPACITY_UNBACKED,
        }

        assert pool_declaration_problems(tags) == ()
        assert resolve_pool_declarations(tags) == PoolDeclarations(
            frozenset({"vm", "bare_metal"}), CAPACITY_UNBACKED,
        )

    def test_unbacked_pool_that_delivers_is_refused(self):
        tags = {
            DELIVERABLE_MODES_POLICY_TAG: ["vm"],
            ADVERTISABLE_MODES_POLICY_TAG: ["vm"],
            CAPACITY_BACKING_POLICY_TAG: CAPACITY_UNBACKED,
        }

        assert _codes(tags) == {(DELIVERABLE_MODES_POLICY_TAG, UNBACKED_POOL_DELIVERS)}

    def test_malformed_delivery_is_reported_instead_of_cross_tag_rules(self):
        # One owner of the whole invariant: the parse failure is the problem,
        # and the cross-tag rules are not judged against a set that did not
        # parse.
        tags = _tags(**{DELIVERABLE_MODES_POLICY_TAG: "vm"})

        assert _codes(tags) == {(DELIVERABLE_MODES_POLICY_TAG, INVALID_DELIVERABLE_MODES)}
        assert validate_deliverable_modes(tags)

    def test_malformed_backing_suppresses_cross_tag_rules(self):
        tags = _tags(**{
            CAPACITY_BACKING_POLICY_TAG: "maybe",
            DELIVERABLE_MODES_POLICY_TAG: [],
        })

        assert _codes(tags) == {(CAPACITY_BACKING_POLICY_TAG, INVALID_CAPACITY_BACKING)}


class TestResolvePoolDeclarations:
    def test_valid_declarations_resolve(self):
        resolved = resolve_pool_declarations(_tags())

        assert resolved == PoolDeclarations(frozenset({"vm"}), CAPACITY_BACKED)
        assert resolved.backed is True

    def test_absence_is_reported_distinctly_and_never_defaulted(self):
        with pytest.raises(MissingPoolDeclarationError) as exc_info:
            resolve_pool_declarations({DELIVERABLE_MODES_POLICY_TAG: ["vm"]})

        assert {p.code for p in exc_info.value.problems} == {MISSING_DECLARATION}

    def test_one_absent_tag_is_still_absence(self):
        with pytest.raises(MissingPoolDeclarationError):
            resolve_pool_declarations(_tags(**{ADVERTISABLE_MODES_POLICY_TAG: _ABSENT}))

    @pytest.mark.parametrize(
        "overrides",
        [
            {CAPACITY_BACKING_POLICY_TAG: "yes"},
            {ADVERTISABLE_MODES_POLICY_TAG: ["vm", "vm"]},
            {ADVERTISABLE_MODES_POLICY_TAG: ["vm", "bare_metal"]},
            {DELIVERABLE_MODES_POLICY_TAG: "vm"},
            {
                CAPACITY_BACKING_POLICY_TAG: CAPACITY_UNBACKED,
                DELIVERABLE_MODES_POLICY_TAG: ["vm"],
            },
        ],
    )
    def test_malformed_or_inconsistent_declarations_fail_closed(self, overrides):
        with pytest.raises(PoolDeclarationError) as exc_info:
            resolve_pool_declarations(_tags(**overrides))

        assert not isinstance(exc_info.value, MissingPoolDeclarationError)

    def test_absent_plus_malformed_is_malformed(self):
        tags = {
            DELIVERABLE_MODES_POLICY_TAG: ["vm"],
            CAPACITY_BACKING_POLICY_TAG: "maybe",
        }

        with pytest.raises(PoolDeclarationError) as exc_info:
            resolve_pool_declarations(tags)

        assert not isinstance(exc_info.value, MissingPoolDeclarationError)
        assert {p.code for p in exc_info.value.problems} == {
            MISSING_DECLARATION, INVALID_CAPACITY_BACKING,
        }

    def test_malformed_delivery_is_reported_by_the_resolver(self):
        with pytest.raises(PoolDeclarationError) as exc_info:
            resolve_pool_declarations(_tags(**{DELIVERABLE_MODES_POLICY_TAG: "vm"}))

        assert {p.code for p in exc_info.value.problems} == {INVALID_DELIVERABLE_MODES}


class TestListingShapesHint:
    """Structure only: the reading domain owns the vocabulary."""

    SHAPE = {"gpu": {"count": 1, "model": "H100"}, "memory": {"gib": 64}}

    def test_absent_is_valid(self):
        assert market_resource_pools.validate_listing_shapes({}) == []

    def test_valid_shapes_are_accepted(self):
        tags = {"listing_shapes": {"vm": [self.SHAPE, {"gpu": {"count": 2, "model": "H100"}}]}}
        assert market_resource_pools.validate_listing_shapes(tags) == []

    def test_a_field_no_domain_defines_is_accepted(self):
        tags = {"listing_shapes": {"vm": [{"gpu": {"count": 1, "flux_capacitor": "yes"}}]}}
        assert market_resource_pools.validate_listing_shapes(tags) == []

    @pytest.mark.parametrize(
        ("value", "fragment"),
        [
            ([], "must be a mapping"),
            ({"vm": []}, "listing_shapes.vm must be a non-empty list"),
            ({"vm": {"gpu": {"count": 1}}}, "listing_shapes.vm must be a non-empty list"),
            ({"vm": [{"gpu": 1}]}, "listing_shapes.vm[0].gpu"),
            ({"vm": [{"gpu": {"count": [1]}}]}, "listing_shapes.vm[0].gpu.count"),
            ({"": [SHAPE]}, "offering modes must be non-empty strings"),
        ],
    )
    def test_malformed_values_are_refused_with_their_location(self, value, fragment):
        problems = market_resource_pools.validate_listing_shapes({"listing_shapes": value})
        assert problems and any(fragment in problem for problem in problems), problems

    def test_raw_read_returns_the_mode_list_unvalidated(self):
        tags = {"listing_shapes": {"vm": [{"anything": {"x": 1}}], "container": [self.SHAPE]}}
        assert market_resource_pools.raw_listing_shapes(tags, "vm") == [{"anything": {"x": 1}}]
        assert market_resource_pools.raw_listing_shapes(tags, "bare_metal") is None
        assert market_resource_pools.raw_listing_shapes({}, "vm") is None
        assert market_resource_pools.raw_listing_shapes({"listing_shapes": "x"}, "vm") is None
