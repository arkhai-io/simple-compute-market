"""A second domain's bundle assembles the same command group under its own names."""

from __future__ import annotations

from market_core import SettlementStageTable
from typer.testing import CliRunner

from arkhai_api_buying.commands import command_group
from arkhai_api_buying.settlement_composition import BuyerSettlementComposition
from tests.bundles import CONTRIBUTIONS


def test_the_group_carries_every_command_and_names_the_bundles_noun(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    group = command_group(BuyerSettlementComposition(CONTRIBUTIONS, SettlementStageTable({})))
    runner = CliRunner()

    result = runner.invoke(group, ["--help"])
    assert result.exit_code == 0, result.output
    for name in ("listing", "buy", "negotiate", "settle", "settlement"):
        assert name in result.output

    listing = runner.invoke(group, ["listing", "--help"])
    assert listing.exit_code == 0, listing.output
    assert "List open example listings" in listing.output
    assert "Show a single example listing" in listing.output
