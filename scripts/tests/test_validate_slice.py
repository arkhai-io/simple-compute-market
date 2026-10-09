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
                 markers: dict[str, str] | None = None, nodes: str = "docker-desktop=True\n",
                 docker_up: bool = True, volumes: Sequence[list[str]] = (),
                 installed: Sequence[tuple[str, str]] = (("arkhai-node-operator-registry-data",
                                                          ""),),
                 release_delay: int = 0) -> None:
        self.fail = set(fail)
        self.output = output or {}
        self.dirty_after = dirty_after
        self.context = context
        self.markers = markers or {"E2E_MODULE": VM_MARKERS,
                                   "E2E_BARE_METAL_MODULE": BARE_METAL_MARKERS}
        self.nodes = nodes
        self.docker_up = docker_up
        # The release's volumes before the uninstall, as (name, retention policy),
        # then successive answers to the volume query while they are deleted.
        self.installed = list(installed)
        self.volumes = list(volumes)
        self.undeployed = False
        # A port-forward from an earlier run holds the ports until it is stopped,
        # and keeps them for `release_delay` more probes while it exits.
        self.forwarding = True
        self.release_delay = release_delay
        self.held: set[int] = set()
        self.dirty: list[str] = []
        self.commands: list[list[str]] = []
        # Commands, cluster queries, and port probes, in the order they happened.
        self.events: list[str] = []

    def run(self, command: Sequence[str], log: Path) -> int:
        command = list(command)
        self.commands.append(command)
        name = log.stem
        self.events.append(name)
        log.write_text(self.output.get(name, f"{name} output\n"), "utf-8")
        if name == self.dirty_after:
            self.dirty = [" M e2e-tests/uv.lock"]
        if name in self.fail:
            return 2
        if name == "forward":
            self.forwarding = True
        elif name in ("stop forwards", "unforward"):
            self.forwarding = False
        elif name == "undeploy":
            self.undeployed = True
        return 0

    def probe(self, port: int) -> bool:
        self.events.append("probe")
        if port in self.held:
            return True
        if not self.forwarding and self.release_delay:
            self.release_delay -= 1
            return True
        return self.forwarding

    @property
    def forwarded(self) -> bool:
        return self.forwarding

    def read(self, command: Sequence[str]) -> str:
        command = list(command)
        if command == ["git", "rev-parse", "HEAD"]:
            return COMMIT + "\n"
        if command == ["git", "status", "--porcelain", "--untracked-files=all"]:
            return "\n".join(self.dirty)
        if command == ["kubectl", "config", "current-context"]:
            return self.context + "\n"
        if command[:2] == ["docker", "info"]:
            if not self.docker_up:
                raise validator.ValidationError("docker info failed: cannot connect")
            return "28.0.0\n"
        if command[:3] == ["kubectl", "get", "nodes"]:
            return self.nodes
        if command[:3] == ["kubectl", "get", "pvc"]:
            assert "app.kubernetes.io/instance=arkhai-node-operator" in command
            if command[-1].startswith("jsonpath="):
                self.events.append("retention query")
                return "".join(f"{name}={policy}\n" for name, policy in self.installed)
            self.events.append("volume query")
            if not self.undeployed:
                return "\n".join(f"persistentvolumeclaim/{name}" for name, _ in self.installed)
            return "\n".join(self.volumes.pop(0)) if self.volumes else ""
        if command[-1].startswith("print-"):
            name = command[-1].removeprefix("print-")
            settings = {"RELEASE": "arkhai-node-operator", "NAMESPACE": "default"}
            return settings.get(name, self.markers.get(name, "")) + "\n"
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
    options.setdefault("probe", fake.probe)
    options.setdefault("sleep", lambda seconds: None)
    options.setdefault("credentials", lambda: None)
    return validator.validate_helm(_validation(tmp_path, fake, "helm"), **options)


def _results(summary: object) -> dict[str, str]:
    return {step.name: step.result for step in summary.steps}


# --- local part ---------------------------------------------------------------

def test_local_runs_packaging_then_tests_and_writes_a_summary(tmp_path: Path) -> None:
    fake = Fake()
    summary = validator.validate_local(_validation(tmp_path, fake, "local"))

    assert summary.passed
    assert fake.ran() == ["make dist-clean", "make check-packaging", "make test"]
    log_dir = tmp_path / ".snapshot/validation" / COMMIT[:12] / "local" / "1"
    written = json.loads((log_dir / "summary.json").read_text("utf-8"))
    assert written["commit"] == COMMIT and written["passed"] is True
    assert (log_dir / "test.log").read_text("utf-8") == "test output\n"


def test_local_stops_at_the_first_failure_with_its_output_tail(tmp_path: Path) -> None:
    fake = Fake(fail=["check-packaging"], output={"check-packaging": "lock is stale\n"})
    summary = validator.validate_local(_validation(tmp_path, fake, "local"))

    assert not summary.passed
    assert fake.ran() == ["make dist-clean", "make check-packaging"]
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
        "make -C helm check-local-secrets",
        "make -C helm unforward",
        "make dist-clean",
        "make build-dev",
        "make -C domains/vms/storefront reinit",
        "make -C helm test-render",
        "make -C helm undeploy",
        "make -C helm deploy-local",
        "make -C helm forward",
        "make -C e2e-tests test-module MODULE=contracts or e2e_alkahest_escrow_codecs",
        "make -C helm unforward",
    ]
    assert set(summary.not_run) == {"e2e_deal", "multi_registry", "e2e_listing_shapes",
                                    "e2e_bare_metal_publication"}
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
    assert fake.ran()[-1] == "make -C helm test-render"
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
    def probe(port: int) -> bool:
        return fake.probe(port) and port != 8001
    summary = _helm(tmp_path, fake, probe=probe, forward_wait=3.0)

    assert not summary.passed
    assert "8001" in next(s for s in summary.steps if s.name == "forwarded ports").detail
    assert not any("e2e-tests" in command for command in fake.ran())
    assert fake.ran()[-1] == "make -C helm unforward"


def test_a_deploy_failure_does_not_forward(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake(fail=["deploy-local"])
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert fake.ran()[-1] == "make -C helm deploy-local"
    assert "make -C helm forward" not in fake.ran()


def test_a_marker_list_that_is_not_a_plain_disjunction_is_refused(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake(markers={"E2E_MODULE": "e2e_deal and not slow",
                         "E2E_BARE_METAL_MODULE": BARE_METAL_MARKERS})
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert "make dist-clean" not in fake.ran()
    assert "e2e_deal and not slow" in summary.steps[-1].detail


def test_each_attempt_keeps_its_own_logs(tmp_path: Path) -> None:
    first = validator.validate_local(_validation(tmp_path, Fake(fail=["test"]), "local"))
    second = validator.validate_local(_validation(tmp_path, Fake(), "local"))

    part = tmp_path / ".snapshot/validation" / COMMIT[:12] / "local"
    assert (first.attempt, second.attempt) == (1, 2)
    written = [json.loads((part / n / "summary.json").read_text("utf-8")) for n in ("1", "2")]
    assert [(s["attempt"], s["passed"]) for s in written] == [(1, False), (2, True)]


def test_a_port_held_by_something_else_stops_before_the_release_is_replaced(
    tmp_path: Path,
) -> None:
    _storefront_env(tmp_path)
    fake = Fake()
    fake.held = {8545}
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert "8545" in next(s for s in summary.steps if s.name == "ports free").detail
    assert "make dist-clean" not in fake.ran()


def test_the_deploy_waits_for_the_old_release_volumes_to_go(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake(volumes=[["persistentvolumeclaim/arkhai-node-operator-registry-data"], []])
    summary = _helm(tmp_path, fake)

    assert summary.passed
    assert "make -C helm deploy-local" in fake.ran()


def test_a_volume_still_deleting_at_the_deadline_stops_before_deploying(
    tmp_path: Path,
) -> None:
    _storefront_env(tmp_path)
    survivor = ["persistentvolumeclaim/arkhai-node-operator-provisioning-data"]
    fake = Fake(volumes=[survivor] * 10)
    summary = _helm(tmp_path, fake, volume_wait=3.0)

    assert not summary.passed
    volumes = next(s for s in summary.steps if s.name == "release volumes")
    assert "arkhai-node-operator-provisioning-data" in volumes.detail
    assert "make -C helm deploy-local" not in fake.ran()


def test_a_retained_volume_stops_before_anything_is_built(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake(installed=[("arkhai-node-operator-registry-data", ""),
                           ("arkhai-node-operator-provisioning-data", "keep")])
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    retained = next(s for s in summary.steps if s.name == "retained volumes")
    assert "arkhai-node-operator-provisioning-data" in retained.detail
    assert "registry-data" not in retained.detail
    assert "make dist-clean" not in fake.ran()
    assert "make -C helm undeploy" not in fake.ran()


def test_the_release_is_replaced_only_in_order(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake(volumes=[["persistentvolumeclaim/arkhai-node-operator-registry-data"], []])
    _helm(tmp_path, fake)

    events = fake.events
    def first(event: str) -> int:
        return events.index(event)
    assert first("stop forwards") < first("probe") < first("retention query") \
        < first("dist-clean")
    assert first("undeploy") < first("volume query") < first("deploy-local") < first("forward")


def test_ports_still_held_by_exiting_forwards_are_waited_for(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake(release_delay=3)
    summary = _helm(tmp_path, fake)

    assert summary.passed
    assert _results(summary)["ports free"] == "passed"


@pytest.mark.parametrize("fault, step", [
    ({"docker_up": False}, "docker"),
    ({"nodes": "docker-desktop=False\n"}, "kube node"),
    ({"nodes": ""}, "kube node"),
    ({"fail": ["local secrets"]}, "local secrets"),
])
def test_an_unready_environment_stops_before_anything_is_built(
    tmp_path: Path, fault: dict[str, object], step: str
) -> None:
    _storefront_env(tmp_path)
    fake = Fake(**fault)
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert _results(summary)[step] == "failed"
    assert "make dist-clean" not in fake.ran()


def test_a_silent_credential_helper_warns_without_failing(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    summary = _helm(tmp_path, Fake(), credentials=lambda: "helper did not answer")

    assert summary.passed
    assert _results(summary)["credential helper"] == "warning"
    assert "warning credential helper" in validator.render(summary)


@pytest.mark.parametrize("body, expected", [
    ("sleep 5", "did not answer within 0.2s"),
    ("exit 3", "exited 3"),
    (None, "could not run"),
])
def test_a_credential_helper_that_does_not_answer_is_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str | None, expected: str
) -> None:
    # A real helper executable on PATH: the probe is the subprocess boundary itself.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if body is not None:
        helper = bin_dir / "docker-credential-test-store"
        helper.write_text(f"#!/bin/sh\n{body}\n", "utf-8")
        helper.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:/usr/bin:/bin")
    config_dir = tmp_path / "docker"
    config_dir.mkdir()
    (config_dir / "config.json").write_text('{"credsStore": "test-store"}', "utf-8")
    monkeypatch.setenv("DOCKER_CONFIG", str(config_dir))

    warning = validator._credential_helper_warning(timeout=0.2)

    assert warning and expected in warning and "docker-credential-test-store" in warning


def test_no_credential_store_needs_no_warning(tmp_path: Path) -> None:
    config = tmp_path / "config.json"
    config.write_text("{}", "utf-8")
    assert validator._credential_helper_warning(config) is None


def test_every_secret_the_preflight_checks_is_named_by_the_chart_values() -> None:
    makefile = (REPO_ROOT / "helm" / "Makefile").read_text("utf-8")
    listed = makefile.split("LOCAL_SECRETS :=", 1)[1].split("\n\n", 1)[0]
    names = [name for name in listed.replace("\\", " ").split() if name.startswith("arkhai-")]
    values = (REPO_ROOT / "helm" / "values.yaml").read_text("utf-8")

    assert len(names) == 6
    assert all(name in values for name in names)


def test_the_pipeline_marker_variables_exist_and_are_plain_disjunctions() -> None:
    markers = validator.pipeline_markers(validator._read)

    assert "e2e_deal" in markers
    assert "e2e_bare_metal_publication" in markers


def test_every_helm_scenario_is_a_declared_marker() -> None:
    declared = (REPO_ROOT / "e2e-tests" / "pyproject.toml").read_text("utf-8")

    for marker in validator.HELM_SCENARIOS:
        assert f'"{marker}:' in declared


def test_all_scenarios_runs_every_pipeline_scenario(tmp_path: Path) -> None:
    _storefront_env(tmp_path)
    fake = Fake()
    summary = _helm(tmp_path, fake, scenarios=None)

    assert summary.not_run == {}
    assert ("make -C e2e-tests test-module MODULE=e2e_deal or multi_registry or "
            "e2e_listing_shapes or e2e_bare_metal_publication") in fake.ran()


def test_make_targets_delegate_to_the_script() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text("utf-8")

    assert "scripts/validate_slice.py local" in makefile
    assert 'scripts/validate_slice.py helm --context "$(HELM_CONTEXT)"' in makefile
    assert "--all-scenarios" in makefile
    # The instruction travels with the invocation into the validation session.
    assert "/change-validate $(CHANGE)$(if $(filter 1,$(HELM_ALL_SCENARIOS))" in makefile
