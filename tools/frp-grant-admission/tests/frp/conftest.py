"""The real-frp tests' binaries and stack, and the gate that fails when they skip.

The binaries come from `tests/frp_fetch.py`. `FRP_GATE=1`, which `make test-frp`
sets, fetches and verifies them, and then a missing binary, a skipped test, or no
test at all fails the run. Otherwise only `FRPS_BIN` and `FRPC_BIN` supply them, and
without those every test here skips, so the default suite stays offline and quick.
Whichever supplied them, both binaries must report the release the pins file names.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.frp.stack import FrpStack, binary_version
from tests.frp_fetch import Binaries, FetchError, NoBinaries, load_pins, resolve
from tests.rfc8032 import TEST_1, TEST_2

GATE = os.environ.get("FRP_GATE") == "1"

_skipped = 0
_provenance: str | None = None


def pytest_collectreport(report: pytest.CollectReport) -> None:
    global _skipped
    if report.skipped:
        _skipped += 1


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    global _skipped
    if report.skipped:
        _skipped += 1


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    # The gate proves frps's behaviour only by running it: a skip is a failure there.
    if GATE and (_skipped or session.testscollected == 0) and exitstatus == 0:
        session.exitstatus = 1


def pytest_terminal_summary(terminalreporter: pytest.TerminalReporter) -> None:
    # A gate run on FRPS_BIN and FRPC_BIN passes as one on the pinned archive does, so
    # the output says which binaries it ran; pytest captures a fixture's own output.
    if _provenance is not None:
        terminalreporter.write_line(f"frp binaries: {_provenance}")


@pytest.fixture(scope="session")
def frp_binaries() -> Binaries:
    global _provenance
    try:
        binaries = resolve(fetching=GATE)
    except NoBinaries as missing:
        if GATE:
            pytest.fail(str(missing))
        pytest.skip(str(missing))
    except FetchError as error:
        pytest.fail(str(error))
    _provenance = binaries.provenance
    pinned = load_pins().version
    for binary in (binaries.frps, binaries.frpc):
        reported = binary_version(binary)
        if reported != pinned:
            pytest.fail(f"{binary} reports version {reported!r}; frp-pins.toml names {pinned}")
    return binaries


@pytest.fixture
def frp_stack(frp_binaries: Binaries, tmp_path: Path) -> Iterator[FrpStack]:
    """frps on runtime ports with the plugin configured, the plugin not yet started.

    Issuer A holds TEST 1 and TEST 2, so removing TEST 1 leaves it a key.
    """
    stack = FrpStack.create(frp_binaries, tmp_path)
    stack.write_plugin_configuration((TEST_1, TEST_2))
    try:
        stack.start_frps()
        yield stack
    finally:
        stack.close()
