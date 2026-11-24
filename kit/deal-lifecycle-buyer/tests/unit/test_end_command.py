"""The buyer's canonical ``end`` verb: its read-back, wait and exit code."""

from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import typer
from market_deal_lifecycle_buyer import EndDeliveryProgress, EndTarget, end_deal, end_exit_code, register_end_command
from market_deal_lifecycle_contracts.models import Accepted, DeliveryView, Pending
from typer.testing import CliRunner


def target(progress, reads, events=None):
    lifecycle = SimpleNamespace(end=AsyncMock(return_value=progress), peer=SimpleNamespace(read=AsyncMock(side_effect=reads)))

    @asynccontextmanager
    async def context():
        yield lifecycle

    record = (lambda name, fields: events.append((name, fields))) if events is not None else None
    return lifecycle, EndTarget(negotiation_id="deal", lifecycle=context(), record=record)


def observed(progress):
    return SimpleNamespace(delivery=DeliveryView(progress=progress))


def normal(payment=Accepted()):
    return EndDeliveryProgress(negotiation_id="deal", observed_at=1, mode="normal_stop", payment=payment)


class Clock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


@pytest.mark.asyncio
async def test_without_a_wait_the_delivery_is_read_once():
    events = []
    lifecycle, end = target(normal(), [observed("active")], events)
    result = await end_deal(end, surrender=False, wait_timeout=0, poll_interval=1)
    assert result["delivery_view"]["progress"] == "active" and not result["capacity_released"]
    assert lifecycle.peer.read.await_count == 1
    lifecycle.end.assert_awaited_once_with("deal", surrender=False)
    assert [name for name, _ in events] == ["delivery_end", "delivery_end_observed"]
    assert events[1][1] == result


@pytest.mark.asyncio
async def test_a_wait_polls_until_release_in_fake_time():
    clock = Clock()
    lifecycle, end = target(normal(), [observed("tearing_down"), observed("tearing_down"), observed("released")])
    result = await end_deal(end, surrender=True, wait_timeout=10, poll_interval=2,
                            sleep=clock.sleep, monotonic=clock.monotonic)
    assert result["capacity_released"] and clock.now == 4
    assert end_exit_code(result, wait_timeout=10) == 0


@pytest.mark.asyncio
async def test_an_unavailable_read_keeps_the_ends_outcome():
    _, end = target(normal(), OSError("storefront down"))
    result = await end_deal(end, surrender=False, wait_timeout=5, poll_interval=1)
    assert result["progress"]["payment"]["status"] == "accepted"
    assert result["delivery_read_error"] and result["delivery_view"] is None
    assert end_exit_code(result, wait_timeout=0) == 0
    assert end_exit_code(result, wait_timeout=5) == 1


def test_the_exit_code_follows_the_governing_outcome():
    stopped = {"progress": normal(Pending(reason="unknown")).model_dump(mode="json"), "capacity_released": False}
    assert end_exit_code(stopped, wait_timeout=0) == 1
    surrendered = EndDeliveryProgress(negotiation_id="deal", observed_at=1, delivery=Accepted(), payment=Pending(reason="x"))
    assert end_exit_code({"progress": surrendered.model_dump(mode="json"), "capacity_released": False}, wait_timeout=0) == 0


def test_a_deprecated_alias_ends_the_same_way_and_keeps_its_output():
    app = typer.Typer()
    calls = []
    unknown = normal(Pending(reason="payment authority down"))

    def open_end(run_id, config):
        calls.append((run_id, config))
        return target(unknown, [observed("active")])[1]

    register_end_command(app, open_end, configurable=True, deprecated_alias="teardown")
    result = CliRunner().invoke(app, ["teardown", "--run-id", "run", "--config", "c.toml"])
    # The alias prints the progress alone and exits 0, as its callers expect.
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == unknown.model_dump(mode="json")
    assert "'teardown' is deprecated" in result.stderr and "use 'end'" in result.stderr
    assert calls == [("run", "c.toml")]
    ended = CliRunner().invoke(app, ["end", "-r", "run"])
    assert ended.exit_code == 1 and json.loads(ended.stdout)["progress"] == unknown.model_dump(mode="json")
    assert calls[-1] == ("run", None)
