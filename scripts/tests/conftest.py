"""The scripts' tests import the scripts' own modules and packages by name, as the
scripts themselves do, so `scripts/` is on the path before any test is collected.

A suite run inside an unattended step inherits the step's marker, under which the
engine's `git` around the step refuses every push, a test's own push to a remote in
its temporary directory among them, and the engine's commands act as that step's.
Each test runs as the owner's own command does, without it, and a test that runs
as a step sets it.

A test that launches the real sandbox asks for `sandbox_runs`
(`change_workflow_fixtures.needs_bwrap`): it is skipped, saying why, where the
engine's own probe finds bubblewrap cannot run, except under `SANDBOX_REQUIRED=1`,
which CI's packaging job sets, where it fails instead: such tests are
external-process integration, run in a gate that fails on a skip."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from change_workflow import sandbox  # noqa: E402  (needs the path above)
from change_workflow.common import UNATTENDED_RUN  # noqa: E402  (needs the path above)

# Why the sandbox cannot run here, asked once; None where it can.
PROBED = sandbox.probe()


@pytest.fixture(autouse=True)
def _outside_any_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UNATTENDED_RUN, raising=False)


@pytest.fixture
def sandbox_runs() -> None:
    """Skips a test that launches the real sandbox where it cannot run, or fails it
    under `SANDBOX_REQUIRED=1`."""
    if PROBED is None:
        return
    if os.environ.get("SANDBOX_REQUIRED") == "1":
        pytest.fail(f"SANDBOX_REQUIRED=1, and the sandbox cannot run: {PROBED}")
    pytest.skip(f"the sandbox cannot run: {PROBED}")
