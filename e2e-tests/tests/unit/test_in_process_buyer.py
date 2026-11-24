"""The in-process buyer's gate, probe and shared-state rules.

Unit: ``in_process_buyer`` runs a small Typer app standing in for ``market``,
whose commands build their wait clock and probe through the factories of a
command module the context replaces, as the domain CLIs' ``wait_clock`` and
``watchdog_probe`` are.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer
from market_deal_lifecycle_buyer import WaitClock

from tests.e2e.roles.buyer_cli import BuyerCli
from tests.e2e.roles.helpers.in_process_buyer import in_process_buyer

#: A placeholder credential variable and value, never a credential.
CREDENTIAL = ("E2E_UNIT_BUYER_CREDENTIAL", "placeholder")


def _original_probe(endpoint):
    raise AssertionError("the command module's own probe factory ran")


def _commands() -> SimpleNamespace:
    """A command module's two factories, as a domain CLI defines them."""
    return SimpleNamespace(wait_clock=WaitClock, watchdog_probe=_original_probe)


def _app(commands: SimpleNamespace, *, between_gates: threading.Event | None = None) -> typer.Typer:
    app = typer.Typer()

    @app.callback()
    def main(config: str = typer.Option(None, "--config")) -> None:
        """The root, taking ``--config`` as ``market``'s does."""

    @app.command()
    def wait(times: int = 2) -> None:
        clock = commands.wait_clock()
        for _ in range(times):
            try:
                asyncio.run(clock.sleep(1.5))
            except KeyboardInterrupt:
                # As the watchdog's own runner reports the buyer's interrupt.
                typer.echo("interrupted by the buyer", err=True)
                return
            typer.echo(f"woke at {clock.monotonic()}")
            if between_gates is not None:
                between_gates.wait(30)

    @app.command()
    def probe(endpoint: str) -> None:
        typer.echo(str(asyncio.run(commands.watchdog_probe(endpoint)())))

    @app.command()
    def read() -> None:
        typer.echo("read")

    @app.command()
    def logged_read() -> None:
        logging.getLogger(LOGGER).info("a request the read makes")
        typer.echo("read")

    return app


#: The logger a command's own requests log through, in these tests.
LOGGER = "tests.unit.in_process_buyer.command"


class RepointingHandler(logging.Handler):
    """Points ``sys.stdout`` elsewhere around each record it emits, as pytest's
    live logging does with its capture."""

    def __init__(self) -> None:
        super().__init__()
        self.elsewhere = io.StringIO()

    def emit(self, record: logging.LogRecord) -> None:
        sys.stdout = self.elsewhere


def _cli(tmp_path: Path, *, config: str = "[registry]\nurls = []\n") -> BuyerCli:
    config_path = tmp_path / "config" / "arkhai" / "buyer.toml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(config, encoding="utf-8")
    return BuyerCli(
        binary=Path("market"), config_path=config_path, state_dir=tmp_path / "state",
        data_dir=tmp_path / "data", home_dir=tmp_path / "home",
        credential_env=dict([CREDENTIAL]),
    )


def test_one_release_advances_the_clock_one_interval_and_lets_one_wait_return(tmp_path):
    commands = _commands()
    with in_process_buyer(_cli(tmp_path), command_module=commands, app=_app(commands)) as buyer:
        run = buyer.run(["wait"], background=True)
        buyer.wait_parked()
        assert buyer.gate.monotonic() == 0.0

        buyer.release()

        # One wait returned; the command reached its second and parked there.
        assert buyer.gate.monotonic() == 1.5 and buyer.gate.released == [1.5]
        assert buyer.gate.parked and not run.exited

        buyer.release()

        assert run.exited and run.returncode == 0
        assert run.stdout().splitlines() == ["woke at 1.5", "woke at 3.0"]


def test_an_interrupt_at_the_gate_ends_the_command_as_a_buyers_interrupt_does(tmp_path):
    commands = _commands()
    with in_process_buyer(_cli(tmp_path), command_module=commands, app=_app(commands)) as buyer:
        buyer.run(["wait"], background=True)

        run = buyer.interrupt()

        assert run.exited and run.returncode == 0
        assert "interrupted by the buyer" in run.stderr()
        assert run.stdout() == "" and buyer.gate.monotonic() == 0.0


def test_the_probe_answers_as_programmed_and_records_its_endpoint(tmp_path):
    commands = _commands()
    with in_process_buyer(_cli(tmp_path), command_module=commands, app=_app(commands)) as buyer:
        reachable = buyer.run(["probe", "192.0.2.10:2222"])
        buyer.probe.reachable = False
        lost = buyer.run(["probe", "192.0.2.10:2222"])

    assert (reachable.stdout(), lost.stdout()) == ("True\n", "False\n")
    assert buyer.probe.built_for == ["192.0.2.10:2222"] * 2
    assert buyer.probe.answered == [True, False]


def test_a_foreground_commands_output_stays_in_its_result_while_it_logs(tmp_path):
    commands = _commands()
    handler = RepointingHandler()
    logger = logging.getLogger(LOGGER)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    streams = sys.stdout
    try:
        with in_process_buyer(_cli(tmp_path), command_module=commands,
                              app=_app(commands)) as buyer:
            run = buyer.run(["logged-read"])
    finally:
        logger.removeHandler(handler)
        sys.stdout = streams

    assert run.stdout() == "read\n"
    assert handler.elsewhere.getvalue() == ""
    # Logging is the process's again once the command has ended.
    assert logging.root.manager.disable == logging.NOTSET


def test_a_configuration_stating_a_time_table_is_refused(tmp_path):
    cli = _cli(tmp_path, config='[time]\nsource = "injected"\nfile = "/run/lane-time.json"\n')

    with pytest.raises(AssertionError, match=r"states a \[time\] table"):
        with in_process_buyer(cli, command_module=_commands(), app=typer.Typer()):
            pass


def test_the_buyers_environment_and_factories_are_restored_when_the_context_ends(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("XDG_STATE_HOME", "/harness/state")
    monkeypatch.delenv(CREDENTIAL[0], raising=False)
    before = dict(os.environ)
    commands = _commands()
    cli = _cli(tmp_path)

    with in_process_buyer(cli, command_module=commands, app=_app(commands)):
        assert os.environ["XDG_STATE_HOME"] == str(cli.state_dir)
        assert os.environ["HOME"] == str(cli.home_dir)
        assert os.environ[CREDENTIAL[0]] == CREDENTIAL[1]
        assert commands.wait_clock is not WaitClock
        assert commands.watchdog_probe is not _original_probe

    assert dict(os.environ) == before
    assert commands.wait_clock is WaitClock and commands.watchdog_probe is _original_probe


def test_a_command_still_running_when_the_context_ends_is_interrupted(tmp_path):
    commands = _commands()
    with in_process_buyer(_cli(tmp_path), command_module=commands, app=_app(commands)) as buyer:
        run = buyer.run(["wait"], background=True)
        buyer.wait_parked()

    assert run.exited and "interrupted by the buyer" in run.stderr()


def test_a_read_while_the_background_command_is_between_gates_is_refused(tmp_path):
    commands = _commands()
    between_gates = threading.Event()
    app = _app(commands, between_gates=between_gates)
    with in_process_buyer(_cli(tmp_path), command_module=commands, app=app) as buyer:
        run = buyer.run(["wait"], background=True)
        buyer.wait_parked()
        with pytest.raises(AssertionError, match="already runs in the background"):
            buyer.run(["wait"], background=True)
        # Released at the gate alone, the command goes on to work between its
        # waits, which it holds until the event is set.
        buyer.gate.release()
        try:
            with pytest.raises(AssertionError, match="between gates"):
                buyer.run(["read"])
        finally:
            between_gates.set()

        buyer.wait_parked()
        assert buyer.run(["read"]).stdout() == "read\n"
        buyer.release()

    assert run.exited and run.returncode == 0
