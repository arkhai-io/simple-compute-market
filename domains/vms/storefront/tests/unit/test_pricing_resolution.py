"""Unit tests for market_storefront.listings.pricing_resolution."""

from __future__ import annotations

from market_storefront.listings.pricing_resolution import (
    GpuPricingFields,
    resolve_gpu_pricing,
)

_FLAT_DEFAULT = GpuPricingFields(
    min_price="1.00",
    token="0xflat",
    max_duration_seconds=60,
    accepted_escrows="flat",
)
_NO_OVERRIDE = GpuPricingFields()


class TestResolveGpuPricing:
    def test_storefront_override_wins_for_every_field(self):
        override = GpuPricingFields(
            min_price="9.99",
            token="0xoverride",
            max_duration_seconds=7200,
            accepted_escrows="override",
        )
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"min_price": "5.00"}}}},
            gpu_model="H100",
            storefront_override=override,
            config_defaults_by_model={"H100": GpuPricingFields(min_price="3.00")},
            flat_default=_FLAT_DEFAULT,
        )
        assert result == override

    def test_pool_hint_used_when_no_storefront_override(self):
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"min_price": "5.00", "token": "0xhint"}}}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={"H100": GpuPricingFields(min_price="3.00")},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.min_price == "5.00"
        assert result.token == "0xhint"

    def test_config_per_model_default_used_when_no_override_or_hint(self):
        result = resolve_gpu_pricing(
            {},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={"H100": GpuPricingFields(min_price="3.00")},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.min_price == "3.00"
        # token has no per-model config default -- falls through to flat.
        assert result.token == "0xflat"

    def test_flat_default_used_as_last_resort(self):
        result = resolve_gpu_pricing(
            {},
            gpu_model="A100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result == _FLAT_DEFAULT

    def test_each_field_resolved_independently_across_tiers(self):
        """A storefront override that only sets one field must not block
        the others from falling through to lower tiers."""
        override = GpuPricingFields(min_price="9.99")  # only min_price set
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"token": "0xhint"}}}},
            gpu_model="H100",
            storefront_override=override,
            config_defaults_by_model={
                "H100": GpuPricingFields(max_duration_seconds=1800),
            },
            flat_default=_FLAT_DEFAULT,
        )
        assert result.min_price == "9.99"  # storefront override
        assert result.token == "0xhint"  # pool hint
        assert result.max_duration_seconds == 1800  # per-model config default
        assert result.accepted_escrows == "flat"  # flat fallback

    def test_hint_for_a_different_model_is_ignored(self):
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"A100": {"min_price": "3.00"}}}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.min_price == "1.00"  # flat default, not A100's hint

    def test_no_gpu_model_falls_straight_through_to_flat_default(self):
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"min_price": "5.00"}}}},
            gpu_model=None,
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={"H100": GpuPricingFields(min_price="3.00")},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.min_price == "1.00"

    def test_malformed_pricing_hint_is_ignored_not_raised(self):
        result = resolve_gpu_pricing(
            {"pricing": "not-a-mapping"},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result == _FLAT_DEFAULT

    def test_malformed_gpu_family_is_ignored_not_raised(self):
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": "not-a-mapping"}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result == _FLAT_DEFAULT

    def test_malformed_individual_min_price_field_falls_through(self):
        """A hint field with the wrong shape (a dict where a price
        string is expected) must not propagate into a commercial
        candidate -- falls through to the next tier the same way a
        missing field already does."""
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"min_price": {"oops": True}}}}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={"H100": GpuPricingFields(min_price="3.00")},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.min_price == "3.00"

    def test_malformed_max_duration_seconds_falls_through(self):
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"max_duration_seconds": "not-an-int"}}}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.max_duration_seconds == 60  # flat default

    def test_negative_max_duration_seconds_falls_through(self):
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"max_duration_seconds": -1}}}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.max_duration_seconds == 60  # flat default

    def test_bool_max_duration_seconds_falls_through(self):
        """bool is technically an int subtype -- explicitly rejected,
        matching this codebase's own established rule elsewhere
        (`kit/resource-pools/hints.py`'s hold-preference/SLA validators)."""
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"max_duration_seconds": True}}}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.max_duration_seconds == 60  # flat default

    def test_malformed_accepted_escrows_falls_through(self):
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"accepted_escrows": "not-a-list"}}}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.accepted_escrows == "flat"  # flat default

    def test_valid_fields_still_used_alongside_a_malformed_sibling_field(self):
        """One malformed field in the hint must not block the other,
        valid fields in that same hint from being used."""
        result = resolve_gpu_pricing(
            {
                "pricing": {
                    "gpu": {
                        "H100": {
                            "min_price": {"oops": True},  # malformed
                            "token": "0xhint",  # valid
                        },
                    },
                },
            },
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.min_price == "1.00"  # flat default (hint rejected)
        assert result.token == "0xhint"  # hint (valid)
