from __future__ import annotations

from market_resource_pools.hints import (
    LISTING_MODE_POLICY_TAG,
    MAX_RESERVATION_HOLD_SECONDS_POLICY_TAG,
    capped_hold_seconds,
    max_reservation_hold_seconds,
    raw_listing_mode,
    validate_hold_preference,
)


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
