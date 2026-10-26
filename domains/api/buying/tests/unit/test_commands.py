"""A second domain's bundle assembles the same command group under its own names."""

from __future__ import annotations

import json

import pytest
from market_core import SettlementStageTable
from typer.testing import CliRunner

from arkhai_api_buying import commands
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


@pytest.mark.parametrize(
    ("data", "kept"),
    [
        (b'{"a":1}\n{"b":', b'{"a":1}\n'),
        (b'{"a":1}\n{"b":\n', b'{"a":1}\n'),
        (b'{"a":1}\n{"b":2}\n', None),
        (b'{"b":', b""),
    ],
    ids=["no newline", "unparseable last line", "intact", "nothing before it"],
)
def test_only_a_torn_final_record_is_dropped(data, kept):
    assert commands._without_torn_tail(data) == kept


def test_a_working_copy_never_holds_a_legacy_secret():
    line = json.dumps({"event": "credentials_delivered", "credentials": {"key_id": "k", "secret": "s"}})
    assert b'"secret"' not in commands._scrubbed(line.encode() + b"\n")
