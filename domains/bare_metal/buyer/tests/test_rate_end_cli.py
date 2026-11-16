"""The bare-metal buyer's canonical ``end`` verb and its deprecated ``teardown`` alias."""

from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from market_deal_lifecycle_buyer import EndTarget
from market_deal_lifecycle_buyer.ending import EndDeliveryProgress
from market_deal_lifecycle_contracts.models import Accepted
from typer.testing import CliRunner

from arkhai_bare_metal_buyer import cli


def _target(monkeypatch, progress):
    lifecycle = SimpleNamespace(end=AsyncMock(return_value=progress),
                                peer=SimpleNamespace(read=AsyncMock(side_effect=OSError("unavailable"))))
    events = []

    @asynccontextmanager
    async def context():
        yield lifecycle

    opened = []

    def end_target(run_id, config):
        opened.append((run_id, config))
        return EndTarget(negotiation_id="deal", lifecycle=context(),
                         record=lambda name, fields: events.append(name))

    monkeypatch.setattr(cli, "end_target", end_target)
    return lifecycle, opened, events


@pytest.mark.parametrize("verb", ["end", "teardown"])
@pytest.mark.parametrize("surrender", [False, True])
def test_end_forwards_the_explicit_surrender_choice(monkeypatch, verb, surrender):
    progress = EndDeliveryProgress(
        negotiation_id="deal", observed_at=100, payment=Accepted(), delivery=Accepted(),
        mode="immediate_surrender" if surrender else "normal_stop",
    )
    lifecycle, opened, events = _target(monkeypatch, progress)
    args = [verb, "--run-id", "run", "--config", "buyer.toml"]
    if surrender:
        args.append("--end-now-regardless")
    result = CliRunner().invoke(cli.bare_metal_app, args)
    assert result.exit_code == 0, result.output
    output = json.loads(result.stdout)
    if verb == "end":
        assert output["capacity_released"] is False and output["delivery_read_error"] is not None
        output = output["progress"]
    # The deprecated alias prints the progress alone, as its callers expect.
    assert output == progress.model_dump(mode="json")
    assert opened == [("run", "buyer.toml")]
    assert events == ["delivery_end", "delivery_end_observed"]
    lifecycle.end.assert_awaited_once_with("deal", surrender=surrender)
    deprecated = "'teardown' is deprecated" in result.stderr
    assert deprecated == (verb == "teardown") and (not deprecated or "use 'end'" in result.stderr)


def test_end_reports_a_surrendered_delivery_as_its_outcome(monkeypatch):
    progress = EndDeliveryProgress(
        negotiation_id="deal", observed_at=100, mode="immediate_surrender", delivery=Accepted(),
    )
    lifecycle, _, _ = _target(monkeypatch, progress)
    result = CliRunner().invoke(cli.bare_metal_app, ["end", "--run-id", "run"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["progress"]["delivery"]["status"] == "accepted"
    lifecycle.end.assert_awaited_once_with("deal", surrender=False)
