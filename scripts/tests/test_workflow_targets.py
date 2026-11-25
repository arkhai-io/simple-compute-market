"""The root Makefile has the change workflow's targets only where the workflow is
installed, and every target of its own works without it.

Static configuration tests: the committed root Makefile read by make — its help, its
dry runs, and the targets it has — with the workflow's command absent from the path,
as CI runs it. That the installed workflow's fragment is included where the command
is on the path is the workflow's wiring here, which no test holds.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _path_without_the_workflow() -> list[str]:
    return [entry for entry in os.environ["PATH"].split(os.pathsep)
            if entry and not (Path(entry) / "change-workflow").exists()]


def _make(*arguments: str, path: list[str]) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items()
           if key not in ("MAKEFLAGS", "MFLAGS", "MAKEOVERRIDES", "MAKELEVEL")}
    return subprocess.run(["make", "--no-print-directory", "-C", str(ROOT), *arguments],
                          capture_output=True, text=True,
                          env={**env, "PATH": os.pathsep.join(path)})


def _help_targets(done: subprocess.CompletedProcess[str]) -> set[str]:
    return {line.split()[0] for line in done.stdout.splitlines() if line.strip()}


def test_without_the_workflow_its_targets_do_not_exist_and_nothing_is_printed() -> None:
    path = _path_without_the_workflow()
    assert shutil.which("change-workflow", path=os.pathsep.join(path)) is None

    helped = _make("help", path=path)
    design = _make("design", "CHANGE=x", path=path)

    assert (helped.returncode, helped.stderr) == (0, "")
    targets = _help_targets(helped)
    assert {"validate-local", "check-repository", "code-snapshot"} <= targets
    assert not {"design", "check-change", "check-spec-index",
                "check-decision-destinations"} & targets
    assert design.returncode != 0
    assert "No rule to make target 'design'" in design.stderr


@pytest.mark.parametrize("target", ["check-change", "check-spec-index",
                                    "check-decision-destinations", "design-review"])
def test_without_the_workflow_the_targets_calling_it_do_not_exist(target: str) -> None:
    """A target that runs the workflow's command, or a target of its fragment, is the
    workflow's: without it, make has no rule for it rather than doing nothing."""
    done = _make(target, "CHANGE=x", path=_path_without_the_workflow())

    assert done.returncode != 0
    assert f"No rule to make target '{target}'" in done.stderr


def test_without_the_workflow_this_repositorys_targets_call_no_workflow() -> None:
    dry = _make("-n", "code-snapshot", "validate-local", "review-diff", "last-diff",
                path=_path_without_the_workflow())

    assert dry.returncode == 0, dry.stderr
    assert "change-workflow " not in dry.stdout
    assert "round-view" not in dry.stdout


def test_the_validation_and_diff_targets_ask_not_to_run_during_a_round_view() -> None:
    helped = _make("help", path=_path_without_the_workflow()).stdout.splitlines()
    caution = ("not while a round view is open, when the branch points at the round's base "
               "rather than its commit")

    cautioned = {line.split()[0] for line in helped if caution in line}

    assert cautioned == {"validate-local", "validate-ci", "validate-helm", "run-e2e",
                         "run-ci", "review-diff", "last-diff"}
