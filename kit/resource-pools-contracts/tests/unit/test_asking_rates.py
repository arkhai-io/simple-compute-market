"""Domain-neutral asking-rate declaration structure."""

import pytest

from market_resource_pools_contracts import validate_asking_rates

H100_1 = {"gpu": {"model": "H100", "count": 1}}
H100_8 = {"gpu": {"model": "H100", "count": 8}, "memory": {"gib": 512}}


def _entry(shape=H100_1, amount="2.10", asset="usd", period="hour"):
    return {"shape": shape, "amount": amount, "asset": asset, "period": period}


class TestStructure:
    @pytest.mark.parametrize(
        "tags",
        [
            {"asking_rates": {"": []}},
            {"asking_rates": {1: []}},
            {"asking_rates": {"vm": "2.10"}},
            {"asking_rates": {"vm": [None]}},
            {"asking_rates": {"vm": [_entry(shape={})]}},
            {"asking_rates": {"vm": [_entry(shape={"gpu": 1})]}},
            {"asking_rates": {"vm": [_entry(asset="")]}},
        ],
    )
    def test_malformed_modes_lists_entries_and_shapes_are_refused(self, tags):
        assert validate_asking_rates(tags)

    def test_absent_is_valid(self):
        assert validate_asking_rates({}) == []

    def test_a_well_formed_declaration_is_valid(self):
        assert validate_asking_rates({"asking_rates": {"vm": [_entry(), _entry(H100_8)]}}) == []

    def test_an_empty_mode_list_is_valid(self):
        assert validate_asking_rates({"asking_rates": {"vm": []}}) == []

    @pytest.mark.parametrize(
        "amount",
        ["0", "0.00", "-1", "+1", "1e3", "01", "1.", ".5", 2.1, ""],
    )
    def test_an_amount_that_is_not_positive_plain_decimal_text_is_refused(self, amount):
        problems = validate_asking_rates({"asking_rates": {"vm": [_entry(amount=amount)]}})
        assert any("amount" in p for p in problems)

    @pytest.mark.parametrize("amount", ["0.01", "16", "16.000000000000000001"])
    def test_boundary_amounts_are_accepted(self, amount):
        assert validate_asking_rates({"asking_rates": {"vm": [_entry(amount=amount)]}}) == []

    def test_a_missing_part_is_refused(self):
        entry = _entry()
        del entry["asset"]
        problems = validate_asking_rates({"asking_rates": {"vm": [entry]}})
        assert problems == ["asking_rates.vm[0]: missing asset"]

    def test_an_unknown_key_is_refused(self):
        problems = validate_asking_rates({"asking_rates": {"vm": [{**_entry(), "rate": "1"}]}})
        assert problems == ["asking_rates.vm[0]: unknown rate"]

    def test_an_untrimmed_asset_is_refused(self):
        problems = validate_asking_rates({"asking_rates": {"vm": [_entry(asset=" usd")]}})
        assert any("asset" in p for p in problems)

    @pytest.mark.parametrize("period", ["Hour", " hour", "per hour", "", 1])
    def test_a_period_that_is_not_a_canonical_unit_token_is_refused(self, period):
        problems = validate_asking_rates({"asking_rates": {"vm": [_entry(period=period)]}})
        assert problems == ["asking_rates.vm[0]: period must be a canonical lowercase unit token"]

    def test_an_unknown_period_is_structurally_valid(self):
        """Which periods are accepted is the reading version's to say."""
        assert validate_asking_rates({"asking_rates": {"vm": [_entry(period="month")]}}) == []

    def test_a_non_mapping_declaration_is_refused(self):
        assert validate_asking_rates({"asking_rates": ["2.10"]}) == [
            "asking_rates must be a mapping of offering mode to a list of rates"
        ]


@pytest.mark.parametrize("tags", [{"asking_rates": None}, {"asking_rates": {"vm": None}}])
def test_stated_null_is_malformed(tags):
    assert validate_asking_rates(tags)
