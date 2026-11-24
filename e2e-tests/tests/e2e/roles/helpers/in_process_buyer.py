"""The shipped buyer CLI run in the harness's process, its probe and its waits programmed.

The buyer watchdog's delivered-deal cases run the shipped ``market buy``, its
resume and the buyer's read here rather than as subprocesses
(``tests/e2e/roles/buyer_cli.py`` says why). Each command runs through the
``market`` app's own entry, ``build_app()`` at the root, so its callback reads
the buyer's configuration, under Typer's ``CliRunner`` in a worker thread. The
harness replaces the domain CLI's two composition factories, as each
storefront's ``test_watchdog_buy.py`` does:

- ``watchdog_probe`` with a ``ProgrammedProbe``, answering reachable or not as
  the stage programs it, making no network call, and recording the endpoint
  each probe was built for: VM's factory is given its delivery's connection
  details, bare metal's the access its caller read from the storefront;
- ``wait_clock`` with a ``WaitClock`` whose ``now`` is the harness's installed
  lane-time source and whose ``sleep`` parks at a ``WaitGate``, so every wait
  the command makes — its commit, its wait for delivery and the watchdog's —
  moves only when the stage releases it, one interval at a time.

The command shares the harness's process, so ``in_process_buyer`` keeps that
shared state coherent for the module: the buyer's configuration states no
``[time]`` table, so its callback installs no source and the harness's
lane-time source stays installed; the buyer's ``XDG_*``, ``HOME`` and
credential variables are set for the module and restored when it ends, with the
two factories; and a command runs only while no other runs or the one running
is parked at the gate, so ``CliRunner``'s process-wide stream swaps nest and no
command's output reaches another's capture.

pytest points the process's streams at its own capture for each stage, and
again around each record its live logging prints. A foreground command runs
with logging held, so its output stays in its result. A background command
outlives the stage that starts it and logs as it runs, so what it prints goes
partly to pytest's captures: a stage reads its outcome from its exit status and
its run log. ``CliRunner`` restores, when a command ends, the streams it found
when it started, so the buyer puts back the running stage's own whenever a
background command ends under it.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
import time
import tomllib
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import injected_time
import pytest
import typer
from core_buyer.cli import build_app
from market_config.config_loader import set_user_config_path
from market_deal_lifecycle_buyer import WaitClock
from typer.testing import CliRunner

from tests.e2e.roles.buyer_cli import BuyerCli, MarketRun, run_id_from_args

log = logging.getLogger(__name__)

#: How long a stage waits for an effect of its own step on a command: the
#: command reaching the gate again, or ending.
STEP_TIMEOUT_SECONDS = 60.0


class WaitGate:
    """The command's waits held at a gate the stage opens one interval at a time.

    Every wait the command makes awaits ``sleep``, which parks it until the
    stage acts: ``release`` lets exactly that sleep return, advancing
    ``monotonic`` by the seconds it asked for, so the command's deadlines and
    the watchdog's schedule move only by the intervals released;
    ``interrupt`` makes it raise ``KeyboardInterrupt``, which ends the command
    as a buyer's interrupt does. The command awaits its sleeps on event loops
    of its own threads, so the gate is a thread condition; a parked sleep holds
    its loop, and nothing else of the command runs while it waits.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._monotonic = 0.0
        #: The seconds the parked sleep asked for; ``None`` while none is parked.
        self._asked: float | None = None
        #: What the stage granted the parked sleep, until it takes it.
        self._grant: str | None = None
        #: The seconds of every sleep released, in order.
        self.released: list[float] = []

    def monotonic(self) -> float:
        with self._condition:
            return self._monotonic

    @property
    def parked(self) -> bool:
        with self._condition:
            return self._asked is not None and self._grant is None

    def wait_clock(self) -> WaitClock:
        """The clock the command's waits run on: lane time stamps, the gate paces."""
        return WaitClock(now=injected_time.now, monotonic=self.monotonic, sleep=self.sleep)

    async def sleep(self, seconds: float) -> None:
        with self._condition:
            if self._asked is not None:
                raise RuntimeError("a second wait reached the gate while one is parked there")
            self._asked = float(seconds)
            self._condition.notify_all()
            while self._grant is None:
                self._condition.wait()
            grant, self._grant, self._asked = self._grant, None, None
            self._condition.notify_all()
        if grant == "interrupt":
            raise KeyboardInterrupt

    def release(self) -> float:
        """Let the parked sleep return, advancing ``monotonic`` by its seconds."""
        with self._condition:
            asked = self._take_parked("release")
            self._monotonic += asked
            self.released.append(asked)
            self._grant = "release"
            self._condition.notify_all()
            self._await_taken()
        return asked

    def interrupt(self) -> None:
        """Make the parked sleep raise ``KeyboardInterrupt``."""
        with self._condition:
            self._take_parked("interrupt")
            self._grant = "interrupt"
            self._condition.notify_all()
            self._await_taken()

    def wait_until(self, condition: Callable[[], bool], timeout: float) -> bool:
        """Wait until ``condition`` holds, woken whenever a wait parks or takes
        its grant and by ``notify``; whether it held within ``timeout``."""
        with self._condition:
            return self._condition.wait_for(condition, timeout)

    def notify(self) -> None:
        """Wake whoever waits on the gate: a command has ended."""
        with self._condition:
            self._condition.notify_all()

    def _take_parked(self, action: str) -> float:
        if self._asked is None or self._grant is not None:
            raise AssertionError(f"no wait is parked at the gate to {action}")
        return self._asked

    def _await_taken(self) -> None:
        deadline = time.monotonic() + STEP_TIMEOUT_SECONDS
        while self._grant is not None:
            if not self._condition.wait(max(0.0, deadline - time.monotonic())):
                raise AssertionError("the parked wait did not take the gate's grant")


@dataclass
class ProgrammedProbe:
    """The watchdog's probe, answering as the stage programs it, with no network call.

    ``factory`` stands in for the domain CLI's ``watchdog_probe``: both domains'
    take one argument naming the endpoint the deal disclosed, which it records
    before building the probe.
    """

    reachable: bool = True
    #: The endpoint each probe was built for, in order.
    built_for: list[Any] = field(default_factory=list)
    #: Each answer given, in order.
    answered: list[bool] = field(default_factory=list)

    def factory(self, endpoint: Any) -> Callable[[], Any]:
        self.built_for.append(endpoint)

        async def probe() -> bool:
            self.answered.append(self.reachable)
            return self.reachable

        return probe


@dataclass
class InProcessRun(MarketRun):
    """One ``market`` command run in the harness's process, read as a ``MarketRun`` is."""

    thread: threading.Thread | None = None
    #: The ``CliRunner`` result, once the command has ended.
    result: Any = None
    #: What escaped the command, if anything did.
    error: BaseException | None = None
    #: The command has returned, set before its thread ends.
    ended: bool = False
    #: Ends the command, when it is still running; the buyer it runs under owns how.
    stop: Callable[[], None] | None = None

    @property
    def exited(self) -> bool:
        return self.thread is not None and not self.thread.is_alive()

    def wait(self, timeout: float = 60.0) -> int:
        assert self.thread is not None
        self.thread.join(timeout)
        if self.thread.is_alive():
            raise AssertionError(f"the in-process command is still running after {timeout}s")
        return int(self.returncode if self.returncode is not None else 1)

    def terminate(self) -> None:
        if self.stop is not None and not self.exited:
            self.stop()

    @property
    def returncode(self) -> int | None:
        if self.result is not None:
            return self.result.exit_code
        if self.error is not None:
            return 1
        return None

    def stdout(self) -> str:
        return self.result.stdout if self.result is not None else ""

    def stderr(self) -> str:
        if self.result is not None:
            return self.result.stderr
        return repr(self.error) if self.error is not None else ""


class InProcessBuyer:
    """``market`` commands run in the harness's process, as ``BuyerCli`` runs them as subprocesses.

    It reads as the ``BuyerCli`` it wraps — its run directory, configuration,
    data directory and credentials — so the stages and cleanups written
    against a ``BuyerCli`` take it unchanged. One command runs in the
    background at a time; another, such as a read, runs only while that one is
    parked at the gate or has ended.
    """

    def __init__(self, cli: BuyerCli, gate: WaitGate, probe: ProgrammedProbe, *,
                 app: typer.Typer | None = None) -> None:
        self.cli = cli
        self.gate = gate
        self.probe = probe
        self._app = app if app is not None else build_app()
        self._background: InProcessRun | None = None

    @property
    def run_dir(self):
        return self.cli.run_dir

    @property
    def config_path(self):
        return self.cli.config_path

    @property
    def data_dir(self):
        return self.cli.data_dir

    @property
    def credential_env(self) -> dict[str, str]:
        return self.cli.credential_env

    def run(self, args: Iterable[str], *, background: bool = False,
            timeout: float = 180.0) -> InProcessRun:
        """Run ``market <args>``; in the background, return once it has started."""
        args_list = list(args)
        self._refuse_unless_quiet(args_list, background=background)
        pre = frozenset(path.stem for path in self.run_dir.glob("*.jsonl")) \
            if self.run_dir.exists() else frozenset()
        run = InProcessRun(run_dir=self.run_dir, pre_existing_run_ids=pre,
                           _run_id=run_id_from_args(args_list), stop=self.stop)
        run.thread = threading.Thread(target=self._invoke, args=(run, args_list),
                                      name=f"market {' '.join(args_list[:2])}", daemon=True)
        log.info("[in-process buyer] market %s%s", " ".join(args_list),
                 " (background)" if background else "")
        if background:
            self._background = run
            run.thread.start()
            return run
        with _logging_held():
            run.thread.start()
            run.wait(timeout)
        return run

    def _invoke(self, run: InProcessRun, args: list[str]) -> None:
        try:
            run.result = CliRunner().invoke(
                self._app, ["--config", str(self.cli.config_path), *args],
            )
        except BaseException as error:  # a KeyboardInterrupt the command left unhandled
            run.error = error
        finally:
            run.ended = True
            self.gate.notify()

    def _refuse_unless_quiet(self, args: list[str], *, background: bool) -> None:
        running = self._background
        if running is None or running.exited:
            return
        if background:
            raise AssertionError(
                f"refused market {' '.join(args)}: a command already runs in the background")
        if not self.gate.parked:
            raise AssertionError(
                f"refused market {' '.join(args)}: the background command is between gates, "
                "and a command runs only while it is parked at the gate")

    @property
    def background(self) -> InProcessRun:
        assert self._background is not None, "no command was run in the background"
        return self._background

    def wait_parked(self, timeout: float = STEP_TIMEOUT_SECONDS) -> None:
        """Wait until the background command is parked at the gate; fail if it ends."""
        self._settle(timeout)
        if not self.gate.parked:
            run = self.background
            raise AssertionError(
                f"the background command ended (exit {run.returncode}) instead of waiting at "
                f"the gate; stderr: {run.stderr()[-1500:]}")

    def release(self, intervals: int = 1) -> None:
        """Release the parked wait ``intervals`` times, each once the command is
        parked again, then wait until it is parked again or has ended."""
        with self._streams_kept():
            for _ in range(intervals):
                self.wait_parked()
                self.gate.release()
                self._settle(STEP_TIMEOUT_SECONDS)

    def interrupt(self, timeout: float = STEP_TIMEOUT_SECONDS) -> InProcessRun:
        """Interrupt the parked background command and wait for it to end."""
        with self._streams_kept():
            self.wait_parked()
            self.gate.interrupt()
            run = self.background
            run.wait(timeout)
        return run

    def wait_ended(self, timeout: float = STEP_TIMEOUT_SECONDS) -> InProcessRun:
        with self._streams_kept():
            run = self.background
            run.wait(timeout)
        return run

    def stop(self) -> None:
        """End a background command still running: interrupt it at the gate."""
        run = self._background
        if run is None or run.exited:
            return
        with self._streams_kept():
            self._settle(STEP_TIMEOUT_SECONDS)
            if self.gate.parked:
                self.gate.interrupt()
            run.wait(STEP_TIMEOUT_SECONDS)

    @contextlib.contextmanager
    def _streams_kept(self) -> Iterator[None]:
        """Put back the running stage's streams if the background command ends
        within: ``CliRunner`` restores those of the stage that started it."""
        saved = sys.stdin, sys.stdout, sys.stderr
        try:
            yield
        finally:
            run = self._background
            if run is not None and run.exited:
                sys.stdin, sys.stdout, sys.stderr = saved

    def _settle(self, timeout: float) -> None:
        """Wait until the background command is parked at the gate or has ended."""
        run = self.background
        # The gate's condition holds a re-entrant lock, so ``parked`` reads
        # under it.
        if not self.gate.wait_until(lambda: self.gate.parked or run.ended, timeout):
            raise AssertionError(
                f"the background command neither reached the gate nor ended within {timeout}s")


@contextlib.contextmanager
def _logging_held() -> Iterator[None]:
    """Hold the process's logging while a command runs in the foreground.

    pytest's live logging suspends and resumes its capture around each record
    it prints, which points ``sys.stdout`` and ``sys.stderr`` back at that
    capture, so a record the command's own requests log would take its output
    from under ``CliRunner`` mid-command. The stage is blocked on the command
    meanwhile, and a background command is parked at the gate, logging nothing.
    """
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        yield
    finally:
        logging.disable(previous)


@contextlib.contextmanager
def in_process_buyer(cli: BuyerCli, *, command_module: Any,
                     app: typer.Typer | None = None) -> Iterator[InProcessBuyer]:
    """``cli``'s buyer run in the harness's process for the context, normally a module.

    ``command_module`` is the domain CLI module defining ``watchdog_probe`` and
    ``wait_clock`` (``arkhai_vms_buyer.buy_cli``, ``arkhai_bare_metal_buyer.cli``).
    The buyer's environment and both factories are set for the context and
    restored when it ends, after any command still running is interrupted, and
    so is the configuration path its ``--config`` set for the process.
    """
    with cli.config_path.open("rb") as stream:
        configured = tomllib.load(stream)
    if "time" in configured:
        raise AssertionError(
            f"{cli.config_path} states a [time] table: an in-process buyer reads the harness's "
            "installed lane-time source, so its configuration names none")
    gate, probe = WaitGate(), ProgrammedProbe()
    clock = gate.wait_clock()
    with pytest.MonkeyPatch.context() as patch:
        for name, value in cli.environment().items():
            patch.setenv(name, value)
        patch.setattr(command_module, "watchdog_probe", probe.factory)
        patch.setattr(command_module, "wait_clock", lambda: clock)
        buyer = InProcessBuyer(cli, gate, probe, app=app)
        try:
            yield buyer
        finally:
            try:
                buyer.stop()
            finally:
                set_user_config_path(None)
