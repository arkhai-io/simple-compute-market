"""Tests for the observational validation of the commit at HEAD."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
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
                                clock=lambda: next(clock), echo=echo)


def _storefront_env(tmp_path: Path) -> None:
    python = tmp_path / validator.STOREFRONT_PYTHON
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
    if not (tmp_path / validator.STOREFRONT_PYTHON).exists():
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
                              "peak_bytes": 700 * 2**20}
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


def test_helm_without_the_storefront_environment_names_how_to_create_it(
        tmp_path: Path) -> None:
    fake = Fake()
    summary = validator.validate_helm(_validation(tmp_path, fake, "helm"), change=CHANGE,
                                      credentials=lambda: None,
                                      capacity=_capacity(tmp_path))

    assert not summary.passed
    assert fake.commands == []
    assert "make init-storefront" in summary.steps[-1].detail


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
    assert "Scale one of them to zero" in capacity.detail
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


@pytest.mark.parametrize("quantity, expected", [
    ("16331392Ki", 16331392 * 1024), ("512Mi", 512 * 2**20), ("2Gi", 2 * GIB),
    ("1000", 1000), ("1.5G", 1_500_000_000), ("128974848", 128974848), ("500m", 0),
])
def test_memory_quantities_are_read_in_bytes(quantity: str, expected: int) -> None:
    assert validator.memory_bytes(quantity) == expected


def test_a_value_that_is_not_a_memory_quantity_is_refused() -> None:
    with pytest.raises(ValueError):
        validator.memory_bytes("lots")


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
