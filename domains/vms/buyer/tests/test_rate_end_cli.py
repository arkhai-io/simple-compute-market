"""Canonical VM end forwards explicit surrender and preserves authority outcomes."""

from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import typer
from market_deal_lifecycle_buyer.ending import EndDeliveryProgress
from market_deal_lifecycle_contracts.models import Accepted, Pending
from typer.testing import CliRunner

from arkhai_vms_buyer import end_cli


@pytest.mark.parametrize("surrender,wait", [(False, False), (True, False), (False, True)])
def test_end_selects_normal_or_explicit_surrender_and_reports_payment_separately(monkeypatch, surrender, wait):
    progress = EndDeliveryProgress(
        negotiation_id="deal", observed_at=100,
        mode="immediate_surrender" if surrender else "normal_stop",
        payment=Accepted(), delivery=Accepted() if surrender else Pending(reason="notice remains"),
    )
    lifecycle = SimpleNamespace(
        end=AsyncMock(return_value=progress),
        peer=SimpleNamespace(read=AsyncMock(side_effect=OSError("storefront unavailable"))),
    )

    @asynccontextmanager
    async def context():
        yield lifecycle

    monkeypatch.setattr(end_cli, "end_context",
                        lambda *args, **kwargs: (SimpleNamespace(negotiation_id="deal"), Mock(), context()))
    app = typer.Typer()
    end_cli.register(app)
    args = ["--from", "run"]
    if surrender:
        args.append("--end-now-regardless")
    if wait:
        args += ["--wait-timeout", "1"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == (1 if wait else 0), result.output
    output = json.loads(result.output)
    assert output["progress"]["payment"]["status"] == "accepted"
    assert output["progress"]["mode"] == progress.mode
    assert output["capacity_released"] is False
    if wait:
        assert output["delivery_read_error"] is not None
    lifecycle.end.assert_awaited_once_with("deal", surrender=surrender)
