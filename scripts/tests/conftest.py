"""The scripts' tests import the scripts' own modules and packages by name, as the
scripts themselves do, so `scripts/` is on the path before any test is collected.

A suite run inside an unattended step of the change workflow inherits the step's
marker, `CHANGE_WORKFLOW_UNATTENDED`, under which the step's `git` refuses every
push, a test's own push to a remote in its temporary directory among them. Each test
runs as the owner's own command does, without it."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The workflow's unattended-run marker, as its make fragment names it.
UNATTENDED_RUN = "CHANGE_WORKFLOW_UNATTENDED"


@pytest.fixture(autouse=True)
def _outside_any_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(UNATTENDED_RUN, raising=False)
