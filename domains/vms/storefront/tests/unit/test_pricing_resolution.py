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
    """VM's composition of the shared settlement-term order with its bounds.

    The order of the settlement terms themselves is the shared resolver's,
    tested in `kit/resource-pools-contracts/tests/unit/test_listing_terms.py`.
    """

    def test_a_released_configuration_and_hint_resolve_as_before(self):
        """A per-model hint and per-model configuration, the forms a released VM
        storefront reads, still resolve every field through their tiers."""
        result = resolve_gpu_pricing(
            {"pricing": {"gpu": {"H100": {"settlements": ["hint"], "max_duration_seconds": 1800}}}},
            gpu_model="H100",
            storefront_override=GpuPricingFields(available_until_utc="2030-01-01T00:00:00Z"),
            config_defaults_by_model={
                "H100": GpuPricingFields(accepted_escrows=["cfg"], settlements=["cfg"])
            },
            flat_default=_FLAT_DEFAULT,
        )
        assert result == GpuPricingFields(
            max_duration_seconds=1800,
            available_until_utc="2030-01-01T00:00:00Z",
            accepted_escrows=["cfg"],
            settlements=["hint"],
        )

    def test_the_pool_level_clauses_sit_below_the_model_hint(self):
        tags = {"pricing": {"settlements": ["pool"], "gpu": {"H100": {"settlements": ["h100"]}}}}

        def clauses(model: str | None) -> object:
            return resolve_gpu_pricing(
                tags,
                gpu_model=model,
                storefront_override=_NO_OVERRIDE,
                config_defaults_by_model={"A100": GpuPricingFields(settlements=["cfg"])},
                flat_default=_FLAT_DEFAULT,
            ).settlements

        assert clauses("H100") == ["h100"]
        assert clauses("A100") == ["pool"]
        assert clauses(None) == ["pool"]

    def test_bounds_keep_the_mode_hint_above_the_per_model_tiers(self):
        result = resolve_gpu_pricing(
            {
                "capacity_bounds": {"vm": {"max_duration_seconds": 900}},
                "pricing": {"gpu": {"H100": {"max_duration_seconds": 1800}}},
            },
            gpu_model="H100",
            storefront_override=_NO_OVERRIDE,
            config_defaults_by_model={"H100": GpuPricingFields(max_duration_seconds=2700)},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.max_duration_seconds == 900

    @pytest.mark.parametrize(
        ("tags", "override", "expected"),
        [
            pytest.param(
                {"capacity_bounds": {"vm": {"max_duration_seconds": 900}}},
                GpuPricingFields(max_duration_seconds=7200),
                7200,
                id="override-above-mode-hint",
            ),
            pytest.param(
                {"pricing": {"gpu": {"H100": {"max_duration_seconds": 1800}}}},
                _NO_OVERRIDE,
                1800,
                id="model-hint-above-model-config",
            ),
            pytest.param({}, _NO_OVERRIDE, 2700, id="model-config-above-flat"),
        ],
    )
    def test_each_bound_tier_wins_over_the_one_below(self, tags, override, expected):
        result = resolve_gpu_pricing(
            tags,
            gpu_model="H100",
            storefront_override=override,
            config_defaults_by_model={"H100": GpuPricingFields(max_duration_seconds=2700)},
            flat_default=_FLAT_DEFAULT,
        )
        assert result.max_duration_seconds == expected

    @pytest.mark.parametrize("value", ["not-an-int", -1, True])
    def test_max_duration_seconds_is_strict_and_nonpositive_is_unlimited(self, value):
        def resolve():
            return resolve_gpu_pricing(
                {"pricing": {"gpu": {"H100": {"max_duration_seconds": value}}}},
                gpu_model="H100",
                storefront_override=_NO_OVERRIDE,
                config_defaults_by_model={},
                flat_default=_FLAT_DEFAULT,
            )

        if value == -1 and not isinstance(value, bool):
            assert resolve().max_duration_seconds == -1
        else:
            with pytest.raises(ValueError, match="max_duration_seconds"):
                resolve()

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
