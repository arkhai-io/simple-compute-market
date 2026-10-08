"""Unit tests for arkhai_vms_listings.pricing_resolution."""

from __future__ import annotations

import pytest
from arkhai_vms_listings.pricing_resolution import (
    GpuPricingFields,
    configured_family_rate_problems,
    family_rate_terms_problems,
    parse_family_rate_list,
    resolve_family_rates,
    resolve_gpu_pricing,
    retired_hint_pricing_keys,
)

_FLAT_DEFAULT = GpuPricingFields(
    max_duration_seconds=60, accepted_escrows="flat", settlements=["flat"],
)
_NO_OVERRIDE = GpuPricingFields()

_TOKEN = "0x" + "11" * 20


def _rates(rate: str, asset: str = _TOKEN) -> list[dict[str, str]]:
    return [{"asset": asset, "rate": rate, "per": "hour"}]


class TestResolveGpuPricing:
    def test_storefront_override_wins_for_every_field(self):
        override = GpuPricingFields(
            max_duration_seconds=7200, accepted_escrows="override",
            settlements=["override"],
        )
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"max_duration_seconds": 1800}}}},
            gpu_model="H100",
            storefront_override=override,
            config_defaults_by_model={"H100": GpuPricingFields(settlements=["cfg"])},
            flat_default=_FLAT_DEFAULT,
        )
        assert result == override

    def test_each_field_resolved_independently_across_tiers(self):
        """A storefront override that only sets one field must not block
        the others from falling through to lower tiers."""
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"settlements": ["hint"]}}}},
            gpu_model="H100",
            storefront_override=GpuPricingFields(max_duration_seconds=7200),
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.max_duration_seconds == 7200  # storefront override
        assert result.settlements == ["hint"]  # pool hint
        assert result.accepted_escrows == "flat"  # flat fallback

    def test_config_per_model_default_used_when_no_override_or_hint(self):
        result = resolve_gpu_pricing(
            {},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={"H100": GpuPricingFields(settlements=["cfg"])},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.settlements == ["cfg"]
        assert result.max_duration_seconds == 60

    def test_flat_default_used_as_last_resort(self):
        result = resolve_gpu_pricing(
            {}, gpu_model="A100", storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={}, flat_default=_FLAT_DEFAULT,
        )
        assert result == _FLAT_DEFAULT

    def test_hint_for_a_different_model_is_ignored(self):
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"A100": {"settlements": ["a100"]}}}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.settlements == ["flat"]

    @pytest.mark.parametrize(
        "pricing",
        ["not-a-mapping", {"gpu": "not-a-mapping"}],
    )
    def test_malformed_pricing_hint_is_ignored_not_raised(self, pricing):
        result = resolve_gpu_pricing(
            {"pricing": pricing},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result == _FLAT_DEFAULT

    @pytest.mark.parametrize("value", ["not-an-int", -1, True])
    def test_malformed_max_duration_seconds_falls_through(self, value):
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"max_duration_seconds": value}}}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.max_duration_seconds == 60

    def test_retired_hint_keys_are_not_listing_terms(self):
        """A hint still stating min_price or token resolves exactly as one
        that does not: neither is a field of the resolved terms."""
        stated = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"min_price": "5", "token": "0xhint"}}}},
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={},
            flat_default=_FLAT_DEFAULT,
        )
        assert stated == _FLAT_DEFAULT
        assert not hasattr(stated, "min_price")


class TestParseFamilyRateList:
    def test_entries_are_normalized(self):
        assert parse_family_rate_list(_rates("0.5")) == (
            {"asset": _TOKEN, "rate": "0.5", "per": "hour"},
        )

    def test_an_empty_list_is_a_statement(self):
        assert parse_family_rate_list([]) == ()

    @pytest.mark.parametrize(
        "value, match",
        [
            ("not-a-list", "must be a list"),
            ([{"asset": _TOKEN, "rate": "1"}], "missing"),
            ([{"asset": _TOKEN, "rate": "1", "per": "hour", "x": 1}], "unknown"),
            ([{"asset": "", "rate": "1", "per": "hour"}], "asset"),
            ([{"asset": _TOKEN, "rate": "0", "per": "hour"}], "positive"),
            ([{"asset": _TOKEN, "rate": 1.5, "per": "hour"}], "decimal text"),
            ([{"asset": _TOKEN, "rate": "1", "per": "request"}], "time unit"),
            (_rates("1") + _rates("2"), "more than once"),
        ],
    )
    def test_problems_are_refused(self, value, match):
        with pytest.raises(ValueError, match=match):
            parse_family_rate_list(value)


class TestResolveFamilyRates:
    def test_each_family_resolves_from_its_own_highest_tier(self):
        result = resolve_family_rates(
            {"pricing": {"memory": {"rates": _rates("0.04")}}},
            gpu_model="H100",
            storefront_override={"gpu": {"H100": {"rates": _rates("90")}}},
            config_defaults={
                "gpu": {"H100": {"rates": _rates("80")}},
                "memory": {"rates": _rates("0.05")},
                "cpu": {"rates": _rates("0.5")},
            },
        )
        assert result.rates == {
            "gpu": tuple(_rates("90")),
            "memory": tuple(_rates("0.04")),
            "cpu": tuple(_rates("0.5")),
        }
        assert result.shape_priced

    def test_a_tier_list_replaces_lower_tiers_whole(self):
        other = "usd"
        result = resolve_family_rates(
            {},
            gpu_model="H100",
            storefront_override={"cpu": {"rates": _rates("0.6")}},
            config_defaults={"cpu": {"rates": _rates("0.5") + _rates("1", other)}},
        )
        assert result.rates["cpu"] == tuple(_rates("0.6"))

    def test_an_empty_list_stops_fall_through(self):
        result = resolve_family_rates(
            {},
            gpu_model="H100",
            storefront_override={"gpu": {"H100": {"rates": []}}},
            config_defaults={"gpu": {"H100": {"rates": _rates("80")}}},
        )
        assert "gpu" not in result.rates

    def test_gpu_rates_are_keyed_by_model(self):
        result = resolve_family_rates(
            {"pricing": {"gpu": {"A100": {"rates": _rates("40")}}}},
            gpu_model="H100",
            storefront_override=None,
            config_defaults=None,
        )
        assert result.rates == {}

    def test_an_unreadable_hint_list_never_falls_through(self):
        result = resolve_family_rates(
            {"pricing": {"cpu": {"rates": [{"asset": _TOKEN}]}}},
            gpu_model="H100",
            storefront_override=None,
            config_defaults={"cpu": {"rates": _rates("0.5")}},
        )
        assert "cpu" not in result.rates
        assert result.unreadable
        (problem,) = result.problems
        assert problem.startswith("hint pricing.cpu")

    @pytest.mark.parametrize(
        ("tier", "fragment"),
        [
            ({"fpga": {"rates": _rates("1")}}, "no VM family is priced by it"),
            ({"gpu": {"rates": _rates("1")}}, "must be stated per model"),
        ],
    )
    def test_rates_no_vm_family_is_priced_by_are_unreadable(self, tier, fragment):
        result = resolve_family_rates(
            {}, gpu_model="H100", storefront_override=tier, config_defaults=None
        )
        assert result.unreadable
        assert fragment in result.problems[0]

    def test_any_family_with_rates_is_shape_priced(self):
        result = resolve_family_rates(
            {}, gpu_model="H100", storefront_override={"memory": {"rates": _rates("1")}},
            config_defaults=None,
        )
        assert result.shape_priced and not result.unreadable

    def test_retired_hint_keys_are_reported(self):
        tags = {"pricing": {"gpu": {"H100": {"min_price": "5", "token": "0x"}}}}
        assert retired_hint_pricing_keys(tags) == (
            "pricing.gpu.H100.min_price",
            "pricing.gpu.H100.token",
        )
        result = resolve_family_rates(
            tags, gpu_model="H100", storefront_override=None, config_defaults=None
        )
        assert result.retired_keys == retired_hint_pricing_keys(tags)


class TestFamilyRateTermsProblems:
    def test_a_valid_override_has_no_problems(self):
        assert family_rate_terms_problems(
            {
                "gpu": {"H100": {"rates": _rates("80")}},
                "memory": {"rates": _rates("0.05")},
            }
        ) == []

    @pytest.mark.parametrize(
        "pricing, match",
        [
            ({"bandwidth": {"rates": _rates("1")}}, "not defined"),
            ({"gpu": {"rates": _rates("1")}}, "keyed by model"),
            ({"cpu": {"H100": {"rates": _rates("1")}}}, "exactly rates"),
            ({"gpu": {"H100": {"rates": _rates("1"), "settlements": []}}}, "exactly rates"),
            ({"cpu": {"rates": _rates("0")}}, "positive"),
        ],
    )
    def test_problems_are_named(self, pricing, match):
        problems = family_rate_terms_problems(pricing)
        assert problems and match in problems[0]


class TestConfiguredFamilyRateProblems:
    def test_valid_defaults_beside_listing_terms_have_no_problems(self):
        assert configured_family_rate_problems(
            {
                "gpu": {"H100": {"rates": _rates("80"), "settlements": []}},
                "memory": {"rates": _rates("0.05")},
            }
        ) == []

    def test_each_unreadable_default_is_named(self):
        problems = configured_family_rate_problems(
            {
                "gpu": {"H100": {"rates": "80"}},
                "cpu": {"rates": [{"asset": _TOKEN, "rate": "0", "per": "hour"}]},
                "fpga": {"rates": _rates("1")},
            }
        )
        assert any(p.startswith("pricing.defaults.gpu.H100.rates") for p in problems)
        assert any(p.startswith("pricing.defaults.cpu.rates") for p in problems)
        assert any("fpga" in p for p in problems)
