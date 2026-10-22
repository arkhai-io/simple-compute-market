"""Tests for the observational validation of the commit at HEAD."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
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
CHANGE = "pilot"
NAMESPACE = "validate-pilot"
RELEASE = "arkhai-node-operator"
POD = f"{RELEASE}-e2e-tests-e2e-scenarios"
GIB = 2**30
NOW = datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc)


class Fake:
    """A checkout, a Docker daemon, and a cluster, as validation's commands see them.

    Records every command it runs, answers every read, and fails the steps named.
    Each namespace holds workloads (kind/name to replicas) and the release's volumes.
    """

    def __init__(self, *, fail: Sequence[str] = (), output: dict[str, str] | None = None,
                 dirty_after: str | None = None, context: str = "docker-desktop",
                 markers: dict[str, str] | None = None, nodes: str = "docker-desktop=True\n",
                 docker_up: bool = True, cast: bool = True, metrics: bool = True,
                 allocatable: str = "16Gi", workloads: dict[str, dict[str, int]] | None = None,
                 volumes: Sequence[list[str]] = (), retained: Sequence[str] = (),
                 head_after: str | None = None, exit_code: str = "0",
                 memory: Sequence[str] = ("500Mi",), restarts: int = 0,
                 samples_during_scenarios: int = 0, test_volume_lingers: int = 0,
                 broken_read: str | None = None, failing_read: str | None = None) -> None:
        self.fail = set(fail)
        self.output = output or {}
        self.dirty_after = dirty_after
        # The step after which HEAD moves, as a commit or branch switch would.
        self.head_after = head_after
        self.head = COMMIT
        self.context = context
        self.markers = markers or {"E2E_MODULE": VM_MARKERS,
                                   "E2E_BARE_METAL_MODULE": BARE_METAL_MARKERS}
        self.nodes = nodes
        self.docker_up = docker_up
        self.cast = cast
        self.metrics = metrics
        self.allocatable = allocatable
        self.workloads = {namespace: dict(found) for namespace, found in (workloads or {}).items()}
        # Successive answers to the volume query once a deletion has started.
        self.volumes = list(volumes)
        self.deleting = False
        self.retained = list(retained)
        # The deal test's buyer-profile volume, which no chart owns: deleted by
        # validation, still listed for `test_volume_lingers` looks, then created
        # again by `topology-secrets`.
        self.test_volume = True
        self.test_volume_lingers = test_volume_lingers
        self.exit_code = exit_code
        # The namespace's memory at each sample, the last repeated.
        self.memory = list(memory)
        self.restarts = restarts
        # The scenario run waits until the sampler has sampled this many times
        # while it runs, so the test needs no sleep.
        self.samples_during_scenarios = samples_during_scenarios
        self.samples = 0
        self.sampled = threading.Condition()
        # A read containing this text raises what no handler expects; one
        # containing `failing_read` fails as a command does.
        self.broken_read = broken_read
        self.failing_read = failing_read
        self.dirty: list[str] = []
        self.commands: list[list[str]] = []
        self.reads: list[list[str]] = []
        # Commands and cluster reads, in the order they happened.
        self.events: list[str] = []

    def run(self, command: Sequence[str], log: Path) -> int:
        command = list(command)
        self.commands.append(command)
        name = log.stem
        self.events.append(name)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(self.output.get(name, f"{name} output\n"), "utf-8")
        if name == self.dirty_after:
            self.dirty = [" M e2e-tests/uv.lock"]
        if name == self.head_after:
            self.head = "f" * 40
        if name in self.fail:
            return 2
        namespace = command[command.index("--namespace") + 1] if "--namespace" in command else None
        if name in ("scale down", "scale to zero"):
            for workload in command[command.index("--replicas=0") + 1:]:
                self.workloads[namespace][workload] = 0
        elif name in ("delete volumes", "undeploy"):
            self.deleting = True
        elif name == "delete test volumes":
            self.test_volume = self.test_volume_lingers > 0
        elif name == "namespace secrets":
            self.test_volume = True
        elif name == "e2e" and self.samples_during_scenarios:
            with self.sampled:
                wanted = self.samples + self.samples_during_scenarios
                assert self.sampled.wait_for(lambda: self.samples >= wanted, timeout=10), (
                    "the sampler did not sample while the scenarios ran")
        elif name in ("deploy", "install"):
            # An upgrade leaves a count scaled outside it as it is; an install
            # creates the release's workloads at the chart's counts.
            target = NAMESPACE if f"CHANGE={CHANGE}" in command else "default"
            found = self.workloads.setdefault(target, {})
            if not any(workload.split("/", 1)[1].startswith(RELEASE + "-") for workload in found):
                found.update({f"deployment/{RELEASE}-registry": 1,
                              f"deployment/{RELEASE}-storefront-bob": 1})
        elif name == "resume":
            target = NAMESPACE if f"CHANGE={CHANGE}" in command else "default"
            named = [argument.removeprefix("RESUME_RELEASES=") for argument in command
                     if argument.startswith("RESUME_RELEASES=")]
            self.workloads[target] = {
                workload: 1 if not named or workload.split("/", 1)[1].startswith(
                    named[0] + "-") else replicas
                for workload, replicas in self.workloads[target].items()}
        return 0

    def read(self, command: Sequence[str]) -> str:
        command = list(command)
        self.reads.append(command)
        if self.broken_read and self.broken_read in " ".join(command):
            raise RuntimeError("an unexpected answer")
        if self.failing_read and self.failing_read in " ".join(command):
            raise validator.ValidationError(f"{' '.join(command)} failed: refused")
        if command == ["git", "rev-parse", "HEAD"]:
            return self.head + "\n"
        if command == ["git", "status", "--porcelain", "--untracked-files=all"]:
            return "\n".join(self.dirty)
        if command == ["kubectl", "config", "current-context"]:
            return self.context + "\n"
        if command[:2] == ["docker", "info"]:
            if not self.docker_up:
                raise validator.ValidationError("docker info failed: cannot connect")
            return "28.0.0\n"
        if command[:2] == ["cast", "--version"]:
            if not self.cast:
                raise validator.ValidationError("cast is required but was not found")
            return "cast 1.5.1\n"
        if command[:3] == ["kubectl", "get", "nodes"]:
            if "allocatable" in command[-1]:
                self.events.append("allocatable query")
                return self.allocatable + "\n"
            return self.nodes
        if command[:3] == ["kubectl", "get", "--raw"]:
            if not self.metrics:
                raise validator.ValidationError("the server could not find the resource")
            if command[-1].endswith("/nodes"):
                return "{}"
            assert command[-1].endswith(f"?labelSelector=app.kubernetes.io%2Finstance%3D{RELEASE}")
            self.events.append("memory sample")
            with self.sampled:
                used = self.memory.pop(0) if len(self.memory) > 1 else self.memory[0]
                self.samples += 1
                self.sampled.notify_all()
            return json.dumps({"items": [{"containers": [{"usage": {"memory": used}}]},
                                         {"containers": [{"usage": {"memory": "0"}}]}]})
        if command[:3] == ["kubectl", "get", "deployments,statefulsets"]:
            return self._workload_read(command)
        if command[:3] == ["kubectl", "get", "pvc"]:
            return self._volume_read(command)
        if command[:3] == ["kubectl", "get", "pods"]:
            return f"{RELEASE}-registry-1 {self.restarts}\n{POD} 0\n"
        if command[:3] == ["kubectl", "get", "pod"]:
            return self.exit_code
        if command[:2] == ["make", "-s"]:
            name = command[command.index("--eval") + 2].removeprefix("print-")
            settings = {"RELEASE": RELEASE, "TEST_VOLUMES": "arkhai-buyer-profiles"}
            return settings.get(name, self.markers.get(name, "")) + "\n"
        raise AssertionError(f"unexpected read: {command}")

    def _workload_read(self, command: list[str]) -> str:
        if "{.resources}" in command[-1]:
            self.events.append("resources query")
            namespace = command[command.index("--namespace") + 1]
            return "".join(f"{workload} app={{\"limits\":{{\"memory\":\"1Gi\"}}}}\n"
                           for workload in self.workloads.get(namespace, {})
                           if _selected(command, workload))
        if "--all-namespaces" in command:
            self.events.append("all workloads query")
            scope = list(self.workloads)
        else:
            self.events.append("workloads query")
            scope = [command[command.index("--namespace") + 1]]
        return "".join(f"{namespace} {workload.capitalize()} {replicas}\n"
                       for namespace in scope
                       for workload, replicas in self.workloads.get(namespace, {}).items()
                       if _selected(command, workload))

    def _volume_read(self, command: list[str]) -> str:
        if command[-1].startswith("jsonpath="):
            self.events.append("retention query")
            assert "--namespace" in command and command[command.index("--namespace") + 1] == "default"
            return "".join(f"{name}=keep\n" for name in self.retained)
        if "--selector" not in command:
            self.events.append("test volume query")
            listed = "persistentvolumeclaim/arkhai-buyer-profiles\n" if self.test_volume else ""
            if self.deleting and self.test_volume and self.test_volume_lingers:
                self.test_volume_lingers -= 1
                self.test_volume = self.test_volume_lingers > 0
            return listed
        self.events.append("volume query")
        if not self.deleting:
            return f"persistentvolumeclaim/{RELEASE}-registry-data\n"
        return "\n".join(self.volumes.pop(0)) if self.volumes else ""

    def ran(self) -> list[str]:
        return [" ".join(command) for command in self.commands]


def _selected(command: list[str], workload: str) -> bool:
    """Whether a workload, named `<kind>/<release>-<component>`, is in a read's selection."""
    if "--selector" not in command:
        return True
    release = command[command.index("--selector") + 1].removeprefix("app.kubernetes.io/instance=")
    return workload.split("/", 1)[1].startswith(release + "-")


def _validation(tmp_path: Path, fake: Fake, part: str,
                echo: object = lambda line: None) -> object:
    clock = iter(float(n) for n in range(1000))
    return validator.Validation(part, root=tmp_path, runner=fake.run, read=fake.read,
                                clock=lambda: next(clock), echo=echo, now=lambda: NOW)


def _storefront_env(tmp_path: Path, *, skip: str | None = None) -> None:
    """Each storefront's loader environment but the one `skip` names."""
    for _, project, _ in validator.LOADER_ENVIRONMENTS:
        if project == skip:
            continue
        python = tmp_path / project / ".venv/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\n", "utf-8")
        python.chmod(0o755)


def _capacity(tmp_path: Path, memory: int | None = None) -> Path:
    path = tmp_path / "validation-capacity.toml"
    if memory is None:
        path.write_text("[release]\n", "utf-8")
    else:
        validator.write_capacity(path, validator.CapacityFigure(
            memory, "2026-10-01T00:00:00+00:00", "an-earlier-change"))
    return path


def _helm(tmp_path: Path, fake: Fake, *, change: str | None = CHANGE,
          memory: int | None = None, **options: object) -> object:
    if not any((tmp_path / project / ".venv").exists()
               for _, project, _ in validator.LOADER_ENVIRONMENTS):
        _storefront_env(tmp_path)
    options.setdefault("sleep", lambda seconds: None)
    options.setdefault("credentials", lambda: None)
    options.setdefault("capacity", _capacity(tmp_path, memory))
    return validator.validate_helm(_validation(tmp_path, fake, "helm"), change=change,
                                   **options)


def _results(summary: object) -> dict[str, str]:
    return {step.name: step.result for step in summary.steps}


def _step(summary: object, name: str) -> object:
    return next(step for step in summary.steps if step.name == name)


def _attempt(tmp_path: Path, attempt: int = 1) -> Path:
    return tmp_path / ".snapshot/validation" / COMMIT[:12] / "helm" / str(attempt)


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


def test_a_part_says_when_each_step_starts_and_ends(tmp_path: Path) -> None:
    fake = Fake(fail=["test"])
    said: list[str] = []

    validator.validate_local(_validation(tmp_path, fake, "local", echo=said.append))

    logs = f".snapshot/validation/{COMMIT[:12]}/local/1"
    assert said == [
        f"dist-clean: running (make dist-clean; log {logs}/dist-clean.log)",
        "dist-clean: passed in 1.0s",
        f"check-packaging: running (make check-packaging; log {logs}/check-packaging.log)",
        "check-packaging: passed in 1.0s",
        f"test: running (make test; log {logs}/test.log)",
        "test: failed in 1.0s",
    ]


def test_a_step_line_is_printed_flushed(capsys: pytest.CaptureFixture[str]) -> None:
    validator._say("test: running")

    assert capsys.readouterr().out == "test: running\n"


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


def test_a_step_that_rewrites_a_tracked_file_fails_and_stops_the_part(tmp_path: Path) -> None:
    fake = Fake(dirty_after="check-packaging")
    summary = validator.validate_local(_validation(tmp_path, fake, "local"))

    assert not summary.passed
    failed = next(s for s in summary.steps if s.name == "check-packaging")
    assert failed.result == "failed" and "e2e-tests/uv.lock" in failed.detail
    assert "make test" not in fake.ran()


def test_each_attempt_keeps_its_own_logs(tmp_path: Path) -> None:
    first = validator.validate_local(_validation(tmp_path, Fake(fail=["test"]), "local"))
    second = validator.validate_local(_validation(tmp_path, Fake(), "local"))

    part = tmp_path / ".snapshot/validation" / COMMIT[:12] / "local"
    assert (first.attempt, second.attempt) == (1, 2)
    written = [json.loads((part / n / "summary.json").read_text("utf-8")) for n in ("1", "2")]
    assert [(s["attempt"], s["passed"]) for s in written] == [(1, False), (2, True)]


# --- Helm part: the change's namespace ------------------------------------------

def test_helm_runs_every_step_for_a_change_in_its_namespace(tmp_path: Path) -> None:
    fake = Fake()
    summary = _helm(tmp_path, fake)

    logs = _attempt(tmp_path)
    assert summary.passed, validator.render(summary)
    assert summary.namespace == NAMESPACE
    assert fake.ran() == [
        "make dist-clean",
        "make build-dev IMAGE_SUFFIX=-pilot",
        "make -C domains/vms/storefront reinit",
        "make -C domains/bare_metal/storefront reinit",
        "make -C helm test-render CHANGE=pilot",
        f"kubectl delete pods --namespace {NAMESPACE} --selector "
        f"app.kubernetes.io/instance={RELEASE} --ignore-not-found --wait=false",
        f"kubectl delete pvc --namespace {NAMESPACE} --selector "
        f"app.kubernetes.io/instance={RELEASE} --ignore-not-found --wait=false",
        f"kubectl delete pvc --namespace {NAMESPACE} arkhai-buyer-profiles "
        "--ignore-not-found --wait=false",
        "make -C helm topology-secrets CHANGE=pilot",
        "make -C helm deploy CHANGE=pilot EXTRA_VALUES=--values local-values.yaml "
        f"--values {logs}/images.json --values {logs}/scenarios.json",
        f"make -C helm resume CHANGE=pilot RESUME_RELEASES={RELEASE}",
        f"kubectl rollout status --namespace {NAMESPACE} "
        f"deployment/{RELEASE}-registry --timeout=600s",
        f"kubectl rollout status --namespace {NAMESPACE} "
        f"deployment/{RELEASE}-storefront-bob --timeout=600s",
        f"helm test {RELEASE} --namespace {NAMESPACE} --filter name={POD} --timeout 30m",
        f"kubectl logs --namespace {NAMESPACE} {POD}",
        f"kubectl logs --namespace {NAMESPACE} {RELEASE}-registry-1 --all-containers --prefix",
        f"kubectl logs --namespace {NAMESPACE} {POD} --all-containers --prefix",
        f"kubectl get pods --namespace {NAMESPACE} --selector "
        f"app.kubernetes.io/instance={RELEASE} --output json",
        f"kubectl get events --namespace {NAMESPACE} --sort-by=.lastTimestamp",
        "kubectl get events --all-namespaces --field-selector involvedObject.kind=Node "
        "--sort-by=.lastTimestamp",
        f"kubectl scale --namespace {NAMESPACE} --replicas=0 "
        f"deployment/{RELEASE}-registry deployment/{RELEASE}-storefront-bob",
    ]
    assert set(summary.not_run) == {"e2e_deal", "multi_registry", "e2e_listing_shapes",
                                    "e2e_bare_metal_publication"}
    assert "not run multi_registry" in validator.render(summary)


def test_the_overlay_names_the_changes_images_and_the_scenarios(tmp_path: Path) -> None:
    _helm(tmp_path, Fake())

    images = json.loads((_attempt(tmp_path) / "images.json").read_text("utf-8"))
    scenarios = json.loads((_attempt(tmp_path) / "scenarios.json").read_text("utf-8"))
    assert images["storefront"]["image"]["tag"] == "storefront-pilot"
    # The image the scenario pod runs.
    assert images["e2e-tests"]["integrationTests"]["tag"] == "e2e-tests-pilot"
    assert scenarios == {"e2e-tests": {"scenarios": {
        "markers": "contracts or e2e_alkahest_escrow_codecs"}}}


def test_no_namespace_but_the_changes_is_scaled_deleted_or_deployed(tmp_path: Path) -> None:
    fake = Fake(workloads={"validate-other": {"deployment/arkhai-node-operator-registry": 1}})
    _helm(tmp_path, fake)

    for command in fake.commands:
        if command[0] in ("kubectl", "helm"):
            if "--all-namespaces" in command:
                # The one read of every namespace this part runs: the nodes' events.
                assert command[:3] == ["kubectl", "get", "events"], command
            else:
                assert command[command.index("--namespace") + 1] == NAMESPACE, command
        if command[:3] == ["make", "-C", "helm"]:
            assert "CHANGE=pilot" in command, command
    for read in fake.reads:
        if read[0] == "kubectl" and read[1:3] != ["config", "current-context"]:
            if "--namespace" in read:
                assert read[read.index("--namespace") + 1] == NAMESPACE, read
            else:
                # Cluster-wide reads: the nodes, the metrics source, and the
                # release's workloads in every namespace, for the capacity check
                # and the evidence.
                assert read[2] in ("nodes", "--raw") or "--all-namespaces" in read, read
            if read[2] == "--raw" and "/namespaces/" in read[-1]:
                assert f"/namespaces/{NAMESPACE}/" in read[-1], read
        if read[:2] == ["make", "-s"] and "helm" in read:
            assert "CHANGE=pilot" in read, read
    assert fake.workloads["validate-other"] == {"deployment/arkhai-node-operator-registry": 1}


def test_without_a_change_the_part_runs_in_default_on_bare_tags(tmp_path: Path) -> None:
    fake = Fake()
    summary = _helm(tmp_path, fake, change=None)

    assert summary.passed, validator.render(summary)
    assert summary.namespace == "default"
    assert "make build-dev IMAGE_SUFFIX=" in fake.ran()
    # `default` is named, so a NAMESPACE inherited through MAKEFLAGS cannot redirect it.
    assert "make -C helm topology-secrets CHANGE= NAMESPACE=default" in fake.ran()
    assert all("CHANGE= NAMESPACE=default" in command for command in fake.ran()
               if command.startswith("make -C helm"))
    deploy = next(c for c in fake.ran() if c.startswith("make -C helm deploy"))
    assert "images.json" not in deploy and "scenarios.json" in deploy
    assert not (_attempt(tmp_path) / "images.json").exists()


@pytest.mark.parametrize("replicas", [0, 1])
def test_a_default_run_leaves_the_owners_other_release_alone(tmp_path: Path,
                                                             replicas: int) -> None:
    seller = "deployment/arkhai-bare-metal-seller-storefront"
    fake = Fake(workloads={"default": {seller: replicas, f"deployment/{RELEASE}-registry": 1}})
    summary = _helm(tmp_path, fake, change=None)

    assert summary.passed, validator.render(summary)
    # Neither scaled down with the release nor resumed with it.
    assert fake.workloads["default"][seller] == replicas
    assert f"make -C helm resume CHANGE= NAMESPACE=default RESUME_RELEASES={RELEASE}" in fake.ran()
    assert not any(seller in command for command in fake.ran())
    assert not any("arkhai-bare-metal-seller" in line
                   for line in (_attempt(tmp_path) / "resources.txt").read_text().splitlines())


def test_a_crashed_run_is_scaled_down_before_its_volumes_are_deleted(tmp_path: Path) -> None:
    fake = Fake(workloads={NAMESPACE: {f"deployment/{RELEASE}-registry": 1,
                                       f"deployment/{RELEASE}-storefront-bob": 0}})
    summary = _helm(tmp_path, fake)

    assert summary.passed, validator.render(summary)
    scale_down = _step(summary, "scale down")
    assert scale_down.detail == f"left up by an earlier run: deployment/{RELEASE}-registry"
    assert (f"kubectl scale --namespace {NAMESPACE} --replicas=0 deployment/{RELEASE}-registry"
            in fake.ran())
    assert fake.events.index("scale down") < fake.events.index("delete volumes")


def test_a_namespace_with_nothing_up_is_not_scaled_down(tmp_path: Path) -> None:
    summary = _helm(tmp_path, Fake(workloads={NAMESPACE: {f"deployment/{RELEASE}-registry": 0}}))

    assert summary.passed and "scale down" not in _results(summary)


def test_the_deploy_waits_for_the_old_volumes_to_go(tmp_path: Path) -> None:
    fake = Fake(volumes=[[f"persistentvolumeclaim/{RELEASE}-registry-data"], []])
    summary = _helm(tmp_path, fake)

    assert summary.passed
    assert fake.events.count("volume query") == 2
    assert fake.events.index("delete pods") < fake.events.index("delete volumes")
    assert fake.events.index("volume query") < fake.events.index("namespace secrets")


def test_the_deploy_waits_for_the_test_volume_too(tmp_path: Path) -> None:
    fake = Fake(test_volume_lingers=1)
    summary = _helm(tmp_path, fake)

    assert summary.passed, validator.render(summary)
    assert fake.events.count("test volume query") == 2
    assert fake.events.index("test volume query") < fake.events.index("namespace secrets")


def test_a_volume_still_deleting_at_the_deadline_stops_before_deploying(tmp_path: Path) -> None:
    survivor = [f"persistentvolumeclaim/{RELEASE}-provisioning-data"]
    fake = Fake(volumes=[survivor] * 10)
    summary = _helm(tmp_path, fake, volume_wait=3.0)

    assert not summary.passed
    assert f"{RELEASE}-provisioning-data" in _step(summary, "volumes gone").detail
    assert not any(command.startswith("make -C helm deploy") for command in fake.ran())


def test_a_refused_upgrade_falls_back_to_uninstall_and_install(tmp_path: Path) -> None:
    refusal = ('Error: UPGRADE FAILED: cannot patch "arkhai-node-operator-registry" with '
               "kind Deployment: spec.selector: Invalid value: field is immutable")
    fake = Fake(fail=["deploy"], output={"deploy": f"upgrading\n{refusal}\n"},
                volumes=[[], []])
    summary = _helm(tmp_path, fake)

    assert summary.passed, validator.render(summary)
    deploy = _step(summary, "deploy")
    assert deploy.result == "warning"
    assert deploy.detail == (f"the upgrade was refused ({refusal}), so the release is "
                             "uninstalled and installed")
    assert fake.events.index("deploy") < fake.events.index("undeploy") < fake.events.index(
        "install") < fake.events.index("resume")
    assert [step.name for step in summary.steps].count("volumes gone") == 2
    # The uninstall leaves the test volume `topology-secrets` just recreated, so
    # the second wait is for the release's own volumes alone.
    assert fake.events.count("test volume query") == 1 and fake.test_volume
    assert _results(summary)["install"] == "passed"


def test_a_failed_deploy_that_was_not_refused_fails_and_still_scales_down(
        tmp_path: Path) -> None:
    fake = Fake(fail=["deploy"], output={"deploy": "Error: timed out waiting for the condition\n"},
                workloads={NAMESPACE: {f"deployment/{RELEASE}-registry": 0}})
    # The failed upgrade left the workload up.
    original = fake.run

    def run(command: Sequence[str], log: Path) -> int:
        status = original(command, log)
        if log.stem == "deploy":
            fake.workloads[NAMESPACE][f"deployment/{RELEASE}-registry"] = 1
        return status

    fake.run = run
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert _results(summary)["deploy"] == "failed"
    assert "make -C helm undeploy CHANGE=pilot" not in fake.ran()
    assert "e2e" not in _results(summary)
    assert _results(summary)["scale to zero"] == "passed"
    assert (_attempt(tmp_path) / "events.log").exists()


# --- Helm part: scenarios and evidence ------------------------------------------

def test_the_scenario_pods_log_and_exit_status_are_collected(tmp_path: Path) -> None:
    fake = Fake(output={"scenarios": "2 passed\n"})
    summary = _helm(tmp_path, fake)

    logs = _attempt(tmp_path)
    record = {"pod": POD, "log": str((logs / "scenarios.log").relative_to(tmp_path)),
              "exit_code": 0}
    assert summary.evidence["scenarios"] == record
    assert json.loads((logs / "summary.json").read_text("utf-8"))["evidence"]["scenarios"] == record
    assert (logs / "scenarios.log").read_text("utf-8") == "2 passed\n"
    assert (logs / "scenarios.exit").read_text("utf-8") == "0\n"
    assert "stop scenario pod" not in _results(summary)
    assert "scenarios pod" in validator.render(summary)


def test_a_scenario_pod_with_no_exit_status_is_stopped(tmp_path: Path) -> None:
    fake = Fake(fail=["e2e"], exit_code="")
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert summary.evidence["scenarios"]["exit_code"] is None
    assert (f"kubectl delete pod {POD} --namespace {NAMESPACE} --ignore-not-found "
            "--wait=false") in fake.ran()


def test_a_failing_scenario_run_still_keeps_the_evidence_and_scales_to_zero(
        tmp_path: Path) -> None:
    fake = Fake(fail=["e2e"], exit_code="1")
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert _results(summary)["e2e"] == "failed"
    assert summary.evidence["scenarios"]["exit_code"] == 1
    assert (_attempt(tmp_path) / "pods" / f"{RELEASE}-registry-1.log").exists()
    assert fake.ran()[-1].startswith(f"kubectl scale --namespace {NAMESPACE} --replicas=0")
    assert set(fake.workloads[NAMESPACE].values()) == {0}


def test_a_scenario_pod_that_exited_non_zero_fails_the_step(tmp_path: Path) -> None:
    fake = Fake(exit_code="5")
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert _step(summary, "e2e").detail == f"{POD} exited 5"
    assert summary.evidence["events"] and summary.evidence["resources"]
    assert set(fake.workloads[NAMESPACE].values()) == {0}


def test_a_passed_scenario_run_with_no_exit_status_fails(tmp_path: Path) -> None:
    # `helm test` passes when its filter matches no test pod.
    summary = _helm(tmp_path, Fake(exit_code=""))

    assert not summary.passed
    assert _step(summary, "e2e").detail == (
        f"{POD} has no exit status, so its scenarios are not shown to have run")


def test_a_failed_read_of_one_piece_of_evidence_keeps_the_others(tmp_path: Path) -> None:
    summary = _helm(tmp_path, Fake(failing_read="{.resources}"))

    assert summary.evidence["resources"] is None
    assert summary.evidence["other_namespaces"] == {}
    assert summary.evidence["events"]
    assert any("could not read the release's rendered resources" in (step.detail or "")
               for step in summary.steps)


def test_a_scenario_log_that_cannot_be_read_is_warned(tmp_path: Path) -> None:
    summary = _helm(tmp_path, Fake(fail=["scenarios"]))

    assert summary.evidence["scenarios"]["log"] is None
    assert any("the scenario pod's log was not kept" in (step.detail or "")
               for step in summary.steps)


def test_an_evidence_command_that_fails_is_warned_and_not_named(tmp_path: Path) -> None:
    summary = _helm(tmp_path, Fake(fail=["events"]))

    assert summary.passed
    assert summary.evidence["events"] is None
    assert any(step.result == "warning" and "the namespace's events was not kept" in step.detail
               for step in summary.steps)


def test_an_unexpected_evidence_error_still_scales_the_release_down(tmp_path: Path) -> None:
    fake = Fake(broken_read="{.resources}")
    summary = _helm(tmp_path, fake)

    assert any(step.name == "evidence" and "stopped keeping evidence: RuntimeError"
               in (step.detail or "") for step in summary.steps)
    assert set(fake.workloads[NAMESPACE].values()) == {0}
    assert (_attempt(tmp_path) / "summary.json").exists()


def test_memory_is_not_sampled_when_the_release_never_came_up(tmp_path: Path) -> None:
    summary = _helm(tmp_path, Fake(fail=["deploy"]))

    assert not summary.passed and summary.memory == {}


def test_a_passing_run_keeps_the_evidence_and_scales_to_zero(tmp_path: Path) -> None:
    fake = Fake(workloads={"validate-other": {f"deployment/{RELEASE}-registry": 1}},
                memory=("400Mi", "700Mi"))
    summary = _helm(tmp_path, fake)

    logs = _attempt(tmp_path)
    evidence = summary.evidence
    assert summary.passed
    assert evidence["pods"] == str((logs / "pods").relative_to(tmp_path))
    assert (logs / "pods" / f"{POD}.log").exists()
    assert not (logs / "pods" / f"{POD}.previous.log").exists()
    assert evidence["pod_statuses"] == str((logs / "pods.json").relative_to(tmp_path))
    assert evidence["events"] == str((logs / "events.log").relative_to(tmp_path))
    assert evidence["node_events"] == str((logs / "node-events.log").relative_to(tmp_path))
    others = {f"validate-other deployment/{RELEASE}-registry": 1}
    assert evidence["other_namespaces"] == evidence["other_namespaces_at_start"] == others
    assert evidence["resources"]["previous"] is None
    assert (logs / "resources.txt").read_text("utf-8").startswith(
        f"deployment/{RELEASE}-registry app=")
    # Sampled once the release is ready, and after the scenarios; the peak is the larger.
    assert summary.memory == {"samples_bytes": [400 * 2**20, 700 * 2**20],
                              "peak_bytes": 700 * 2**20,
                              "measured_at": "2026-10-22T07:00:00+00:00"}
    assert set(fake.workloads[NAMESPACE].values()) == {0}
    written = json.loads((logs / "summary.json").read_text("utf-8"))
    assert written["namespace"] == NAMESPACE and written["memory"]["peak_bytes"] == 700 * 2**20


def test_the_memory_is_sampled_while_the_scenarios_run(tmp_path: Path) -> None:
    fake = Fake(memory=("400Mi", "900Mi", "900Mi", "500Mi"), samples_during_scenarios=2)
    summary = _helm(tmp_path, fake, sample_interval=0.01)

    assert summary.passed, validator.render(summary)
    samples = summary.memory["samples_bytes"]
    assert len(samples) >= 4 and samples[0] == 400 * 2**20
    assert summary.memory["peak_bytes"] == 900 * 2**20


def test_a_restarted_containers_previous_log_is_kept(tmp_path: Path) -> None:
    fake = Fake(restarts=1)
    _helm(tmp_path, fake)

    assert (f"kubectl logs --namespace {NAMESPACE} {RELEASE}-registry-1 --all-containers "
            "--prefix --previous") in fake.ran()
    assert (_attempt(tmp_path) / "pods" / f"{RELEASE}-registry-1.previous.log").exists()


def _earlier(tmp_path: Path, commit: str, namespace: str, resources: str,
             mtime: float) -> Path:
    attempt = tmp_path / ".snapshot/validation" / commit / "helm/1"
    attempt.mkdir(parents=True)
    (attempt / "summary.json").write_text(json.dumps({"namespace": namespace}), "utf-8")
    (attempt / "resources.txt").write_text(resources, "utf-8")
    os.utime(attempt / "resources.txt", (mtime, mtime))
    return attempt / "resources.txt"


def test_the_rendered_resources_are_kept_beside_the_previous_validations(
        tmp_path: Path) -> None:
    _earlier(tmp_path, "111111111111", NAMESPACE, "deployment/oldest app={}\n", 1_000)
    latest = _earlier(tmp_path, "222222222222", NAMESPACE, "deployment/other app={}\n", 2_000)
    _earlier(tmp_path, "333333333333", "validate-x", "x\n", 3_000)

    summary = _helm(tmp_path, Fake())

    assert summary.evidence["resources"]["previous"] == str(latest.relative_to(tmp_path))
    assert summary.evidence["resources"]["changed"] is True


def test_resources_equal_to_the_previous_validations_are_unchanged(tmp_path: Path) -> None:
    rendered = "".join(f"deployment/{RELEASE}-{name} app={{\"limits\":{{\"memory\":\"1Gi\"}}}}\n"
                       for name in ("registry", "storefront-bob"))
    _earlier(tmp_path, "222222222222", NAMESPACE, rendered, 2_000)

    summary = _helm(tmp_path, Fake())

    assert summary.evidence["resources"]["changed"] is False


def test_a_commit_mid_part_stops_the_evidence_but_still_scales_to_zero(tmp_path: Path) -> None:
    fake = Fake(head_after="resume")
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert "HEAD is now ffffffffffff" in _step(summary, "resume").detail
    assert not any(command[:2] == ["helm", "test"] for command in fake.commands)
    assert "events" not in fake.events and "resources query" not in fake.events
    assert fake.ran()[-1].startswith(f"kubectl scale --namespace {NAMESPACE} --replicas=0")


def test_a_commit_or_branch_switch_mid_build_stops_before_the_namespace(tmp_path: Path) -> None:
    fake = Fake(head_after="build-dev")
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert "HEAD is now ffffffffffff" in _step(summary, "build-dev").detail
    assert "make -C helm test-render CHANGE=pilot" not in fake.ran()
    assert not any(command[0] == "kubectl" for command in fake.commands)


def test_a_skipped_render_check_fails_validation(tmp_path: Path) -> None:
    skip = "skip: STOREFRONT_PYTHON unset; the storefront loader check did not run"
    fake = Fake(output={"test-render": f"ok    a check\n{skip}\n"})
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert fake.ran()[-1] == "make -C helm test-render CHANGE=pilot"
    render = _step(summary, "test-render")
    assert render.result == "failed" and render.tail == [skip]


# --- Helm part: preflights ----------------------------------------------------

def test_helm_refuses_a_kube_context_other_than_the_one_named(tmp_path: Path) -> None:
    fake = Fake(context="production-cluster")
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert fake.commands == []
    assert "production-cluster" in summary.steps[-1].detail


@pytest.mark.parametrize(("missing", "step", "target"), [
    ("domains/vms/storefront", "storefront environment", "make init-storefront"),
    ("domains/bare_metal/storefront", "bare-metal storefront environment",
     "make init-bare-metal-storefront"),
])
def test_helm_without_a_loader_environment_names_how_to_create_it(
        tmp_path: Path, missing: str, step: str, target: str) -> None:
    fake = Fake()
    _storefront_env(tmp_path, skip=missing)
    summary = validator.validate_helm(_validation(tmp_path, fake, "helm"), change=CHANGE,
                                      credentials=lambda: None,
                                      capacity=_capacity(tmp_path))

    assert not summary.passed
    assert fake.commands == []
    assert summary.steps[-1].name == step
    assert f"{missing}/.venv/bin/python is missing" in summary.steps[-1].detail
    assert target in summary.steps[-1].detail


@pytest.mark.parametrize("fault, step", [
    ({"docker_up": False}, "docker"),
    ({"nodes": "docker-desktop=False\n"}, "kube node"),
    ({"nodes": ""}, "kube node"),
    ({"cast": False}, "cast"),
])
def test_an_unready_environment_stops_before_anything_is_built(
    tmp_path: Path, fault: dict[str, object], step: str
) -> None:
    fake = Fake(**fault)
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert _results(summary)[step] == "failed"
    assert fake.commands == []


def test_no_recorded_figure_warns_that_the_capacity_check_was_skipped(tmp_path: Path) -> None:
    fake = Fake()
    summary = _helm(tmp_path, fake)

    assert summary.passed
    capacity = _step(summary, "capacity")
    assert capacity.result == "warning" and "capacity check was skipped" in capacity.detail
    assert "allocatable query" not in fake.events


def test_no_metrics_source_warns_and_records_no_memory(tmp_path: Path) -> None:
    summary = _helm(tmp_path, Fake(metrics=False))

    assert summary.passed
    metrics = _step(summary, "metrics")
    assert metrics.result == "warning" and "no memory figure will be recorded" in metrics.detail
    assert summary.memory == {}


def test_a_release_that_fits_beside_the_running_ones_goes_on(tmp_path: Path) -> None:
    fake = Fake(allocatable="8Gi",
                workloads={"validate-other": {f"deployment/{RELEASE}-registry": 1},
                           "validate-idle": {f"deployment/{RELEASE}-registry": 0},
                           NAMESPACE: {f"deployment/{RELEASE}-registry": 1}})
    summary = _helm(tmp_path, fake, memory=3 * GIB)

    assert summary.passed, validator.render(summary)
    capacity = _step(summary, "capacity")
    assert capacity.result == "passed"
    assert capacity.detail.startswith(f"fits: 2 release(s) at {3 * GIB} bytes each")
    assert "running now: validate-other" in capacity.detail


def test_a_release_that_would_not_fit_fails_as_environmental_before_building(
        tmp_path: Path) -> None:
    fake = Fake(allocatable="8Gi",
                workloads={"validate-other": {f"deployment/{RELEASE}-registry": 1},
                           "validate-third": {f"deployment/{RELEASE}-storefront-bob": 2}})
    summary = _helm(tmp_path, fake, memory=3 * GIB)

    assert not summary.passed
    capacity = _step(summary, "capacity")
    assert capacity.detail.startswith("environmental: deploying would not fit: 3 release(s)")
    assert "validate-other, validate-third" in capacity.detail
    # The remedy scales the validation release alone, StatefulSets included, so an
    # owner's other releases in a namespace stay up.
    assert ("Scale one of them to zero (`kubectl scale --namespace <namespace> "
            "--replicas=0 deployments,statefulsets --selector "
            f"app.kubernetes.io/instance={RELEASE}`)") in capacity.detail
    assert fake.commands == []


def test_only_default_is_checked_for_retained_volumes(tmp_path: Path) -> None:
    changed = Fake(retained=["kept"])
    assert _helm(tmp_path / "change", changed).passed
    assert "retention query" not in changed.events

    default = Fake(retained=[f"{RELEASE}-provisioning-data"])
    summary = _helm(tmp_path / "default", default, change=None)
    assert not summary.passed
    assert f"{RELEASE}-provisioning-data" in _step(summary, "retained volumes").detail
    assert default.commands == []


def test_a_silent_credential_helper_warns_without_failing(tmp_path: Path) -> None:
    summary = _helm(tmp_path, Fake(), credentials=lambda: "helper did not answer")

    assert summary.passed
    assert _results(summary)["credential helper"] == "warning"
    assert "warning credential helper" in validator.render(summary)


def test_a_marker_list_that_is_not_a_plain_disjunction_is_refused(tmp_path: Path) -> None:
    fake = Fake(markers={"E2E_MODULE": "e2e_deal and not slow",
                         "E2E_BARE_METAL_MODULE": BARE_METAL_MARKERS})
    summary = _helm(tmp_path, fake)

    assert not summary.passed
    assert fake.commands == []
    assert "e2e_deal and not slow" in summary.steps[-1].detail


def test_all_scenarios_runs_every_pipeline_scenario(tmp_path: Path) -> None:
    summary = _helm(tmp_path, Fake(), scenarios=None)

    assert summary.not_run == {}
    scenarios = json.loads((_attempt(tmp_path) / "scenarios.json").read_text("utf-8"))
    assert scenarios["e2e-tests"]["scenarios"]["markers"] == (
        "e2e_deal or multi_registry or e2e_listing_shapes or e2e_bare_metal_publication")


# --- the capacity figure and memory quantities ----------------------------------

def test_the_capacity_figure_is_written_and_read_back(tmp_path: Path) -> None:
    path = tmp_path / "validation-capacity.toml"
    figure = validator.CapacityFigure(3 * GIB, "2026-10-21T12:00:00+00:00", "pilot")

    validator.write_capacity(path, figure)

    assert validator.read_capacity(path) == figure
    assert path.read_text("utf-8").startswith(validator.CAPACITY_HEADER)


@pytest.mark.parametrize("memory", [0, -1])
def test_a_figure_that_is_not_positive_is_not_written(tmp_path: Path, memory: int) -> None:
    path = tmp_path / "validation-capacity.toml"

    with pytest.raises(ValueError, match="positive"):
        validator.write_capacity(path, validator.CapacityFigure(memory, "t", "c"))
    assert not path.exists()


def test_the_tracked_capacity_file_starts_with_no_figure() -> None:
    assert validator.read_capacity(REPO_ROOT / validator.CAPACITY_FILE) is None


@pytest.mark.parametrize("body", ["[release]\nmemory_bytes = -1\nmeasured_at = \"t\"\nchange = \"c\"\n",
                                  "[release]\nmemory_bytes = 5\n",
                                  "not toml ["])
def test_a_malformed_capacity_figure_is_refused(tmp_path: Path, body: str) -> None:
    path = tmp_path / "validation-capacity.toml"
    path.write_text(body, "utf-8")

    with pytest.raises(validator.ValidationError):
        validator.read_capacity(path)


# Archive cleanup's figure, from the change's latest validation, over a fake checkout:
# its records and the Helm attempts' summaries they name.
ARCHIVED_REVIEWS = Path("openspec/changes/archive/2026-10-22-pilot/reviews")
OLDER = "fedcba9876543210fedcba9876543210fedcba98"


def _validated(root: Path, number: int, commit: str, *attempts: dict) -> None:
    reviews = root / ARCHIVED_REVIEWS
    reviews.mkdir(parents=True, exist_ok=True)
    (reviews / f"{number:02d}-validation.md").write_text(
        f"# Validation\n\n- **Commit:** {commit} on feat/pilot\n", "utf-8")
    for attempt, memory in enumerate(attempts, 1):
        directory = root / validator.LOG_ROOT / commit[:12] / "helm" / str(attempt)
        directory.mkdir(parents=True)
        (directory / "summary.json").write_text(json.dumps({"memory": memory}), "utf-8")


def _figure_file(root: Path) -> Path:
    path = root / validator.CAPACITY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    validator.write_capacity(path, validator.CapacityFigure(
        GIB, "2026-10-01T00:00:00+00:00", "an-earlier-change"))
    return path


def test_the_figure_is_the_latest_validations_last_helm_attempt_with_its_time_and_change(
        tmp_path: Path) -> None:
    _validated(tmp_path, 3, OLDER, {"peak_bytes": 9 * GIB, "measured_at": "early"})
    _validated(tmp_path, 7, COMMIT, {"peak_bytes": GIB, "measured_at": "first"},
               {"peak_bytes": 2 * GIB, "measured_at": "2026-10-22T06:00:00+00:00"})
    path = _figure_file(tmp_path)

    said = validator.record_capacity(tmp_path, CHANGE)

    assert validator.read_capacity(path) == validator.CapacityFigure(
        2 * GIB, "2026-10-22T06:00:00+00:00", CHANGE)
    assert said.startswith(f"Recorded {2 * GIB} bytes, measured 2026-10-22T06:00:00+00:00")


def test_with_no_measurement_nothing_is_written_and_the_figure_is_left_as_it_was(
        tmp_path: Path) -> None:
    _validated(tmp_path, 7, COMMIT, {})
    path = _figure_file(tmp_path)
    before = path.read_text("utf-8")

    said = validator.record_capacity(tmp_path, CHANGE)

    assert path.read_text("utf-8") == before
    assert said.startswith("No memory figure recorded:") and "no metrics source" in said


def test_with_no_measurement_and_no_figure_the_file_stays_without_one(tmp_path: Path) -> None:
    _validated(tmp_path, 7, COMMIT, {})

    validator.record_capacity(tmp_path, CHANGE)

    assert not (tmp_path / validator.CAPACITY_FILE).exists()


def test_a_validation_with_no_helm_part_records_nothing(tmp_path: Path) -> None:
    _validated(tmp_path, 7, COMMIT)

    assert "ran no Helm part" in validator.record_capacity(tmp_path, CHANGE)


@pytest.mark.parametrize("measured_at", [None, "then", "2026-10-22T06:00:00"])
def test_a_summary_not_saying_when_it_measured_is_dated_by_the_file(
        tmp_path: Path, measured_at: str | None) -> None:
    memory = {"peak_bytes": GIB} | ({"measured_at": measured_at} if measured_at else {})
    _validated(tmp_path, 7, COMMIT, memory)
    summary = tmp_path / validator.LOG_ROOT / COMMIT[:12] / "helm/1/summary.json"
    os.utime(summary, (NOW.timestamp(), NOW.timestamp()))

    figure, _ = validator.capacity_figure(tmp_path, CHANGE)

    assert figure == validator.CapacityFigure(GIB, "2026-10-22T07:00:00+00:00", CHANGE)


@pytest.mark.parametrize("memory", [[1], {"peak_bytes": "1Gi"}, {"peak_bytes": True}])
def test_a_summary_whose_memory_is_not_a_measurement_records_nothing(
        tmp_path: Path, memory: object) -> None:
    _validated(tmp_path, 7, COMMIT, memory)

    assert validator.capacity_figure(tmp_path, CHANGE)[0] is None


def test_a_change_with_no_validation_record_records_nothing_and_says_why(
        tmp_path: Path) -> None:
    (tmp_path / ARCHIVED_REVIEWS).mkdir(parents=True)
    path = _figure_file(tmp_path)
    before = path.read_text("utf-8")

    said = validator.record_capacity(tmp_path, CHANGE)

    assert said == (f"No memory figure recorded: {CHANGE} has no validation record; "
                    f"{validator.CAPACITY_FILE} is unchanged.")
    assert path.read_text("utf-8") == before


def test_the_measurement_time_is_the_last_samples(tmp_path: Path) -> None:
    moments = iter([datetime(2026, 10, 22, 6, minute, tzinfo=timezone.utc)
                    for minute in range(60)])
    fake = Fake(memory=("400Mi", "700Mi"))
    _storefront_env(tmp_path)
    validation = validator.Validation("helm", root=tmp_path, runner=fake.run, read=fake.read,
                                      clock=lambda: 0.0, echo=lambda line: None,
                                      now=lambda: next(moments))

    summary = validator.validate_helm(validation, change=CHANGE, sleep=lambda seconds: None,
                                      credentials=lambda: None, capacity=_capacity(tmp_path))

    assert len(summary.memory["samples_bytes"]) == 2
    assert summary.memory["measured_at"] == "2026-10-22T06:01:00+00:00"


def test_the_command_records_the_figure_for_a_change(
        tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _validated(tmp_path, 7, COMMIT, {"peak_bytes": GIB, "measured_at": "then"})
    (tmp_path / validator.CAPACITY_FILE).parent.mkdir()

    assert validator.main(["capacity", "--change", CHANGE], root=tmp_path) == 0

    assert capsys.readouterr().out.startswith(f"Recorded {GIB} bytes")
    assert validator.read_capacity(tmp_path / validator.CAPACITY_FILE).change == CHANGE
    assert validator.main(["capacity", "--change", "absent"], root=tmp_path) == 1
    assert "no change 'absent'" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        validator.main(["capacity"], root=tmp_path)


@pytest.mark.parametrize("quantity, expected", [
    ("16331392Ki", 16331392 * 1024), ("512Mi", 512 * 2**20), ("2Gi", 2 * GIB),
    ("1000", 1000), ("1.5G", 1_500_000_000), ("128974848", 128974848), ("500m", 0),
])
def test_memory_quantities_are_read_in_bytes(quantity: str, expected: int) -> None:
    assert validator.memory_bytes(quantity) == expected


def test_a_value_that_is_not_a_memory_quantity_is_refused() -> None:
    with pytest.raises(ValueError):
        validator.memory_bytes("lots")


# --- the ci part ------------------------------------------------------------------

CI_RUN, BASELINE_RUN, AFTER_RUN = 500, 80, 41
DEV_COMMIT = "1111111111111111111111111111111111111111"
OWED_JOB = "release · deployment contracts"
VMS_JOB = "py · vms-storefront"
TIMEOUT = "FAILED tests/test_vm.py::test_slow - TimeoutError: timed out"


def _ci_log(*jobs: tuple[str, Sequence[str]]) -> str:
    """A run's whole log, as `gh run view --log` prints it: each failure of a job in
    its short test summary."""
    lines = []
    for job, failures in jobs:
        texts = ["collected 12 items"]
        if failures:
            texts += ["=========================== short test summary info "
                      "============================", *failures, f"{len(failures)} failed"]
        lines += [f"{job}\tRun tests\t2026-10-22T07:00:00.1234567Z {text}" for text in texts]
    return "\n".join(lines) + "\n"


def _ci_jobs(*jobs: tuple[str, Sequence[str]]) -> list[dict]:
    return [{"name": job, "conclusion": "failure" if failures else "success",
             "steps": [{"name": "Run tests", "conclusion": "failure" if failures else "success"}]}
            for job, failures in jobs]


class CIFake:
    """The checkout and GitHub, as the ci part's fetches and reads see them: the
    dispatched run of the commit, and the dev runs listed for a baseline."""

    def __init__(self, *, run: Sequence[tuple[str, Sequence[str]]],
                 baseline: Sequence[tuple[str, Sequence[str]]] = (),
                 conclusion: str = "failure", status: str = "completed",
                 head_sha: str = COMMIT, dev_runs: list[dict] | None = None,
                 fetch_fails: bool = False, fetch_keeps_nothing: bool = False,
                 baseline_fetch_fails: bool = False, unreadable: str | None = None,
                 head_moves_at_baseline: bool = False) -> None:
        self.head = COMMIT
        # A commit or branch switch while the baseline is fetched.
        self.head_moves_at_baseline = head_moves_at_baseline
        self.runs = {str(CI_RUN): (run, head_sha, conclusion, status),
                     str(BASELINE_RUN): (baseline, DEV_COMMIT, "failure", "completed")}
        self.dev_runs = (dev_runs if dev_runs is not None else
                         [{"databaseId": 90, "headSha": "2" * 40, "conclusion": "failure"},
                          {"databaseId": BASELINE_RUN, "headSha": DEV_COMMIT,
                           "conclusion": "failure"}])
        self.fetch_fails = fetch_fails
        # A fetch that exits 0 yet leaves no run's directory.
        self.fetch_keeps_nothing = fetch_keeps_nothing
        self.baseline_fetch_fails = baseline_fetch_fails
        # The run ID whose `gh run view` fails.
        self.unreadable = unreadable
        self.commands: list[list[str]] = []
        self.reads: list[list[str]] = []

    def run(self, command: Sequence[str], log: Path) -> int:
        command = list(command)
        self.commands.append(command)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(f"{log.stem} output\n", "utf-8")
        assert command[:2] == ["python3", "scripts/fetch-e2e-logs.py"], command
        if self.head_moves_at_baseline and "--run-id" in command:
            self.head = "f" * 40
        if self.fetch_fails or (self.baseline_fetch_fails and "--run-id" in command):
            return 1
        if self.fetch_keeps_nothing:
            return 0
        run_id = (str(CI_RUN) if "--after-run" in command
                  else command[command.index("--run-id") + 1])
        directory = Path(command[command.index("--output-dir") + 1]) / run_id
        directory.mkdir(parents=True)
        (directory / "actions.log").write_text(_ci_log(*self.runs[run_id][0]), "utf-8")
        return 0

    def read(self, command: Sequence[str]) -> str:
        command = list(command)
        self.reads.append(command)
        if command == ["git", "rev-parse", "HEAD"]:
            return self.head + "\n"
        if command == ["git", "status", "--porcelain", "--untracked-files=all"]:
            return ""
        if command[:3] == ["gh", "run", "view"]:
            if command[3] == self.unreadable:
                raise validator.ValidationError(f"{' '.join(command)} failed: not found")
            jobs, sha, conclusion, status = self.runs[command[3]]
            return json.dumps({"databaseId": int(command[3]), "headSha": sha,
                               "headBranch": "feat/pilot", "status": status,
                               "conclusion": conclusion, "jobs": _ci_jobs(*jobs)})
        if command[:3] == ["gh", "run", "list"]:
            return json.dumps(self.dev_runs)
        raise AssertionError(f"unexpected read: {command}")


def _ci(tmp_path: Path, fake: CIFake, workflow: str = "tests.yml") -> object:
    return validator.validate_ci(_validation(tmp_path, fake, "ci"), workflow=workflow,
                                 after_run=AFTER_RUN,
                                 contains=lambda ancestor, commit: ancestor == DEV_COMMIT)


def _ci_attempt(tmp_path: Path) -> Path:
    return tmp_path / ".snapshot/validation" / COMMIT[:12] / "ci" / "1"


def test_the_ci_part_keeps_the_run_its_baseline_and_each_jobs_classed_failures(
        tmp_path: Path) -> None:
    jobs = [(OWED_JOB, []), (VMS_JOB, [TIMEOUT])]
    fake = CIFake(run=jobs, baseline=jobs)

    summary = _ci(tmp_path, fake)

    assert summary.passed
    runs = _ci_attempt(tmp_path) / "runs"
    assert fake.commands == [
        ["python3", "scripts/fetch-e2e-logs.py", "--workflow", "tests.yml", "--output-dir",
         str(runs), "--after-run", str(AFTER_RUN), "--event", "workflow_dispatch"],
        ["python3", "scripts/fetch-e2e-logs.py", "--workflow", "tests.yml", "--output-dir",
         str(runs), "--run-id", str(BASELINE_RUN)],
    ]
    assert ["gh", "run", "list", "--workflow", "tests.yml", "--branch", "dev", "--status",
            "completed", "--limit", "100", "--json",
            "databaseId,headSha,conclusion,event"] in fake.reads
    evidence = summary.evidence
    assert evidence["run"] == {
        "id": CI_RUN, "commit": COMMIT, "branch": "feat/pilot", "status": "completed",
        "conclusion": "failure",
        "log": str((runs / str(CI_RUN) / "actions.log").relative_to(tmp_path))}
    assert (evidence["baseline"]["id"], evidence["baseline"]["commit"]) == (BASELINE_RUN,
                                                                            DEV_COMMIT)
    by_name = {job["name"]: job for job in evidence["jobs"]}
    assert by_name[OWED_JOB]["failures"] == []
    assert by_name[VMS_JOB]["failures"] == [{"test": "tests/test_vm.py::test_slow",
                                             "type": "TimeoutError", "outcome": "FAILED",
                                             "class": "inherited"}]
    assert evidence["classes"] == {"inherited": 1, "new": 0, "uncomparable": 0}
    job_log = tmp_path / by_name[VMS_JOB]["log"]
    assert job_log == runs / str(CI_RUN) / "jobs" / "py_vms-storefront.log"
    assert TIMEOUT in job_log.read_text("utf-8")
    assert json.loads((runs / str(CI_RUN) / "run.json").read_text("utf-8"))["headSha"] == COMMIT
    kept = json.loads((_ci_attempt(tmp_path) / "summary.json").read_text("utf-8"))
    assert kept["evidence"]["classes"] == evidence["classes"]
    assert _results(summary) == {"clean before": "passed", "fetch": "passed",
                                 "run": "passed", "baseline fetch": "passed",
                                 "baseline": "passed", "failures": "passed",
                                 "clean after": "passed"}
    rendered = validator.render(summary)
    assert f"baseline tests.yml run {BASELINE_RUN} of {DEV_COMMIT[:12]}" in rendered
    assert "inherited    tests/test_vm.py::test_slow (TimeoutError)" in rendered


def test_a_failure_the_baseline_does_not_show_fails_the_part_naming_it(tmp_path: Path) -> None:
    other = "FAILED tests/test_vm.py::test_other - KeyError: 'listing'"

    summary = _ci(tmp_path, CIFake(run=[(VMS_JOB, [TIMEOUT, other])],
                                   baseline=[(VMS_JOB, [TIMEOUT])]))

    assert not summary.passed
    detail = _step(summary, "failures").detail
    assert detail.startswith("1 inherited, 1 new, 0 uncomparable")
    assert f"{VMS_JOB}: tests/test_vm.py::test_other (KeyError), new" in detail
    assert "test_slow" not in detail


def test_with_no_dev_run_of_the_branchs_code_every_failure_is_uncomparable(
        tmp_path: Path) -> None:
    fake = CIFake(run=[(VMS_JOB, [TIMEOUT])],
                  dev_runs=[{"databaseId": 90, "headSha": "2" * 40, "conclusion": "failure"}])

    summary = _ci(tmp_path, fake)

    assert not summary.passed
    assert _results(summary)["baseline"] == "warning"
    assert summary.evidence["baseline"] is None
    assert summary.evidence["classes"] == {"inherited": 0, "new": 0, "uncomparable": 1}
    assert len(fake.commands) == 1


def test_a_cancelled_run_is_reported_as_producing_no_evidence(tmp_path: Path) -> None:
    fake = CIFake(run=[(VMS_JOB, [])], conclusion="cancelled")

    summary = _ci(tmp_path, fake)

    assert not summary.passed
    assert "cancelled" in summary.evidence["no_evidence"]
    assert _step(summary, "evidence").detail.startswith("the run produced no evidence")
    assert not any(read[:3] == ["gh", "run", "list"] for read in fake.reads)


def test_a_run_never_listed_or_not_fetched_is_reported_as_producing_no_evidence(
        tmp_path: Path) -> None:
    fake = CIFake(run=[], fetch_fails=True)

    summary = _ci(tmp_path, fake)

    assert not summary.passed
    assert f"newer than run {AFTER_RUN} was listed" in summary.evidence["no_evidence"]
    assert not any(read[:2] == ["gh", "run"] for read in fake.reads)


def test_a_run_not_yet_completed_is_reported_as_producing_no_evidence(tmp_path: Path) -> None:
    summary = _ci(tmp_path, CIFake(run=[(VMS_JOB, [])], conclusion="", status="in_progress"))

    assert not summary.passed
    assert "in_progress, not completed" in summary.evidence["no_evidence"]


@pytest.mark.parametrize("jobs", [[], [(OWED_JOB, [])]], ids=["no jobs", "no failed job"])
def test_a_failed_run_with_no_failed_job_is_reported_as_producing_no_evidence(
        tmp_path: Path, jobs: list) -> None:
    fake = CIFake(run=jobs, conclusion="failure")

    summary = _ci(tmp_path, fake)

    assert not summary.passed
    counted = "1 job" if jobs else "0 jobs"
    assert (f"run {CI_RUN} concluded failure but reported no failed job among its "
            f"{counted}") in summary.evidence["no_evidence"]
    assert "failures" not in _results(summary)
    assert not any(read[:3] == ["gh", "run", "list"] for read in fake.reads)


def test_a_fetch_that_keeps_no_run_is_reported_as_producing_no_evidence(
        tmp_path: Path) -> None:
    fake = CIFake(run=[(VMS_JOB, [])], fetch_keeps_nothing=True)

    summary = _ci(tmp_path, fake)

    assert not summary.passed
    assert "the fetch left 0 runs" in summary.evidence["no_evidence"]
    assert not any(read[:2] == ["gh", "run"] for read in fake.reads)


def test_a_fetched_run_that_cannot_be_read_is_reported_as_producing_no_evidence(
        tmp_path: Path) -> None:
    summary = _ci(tmp_path, CIFake(run=[(VMS_JOB, [])], unreadable=str(CI_RUN)))

    assert not summary.passed
    assert "could not be read" in summary.evidence["no_evidence"]
    assert "not found" in _step(summary, "run").detail


def test_a_baseline_that_cannot_be_fetched_leaves_every_failure_uncomparable_saying_so(
        tmp_path: Path) -> None:
    summary = _ci(tmp_path, CIFake(run=[(VMS_JOB, [TIMEOUT])], baseline=[(VMS_JOB, [TIMEOUT])],
                                   baseline_fetch_fails=True))

    assert not summary.passed
    assert _results(summary)["baseline fetch"] == "failed"
    assert summary.evidence["baseline"] is None
    job = summary.evidence["jobs"][0]
    assert job["failures"][0]["class"] == "uncomparable"
    assert job["reason"] == f"the baseline, dev's run {BASELINE_RUN}, could not be fetched"


def test_a_baseline_that_cannot_be_fetched_is_only_a_warning_when_no_job_failed(
        tmp_path: Path) -> None:
    summary = _ci(tmp_path, CIFake(run=[(OWED_JOB, [])], conclusion="success",
                                   baseline_fetch_fails=True))

    assert summary.passed
    assert _results(summary)["baseline fetch"] == "warning"
    assert _step(summary, "failures").detail == "no job failed"


def test_a_commit_while_the_baseline_is_fetched_fails_the_part_and_stops_it(
        tmp_path: Path) -> None:
    summary = _ci(tmp_path, CIFake(run=[(OWED_JOB, [])], conclusion="success",
                                   baseline=[(OWED_JOB, [])], head_moves_at_baseline=True))

    assert not summary.passed
    assert "not the validated commit" in _step(summary, "checkout").detail
    assert summary.evidence["jobs"] == []


def test_a_baseline_fetched_but_unreadable_says_so(tmp_path: Path) -> None:
    summary = _ci(tmp_path, CIFake(run=[(VMS_JOB, [TIMEOUT])], baseline=[(VMS_JOB, [TIMEOUT])],
                                   unreadable=str(BASELINE_RUN)))

    assert not summary.passed
    assert _results(summary)["baseline"] == "failed"
    assert summary.evidence["jobs"][0]["reason"] == (
        f"the baseline, dev's run {BASELINE_RUN}, was fetched but could not be read")


@pytest.mark.parametrize("dev_runs, contains, problem", [
    ({"databaseId": 80}, None, "not a run list"),
    ([{"databaseId": BASELINE_RUN, "headSha": DEV_COMMIT, "conclusion": "failure"}],
     "raise", "merge-base exited 128"),
])
def test_a_baseline_that_cannot_be_chosen_fails_its_step_and_compares_with_none(
        tmp_path: Path, dev_runs: object, contains: str | None, problem: str) -> None:
    def broken(ancestor: str, commit: str) -> bool:
        raise validator.ci_evidence.CIError("git merge-base exited 128: broken")

    fake = CIFake(run=[(VMS_JOB, [TIMEOUT])], dev_runs=dev_runs)
    summary = validator.validate_ci(
        _validation(tmp_path, fake, "ci"), workflow="tests.yml", after_run=AFTER_RUN,
        contains=broken if contains else (lambda ancestor, commit: ancestor == DEV_COMMIT))

    assert not summary.passed
    assert problem in _step(summary, "baseline").detail
    job = summary.evidence["jobs"][0]
    assert job["failures"][0]["class"] == "uncomparable"
    assert "could be chosen" in job["reason"]
    assert len(fake.commands) == 1


def test_a_run_of_another_commit_is_not_read_as_the_commits(tmp_path: Path) -> None:
    summary = _ci(tmp_path, CIFake(run=[(VMS_JOB, [])], head_sha="f" * 40))

    assert not summary.passed
    assert "not the validated commit" in _step(summary, "run commit").detail
    assert summary.evidence["jobs"] == []


def test_a_workflow_validation_may_not_dispatch_is_refused_and_nothing_runs(
        tmp_path: Path) -> None:
    fake = CIFake(run=[])

    summary = _ci(tmp_path, fake, workflow="publish-pypi.yml")

    assert not summary.passed
    assert "it may dispatch: tests.yml" in _step(summary, "workflow").detail
    assert fake.commands == []


def test_the_ci_command_line_needs_the_workflow_and_the_run_before_the_dispatch(
        tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        validator.main(["ci", "--workflow", "tests.yml"], root=tmp_path)
    with pytest.raises(SystemExit):
        validator.main(["ci", "--after-run", "41"], root=tmp_path)


@pytest.mark.parametrize("arguments, command", [
    (["validate-ci", "WORKFLOW=tests.yml", "CI_AFTER_RUN=41"],
     'python3 scripts/validate_slice.py ci --workflow "tests.yml" --after-run "41"'),
    (["run-ci", "WORKFLOW=tests.yml"], 'python3 scripts/ci_evidence.py dispatch "tests.yml"'),
])
def test_the_ci_targets_run_their_scripts(arguments: list[str], command: str) -> None:
    environment = {name: value for name, value in os.environ.items()
                   if name not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "CHANGE")}

    printed = subprocess.run(["make", "-n", "-s", "--no-print-directory", *arguments],
                             cwd=REPO_ROOT, env=environment, capture_output=True, text=True,
                             check=True).stdout

    assert printed.strip().splitlines()[-1] == command


# --- the credential helper, the markers, and the targets ------------------------

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


def test_the_pipeline_marker_variables_exist_and_are_plain_disjunctions() -> None:
    markers = validator.pipeline_markers(validator._read)

    assert "e2e_deal" in markers
    assert "e2e_bare_metal_publication" in markers


def test_every_helm_scenario_is_a_declared_marker() -> None:
    declared = (REPO_ROOT / "e2e-tests" / "pyproject.toml").read_text("utf-8")

    for marker in validator.HELM_SCENARIOS:
        assert f'"{marker}:' in declared


def test_the_scenario_pod_is_the_one_the_e2e_tests_chart_renders() -> None:
    template = (REPO_ROOT / "helm/charts/e2e-tests/templates/tests/e2e-scenarios-test.yaml"
                ).read_text("utf-8")

    assert validator.SCENARIO_POD == "{release}-e2e-tests-e2e-scenarios"
    assert 'name: {{ include "e2e-tests.fullname" . }}-e2e-scenarios' in template


def test_make_targets_delegate_to_the_script() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text("utf-8")

    assert "scripts/validate_slice.py local" in makefile
    assert 'scripts/validate_slice.py helm --context "$(HELM_CONTEXT)"' in makefile
    assert '$(if $(CHANGE),--change "$(CHANGE)")' in makefile
    assert "--all-scenarios" in makefile
    # The instruction travels with the invocation into the validation session.
    assert "/change-validate $(CHANGE)$(if $(filter 1,$(HELM_ALL_SCENARIOS))" in makefile


def test_the_command_line_refuses_a_name_that_is_not_a_change(
        capsys: pytest.CaptureFixture[str]) -> None:
    assert validator.main(["helm", "--change", "Not_A_Change"]) == 1

    assert "not a change name" in capsys.readouterr().err
