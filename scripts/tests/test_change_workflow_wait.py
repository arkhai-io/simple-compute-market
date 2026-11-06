"""`change-workflow wait` returns as soon as a matching line is in the file, including
one written before it began or the file's unterminated last line, stops at the
harness's exit line when nothing matched, and gives up at its bound. Time is an
injected clock whose sleep advances it, so no test waits."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from change_workflow import cli
from change_workflow.wait import Ended, run, wait_for

COMMAND = Path(__file__).resolve().parents[1] / "change-workflow"


class Clock:
    """A clock that moves only when slept on, running `on_sleep` at each sleep."""

    def __init__(self, on_sleep: Callable[[float], None] = lambda now: None) -> None:
        self.now = 0.0
        self.slept: list[float] = []
        self._on_sleep = on_sleep

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
        self._on_sleep(self.now)


def test_a_line_already_written_returns_without_waiting(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.write_text("starting\nvalidation of abc, attempt 1: PASSED\nleaving\n")
    clock = Clock()

    line = wait_for(output, re.compile(r": (PASSED|FAILED)$"), timeout=60,
                    clock=clock, sleep=clock.sleep)

    assert line == "validation of abc, attempt 1: PASSED"
    assert clock.slept == []


def test_a_line_written_later_is_found_when_it_arrives(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.write_text("fetching\n")

    def grow(now: float) -> None:
        if now >= 3:
            with output.open("a") as handle:
                handle.write("Fetched e2e.yml run 7 (success) logs\n")

    clock = Clock(grow)
    line = wait_for(output, re.compile(r"^Fetched .* run \d+"), timeout=60,
                    clock=clock, sleep=clock.sleep)

    assert line == "Fetched e2e.yml run 7 (success) logs"
    assert clock.now == 3


def test_the_unterminated_last_line_matches(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.write_text("running\n[exited with code 0]")
    clock = Clock()

    assert wait_for(output, re.compile(r"exited with code"), timeout=5,
                    clock=clock, sleep=clock.sleep) == "[exited with code 0]"


def test_a_line_split_across_writes_matches_once_whole(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.write_text("attempt 1: PA")

    def finish(now: float) -> None:
        if now == 1:
            with output.open("a") as handle:
                handle.write("SSED\n")

    clock = Clock(finish)
    line = wait_for(output, re.compile(r": PASSED$"), timeout=10,
                    clock=clock, sleep=clock.sleep)

    assert line == "attempt 1: PASSED"


def test_a_file_not_yet_created_is_waited_for(tmp_path: Path) -> None:
    output = tmp_path / "out"

    def create(now: float) -> None:
        if now == 2:
            output.write_text("ERROR: the part could not start\n")

    clock = Clock(create)
    assert wait_for(output, re.compile(r"^ERROR:"), timeout=10, clock=clock,
                    sleep=clock.sleep) == "ERROR: the part could not start"


def test_a_command_that_ended_without_the_line_stops_the_wait(tmp_path: Path,
                                                              capsys) -> None:
    output = tmp_path / "out"
    output.write_text("Run E2E (7) has already completed with 'success'\n"
                      "Fetched e2e.yml run 7 (success) logs into /x.\n\n"
                      "[exited with code 0]\n")
    clock = Clock()

    status = run(output, re.compile("conclusion"), timeout=540, clock=clock,
                 sleep=clock.sleep)

    assert status == 3
    assert clock.slept == []
    assert "ended ([exited with code 0]) with no line" in capsys.readouterr().err


def test_the_exit_line_ends_a_wait_already_under_way(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.write_text("running\n")

    def finish(now: float) -> None:
        if now == 2:
            with output.open("a") as handle:
                handle.write("failed early\n\n[exited with code 2]")

    clock = Clock(finish)
    found = wait_for(output, re.compile(r": PASSED$"), timeout=540, clock=clock,
                     sleep=clock.sleep)

    assert found == Ended("[exited with code 2]")
    assert clock.now == 2


def test_a_matching_line_before_the_exit_line_is_still_returned(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.write_text("attempt 1: PASSED\n\n[exited with code 0]\n")
    clock = Clock()

    assert wait_for(output, re.compile(r": PASSED$"), timeout=5, clock=clock,
                    sleep=clock.sleep) == "attempt 1: PASSED"


def test_nothing_matching_gives_up_at_the_bound(tmp_path: Path, capsys) -> None:
    output = tmp_path / "out"
    output.write_text("still running\n")
    clock = Clock()

    status = run(output, re.compile("PASSED"), timeout=4.5, clock=clock, sleep=clock.sleep)

    assert status == 1
    assert clock.now == 4.5
    assert "matched 'PASSED' within 4.5s; wait again" in capsys.readouterr().err


def test_a_match_prints_its_line_and_exits_zero(tmp_path: Path, capsys) -> None:
    output = tmp_path / "out"
    output.write_text("done: PASSED\n")
    clock = Clock()

    assert run(output, re.compile("PASSED"), timeout=1, clock=clock, sleep=clock.sleep) == 0
    assert capsys.readouterr().out == "done: PASSED\n"


def test_the_command_refuses_a_malformed_pattern_or_bound(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.write_text("x\n")

    assert cli.main(["wait", str(output), "("], root=tmp_path) == 2
    assert cli.main(["wait", str(output), "x", "--timeout", "0"], root=tmp_path) == 2


def test_the_command_runs_as_an_executable(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.write_text("Created log archive /x.zip\n")

    ran = subprocess.run([sys.executable, str(COMMAND), "wait", str(output),
                          "^Created log archive"], cwd=COMMAND.parent, capture_output=True,
                         text=True, check=False)

    assert (ran.returncode, ran.stdout) == (0, "Created log archive /x.zip\n")
