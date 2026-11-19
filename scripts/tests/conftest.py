"""The scripts' tests import the scripts' own modules and packages by name, as the
scripts themselves do, so `scripts/` is on the path before any test is collected.

A suite run inside an unattended step inherits the step's marker, under which the
engine's `git` around the step refuses every push, a test's own push to a remote in
its temporary directory among them, and the engine's commands act as that step's.
Each test runs as the owner's own command does, without it, and a test that runs
as a step sets it."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from change_workflow.common import UNATTENDED_RUN  # noqa: E402  (needs the path above)


@pytest.fixture(autouse=True)
def _outside_any_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UNATTENDED_RUN, raising=False)
