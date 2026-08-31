from __future__ import annotations

import pytest

from market_resource_pools.hints import (
    DELIVERABLE_MODES_POLICY_TAG,
    LISTING_MODE_POLICY_TAG,
    MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG,
    PRICING_POLICY_TAG,
    REGION_POLICY_TAG,
    SLA_POLICY_TAG,
    capped_hold_seconds,
    declared_deliverable_modes,
    max_reservation_hold_seconds,
    pool_delivers_offering_mode,
    raw_listing_mode,
    raw_pricing,
    raw_region,
    sla_value,
    validate_deliverable_modes,
    validate_hold_preference,
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


class TestRawListingMode:
    def test_absent_returns_none(self):
        assert raw_listing_mode({}) is None

    def test_present_returned_unvalidated(self):
        """This package doesn't know which values a domain accepts --
        anything present is returned as-is, including nonsense, for the
        domain's own resolver to interpret."""
        assert raw_listing_mode({LISTING_MODE_POLICY_TAG: "not_a_real_mode"}) == (
            "not_a_real_mode"
        )
        assert raw_listing_mode({LISTING_MODE_POLICY_TAG: "fungible"}) == "fungible"


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
            {LISTING_MODE_POLICY_TAG: "whatever-a-domain-wants"},
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
            {LISTING_MODE_POLICY_TAG: "whatever-a-domain-wants"},
        ) == []
