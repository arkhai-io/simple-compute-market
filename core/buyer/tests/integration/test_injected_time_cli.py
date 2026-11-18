"""The `market` command on a lane-time file: installed at start, read on every read.

The real `market` app, assembled by `build_app` from an explicit domain list and
driven through Typer's runner and through `run`, which the console entry calls,
with a buyer configuration and a lane-time file written under a temporary
directory, so the file is read as the buyer reads it. A small domain stands in
for a command that reads the time twice during one run, the harness writing the
file between the reads.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path

import injected_time
import pytest
import typer
from injected_time import TimeFile
from market_config.config_loader import set_user_config_path
from typer.testing import CliRunner

from core_buyer.cli import build_app, run
from market_core import (
    MARKET_DOMAIN_CONTRACT_VERSION,
    DomainCapability,
    DomainIdentity,
    ImmutableBuyerCapability,
    ImmutableCodecCapability,
    MarketDomainContract,
)

T = 1_794_821_400
runner = CliRunner()


@pytest.fixture(autouse=True)
def restored() -> Iterator[None]:
    """Each test's source and configuration path are the process's again after it."""
    before = injected_time.installed()
    yield
    injected_time.install(before)
    set_user_config_path(None)


def _config(tmp_path: Path, time: str, *, settlement: str = "") -> Path:
    config = tmp_path / "buyer.toml"
    config.write_text(time + settlement, encoding="utf-8")
    return config


def _injected(lane_time: Path) -> str:
    return f'[time]\nsource = "injected"\nfile = "{lane_time}"\n'


def _output(result) -> str:
    try:
        return result.output + result.stderr
    except ValueError:
        return result.output


def _reading_domain(between: Callable[[], None]) -> MarketDomainContract:
    """A domain whose `tick` reads the time, lets ``between`` run, and reads it again."""

    def register(app: typer.Typer) -> None:
        @app.command("tick")
        def tick() -> None:
            typer.echo(f"first read {injected_time.now()}")
            between()
            typer.echo(f"second read {injected_time.now()}")

    def same(value):
        return value

    return MarketDomainContract(
        identity=DomainIdentity("clock.test"),
        contract_version=MARKET_DOMAIN_CONTRACT_VERSION,
        codecs=ImmutableCodecCapability(
            normalize_listing=same, normalize_message=same, normalize_terms=same,
            normalize_materialization=same, normalize_receipt=same, normalize_result=same,
        ),
        declared_capabilities=frozenset({DomainCapability.BUYER}),
        buyer=ImmutableBuyerCapability(
            identity_injection_contract="core.resolved-buyer-identity.v1",
            register_commands=register,
            build_provision_terms=lambda **kwargs: kwargs,
            select_policy=lambda: object(),
            decode_result=same,
        ),
    )


def test_injected_time_is_installed_from_the_file_and_announced_and_warned_beside_livemode(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lane_time = tmp_path / "lane-time.json"
    TimeFile(lane_time).write(T)
    config = _config(tmp_path, _injected(lane_time),
                     settlement="[bare_metal.arkhai_payments]\nlivemode = true\n")

    with pytest.raises(SystemExit) as exited:
        run(build_app(domains=[]), ["--config", str(config), "plugins"])

    captured = capsys.readouterr()
    assert exited.value.code == 0, captured.err
    installed = injected_time.installed()
    assert isinstance(installed, TimeFile) and installed.path == lane_time
    assert captured.err.splitlines() == [
        f"[market] [time] source is injected: time is read from {lane_time}, now {T}",
        "[market] warning: [time] source is injected while [bare_metal.arkhai_payments] "
        "states livemode = true",
    ]
    assert "No buyer market domains installed" in captured.out


def test_a_buyer_on_wall_time_announces_nothing(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = _config(tmp_path, '[time]\nsource = "wall"\n',
                     settlement="[Settlement.arkhai_payments]\nlivemode = true\n")

    with pytest.raises(SystemExit) as exited:
        run(build_app(domains=[]), ["--config", str(config), "plugins"])

    assert exited.value.code == 0
    assert capsys.readouterr().err == ""


def test_a_missing_lane_time_file_refuses_the_start_naming_it(tmp_path: Path) -> None:
    lane_time = tmp_path / "absent.json"
    config = _config(tmp_path, _injected(lane_time))
    before = injected_time.installed()

    result = runner.invoke(build_app(domains=[]), ["--config", str(config), "plugins"])

    assert result.exit_code == 2
    assert f"time file {lane_time}: cannot be read" in _output(result)
    assert "No buyer market domains installed" not in result.output
    assert injected_time.installed() is before


def test_injected_time_without_a_file_refuses_the_start_naming_the_setting(
        tmp_path: Path) -> None:
    config = _config(tmp_path, '[time]\nsource = "injected"\n')

    result = runner.invoke(build_app(domains=[]), ["--config", str(config), "plugins"])

    assert result.exit_code == 2
    assert "[time] file names no lane-time file" in _output(result)


def test_a_running_command_sees_a_later_instant_at_its_next_read(tmp_path: Path) -> None:
    lane_time = tmp_path / "lane-time.json"
    TimeFile(lane_time).write(T)
    config = _config(tmp_path, _injected(lane_time))
    app = build_app(domains=[_reading_domain(lambda: TimeFile(lane_time).write(T + 3_600))])

    result = runner.invoke(app, ["--config", str(config), "tick"])

    assert result.exit_code == 0, _output(result)
    assert result.stdout.splitlines() == [f"first read {T}", f"second read {T + 3_600}"]


def test_an_invalid_instant_written_during_a_run_fails_the_command_naming_the_file(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lane_time = tmp_path / "lane-time.json"
    TimeFile(lane_time).write(T)
    config = _config(tmp_path, _injected(lane_time))
    invalid = json.dumps({"now": str(T)})
    app = build_app(domains=[
        _reading_domain(lambda: lane_time.write_text(invalid, encoding="utf-8"))])

    with pytest.raises(SystemExit) as exited:
        run(app, ["--config", str(config), "tick"])

    captured = capsys.readouterr()
    assert exited.value.code == 2
    # The first read was the file's instant; the second failed on the file and
    # returned nothing, wall time least of all.
    assert captured.out.splitlines() == [f"first read {T}"]
    assert f"[market] time file {lane_time}: holds no valid instant" in captured.err
