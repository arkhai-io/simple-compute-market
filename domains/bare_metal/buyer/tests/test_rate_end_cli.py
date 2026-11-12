"""Canonical bare-metal teardown uses normal end unless surrender is explicit."""

from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle_buyer.ending import EndDeliveryProgress
from market_deal_lifecycle_contracts.models import Accepted
from typer.testing import CliRunner

from arkhai_bare_metal_buyer import cli


@pytest.mark.parametrize("surrender", [False, True])
def test_teardown_forwards_the_explicit_surrender_choice(monkeypatch, surrender):
    progress = EndDeliveryProgress(
        negotiation_id="deal", observed_at=100, payment=Accepted(),
        mode="immediate_surrender" if surrender else "normal_stop",
    )
    lifecycle = SimpleNamespace(end=AsyncMock(return_value=progress),
                                peer=SimpleNamespace(read=AsyncMock(side_effect=OSError("unavailable"))))

    @asynccontextmanager
    async def context():
        yield lifecycle

    monkeypatch.setattr(cli, "_lifecycle_for_run",
                        lambda *args: (SimpleNamespace(negotiation_id="deal"), context()))
    args = ["teardown", "--run-id", "run"]
    if surrender:
        args.append("--end-now-regardless")
    result = CliRunner().invoke(cli.bare_metal_app, args)
    assert result.exit_code == 0, result.output
    output = json.loads(result.output)
    assert output["payment"]["status"] == "accepted" and output["mode"] == progress.mode
    lifecycle.end.assert_awaited_once_with("deal", surrender=surrender)
