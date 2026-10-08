"""Tests for the observational validation of the commit at HEAD."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Sequence

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "validate_slice.py"
_SPEC = importlib.util.spec_from_file_location("validate_slice", SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
validator = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = validator
_SPEC.loader.exec_module(validator)

COMMIT = "0123456789abcdef0123456789abcdef01234567"
VM_MARKERS = "e2e_deal or multi_registry or e2e_listing_shapes"
BARE_METAL_MARKERS = "e2e_bare_metal_publication"


class Fake:
    """Records commands; fails the ones named; dirties the worktree after a step."""

    def __init__(self, *, fail: Sequence[str] = (), output: dict[str, str] | None = None,
                 dirty_after: str | None = None, context: str = "docker-desktop",
                 markers: dict[str, str] | None = None) -> None:
        self.fail = set(fail)
        self.output = output or {}
        self.dirty_after = dirty_after
        self.context = context
        self.markers = markers or {"E2E_MODULE": VM_MARKERS,
                                   "E2E_BARE_METAL_MODULE": BARE_METAL_MARKERS}
        self.dirty: list[str] = []
        self.commands: list[list[str]] = []

    def run(self, command: Sequence[str], log: Path) -> int:
        command = list(command)
        self.commands.append(command)
        name = log.stem
        log.write_text(self.output.get(name, f"{name} output\n"), "utf-8")
        if name == self.dirty_after:
            self.dirty = [" M e2e-tests/uv.lock"]
        return 2 if name in self.fail else 0

    def read(self, command: Sequence[str]) -> str:
        command = list(command)
        if command == ["git", "rev-parse", "HEAD"]:
            return COMMIT + "\n"
        if command[:2] == ["git", "status"]:
            return "\n".join(self.dirty)
        if command == ["kubectl", "config", "current-context"]:
            return self.context + "\n"
        if command[-1].startswith("print-"):
            return self.markers[command[-1].removeprefix("print-")] + "\n"
        raise AssertionError(f"unexpected read: {command}")

    def ran(self) -> list[str]:
        return [" ".join(command) for command in self.commands]


def _validation(tmp_path: Path, fake: Fake, part: str) -> object:
    clock = iter(float(n) for n in range(1000))
    return validator.Validation(part, root=tmp_path, runner=fake.run, read=fake.read,
                                clock=lambda: next(clock))


def _storefront_env(tmp_path: Path) -> None:
    python = tmp_path / validator.STOREFRONT_PYTHON
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\n", "utf-8")
    python.chmod(0o755)


def _helm(tmp_path: Path, fake: Fake, **options: object) -> object:
    options.setdefault("probe", lambda port: True)
    options.setdefault("sleep", lambda seconds: None)
    return validator.validate_helm(_validation(tmp_path, fake, "helm"), **options)


def _results(summary: object) -> dict[str, str]:
    return {step.name: step.result for step in summary.steps}


# --- local part ---------------------------------------------------------------

def test_local_runs_packaging_then_tests_and_writes_a_summary(tmp_path: Path) -> None:
    fake = Fake()
    summary = validator.validate_local(_validation(tmp_path, fake, "local"))

    assert summary.passed
    assert fake.ran() == ["make check-packaging", "make test"]
    log_dir = tmp_path / ".snapshot/validation" / COMMIT[:12] / "local"
    written = json.loads((log_dir / "summary.json").read_text("utf-8"))
    assert written["commit"] == COMMIT and written["passed"] is True
    assert (log_dir / "test.log").read_text("utf-8") == "test output\n"


def test_local_stops_at_the_first_failure_with_its_output_tail(tmp_path: Path) -> None:
    fake = Fake(fail=["check-packaging"], output={"check-packaging": "lock is stale\n"})
    summary = validator.validate_local(_validation(tmp_path, fake, "local"))

    assert not summary.passed
    assert fake.ran() == ["make check-packaging"]
    failed = next(step for step in summary.steps if step.name == "check-packaging")
    assert failed.tail == ["lock is stale"]
    assert "lock is stale" in validator.render(summary)


def test_a_dirty_worktree_before_validation_runs_nothing(tmp_path: Path) -> None:
    fake = Fake()
    fake.dirty = ["?? scratch.txt"]
    summary = validator.validate_local(_validation(tmp_path, fake, "local"))

    assert not summary.passed
    assert fake.commands == []
    assert "?? scratch.txt" in summary.steps[0].detail


def test_a_step_that_rewrites_a_tracked_file_fails_validation(tmp_path: Path) -> None:
    fake = Fake(dirty_after="test")
    summary = validator.validate_local(_validation(tmp_path, fake, "local"))

    assert not summary.passed
    assert _results(summary)["test"] == "passed"
    assert _results(summary)["clean after"] == "failed"


# --- Helm part ----------------------------------------------------------------

def test_helm_runs_every_step_and_the_pipeline_scenarios_it_can_serve(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake()
    summary = _helm(tmp_path, fake)

    assert summary.passed
    assert fake.ran() == [
        "make -C helm test-render",
        "make build-dev",
        "make -C helm deploy",
        "make -C helm forward",
        "make -C e2e-tests test-module MODULE=e2e_deal or e2e_listing_shapes",
        "make -C helm unforward",
    ]
    assert set(summary.not_run) == {"multi_registry", "e2e_bare_metal_publication"}
    assert "not run multi_registry" in validator.render(summary)


def test_helm_refuses_a_kube_context_other_than_the_one_named(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake(context="production-cluster")
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert fake.commands == []
    assert "production-cluster" in summary.steps[-1].detail


def test_helm_without_the_storefront_environment_names_how_to_create_it(
    tmp_path: Path,
) -> None:
    fake = Fake()
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert fake.commands == []
    assert "make init-storefront" in summary.steps[-1].detail


def test_a_skipped_render_check_fails_validation(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    skip = "skip: STOREFRONT_PYTHON unset; the storefront loader check did not run"
    fake = Fake(output={"test-render": f"ok    a check\n{skip}\n"})
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert fake.ran() == ["make -C helm test-render"]
    render = next(step for step in summary.steps if step.name == "test-render")
    assert render.result == "failed" and render.tail == [skip]


def test_a_failing_scenario_still_unforwards(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake(fail=["e2e"])
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert fake.ran()[-1] == "make -C helm unforward"
    assert _results(summary)["e2e"] == "failed"


def test_ports_that_never_open_fail_before_the_scenarios_and_unforward(
    tmp_path: Path,
) -> None:
    _storefront_env(tmp_path)
    fake = Fake()
    summary = _helm(tmp_path, fake, probe=lambda port: port != 8001, forward_wait=3.0)

    assert not summary.passed
    assert "8001" in next(s for s in summary.steps if s.name == "forwarded ports").detail
    assert not any("e2e-tests" in command for command in fake.ran())
    assert fake.ran()[-1] == "make -C helm unforward"


def test_a_deploy_failure_does_not_forward(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake(fail=["deploy"])
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert fake.ran() == ["make -C helm test-render", "make build-dev", "make -C helm deploy"]


def test_a_marker_list_that_is_not_a_plain_disjunction_is_refused(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake(markers={"E2E_MODULE": "e2e_deal and not slow",
                         "E2E_BARE_METAL_MODULE": BARE_METAL_MARKERS})
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert fake.commands == []
    assert "e2e_deal and not slow" in summary.steps[-1].detail


def test_the_pipeline_marker_variables_exist_and_are_plain_disjunctions() -> None:
    markers = validator.pipeline_markers(validator._read)

    assert "e2e_deal" in markers
    assert "e2e_bare_metal_publication" in markers
    assert set(validator.HELM_EXCLUSIONS) <= set(markers)


def test_make_targets_delegate_to_the_script() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text("utf-8")

    assert "scripts/validate_slice.py local" in makefile
    assert 'scripts/validate_slice.py helm --context "$(HELM_CONTEXT)"' in makefile
