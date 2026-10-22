#!/usr/bin/env python3
"""Validate the committed slice at HEAD without changing the checkout.

Validation describes one commit, so it must leave the worktree exactly as it found
it: a step that rewrote a tracked file would validate a tree that is not the
commit. Each part asserts a clean worktree, untracked files included, before it
starts, and after every step checks that `HEAD` is still the commit it recorded and
the worktree is still clean; on any change it stops, because every later step
would describe a different tree. It fails rather than repairs. A step can change
the tree — `make test` and the end-to-end image build both sync project
environments, which may rewrite a lock — and so can something outside it, such as a
commit or a branch switch in the same checkout.

Both parts start with `make dist-clean`. The wheelhouse in `.dist` is shared by
every branch built in the checkout, and environments sync internal packages with an
upgrade, so a higher version another branch left there would be installed in place
of the one this commit builds. Removing it makes every wheel tested come from the
commit; it is untracked, so the checkout is unchanged.

- `local` runs `make check-packaging`, then `make test`.
- `helm` runs in the change's own namespace (`--change`, else `default`), so two
  changes' validations never touch each other's release, volumes, or Secrets. It
  builds the images under the change's own tags, runs the chart render checks
  with the chart-to-loader check able to run against this commit's code, then
  replaces the change's release: its workloads scaled to zero if a crashed run
  left any up, its volumes deleted, the namespace's Secrets created, and the
  release upgraded in place from zero, so every pod starts new on the images just
  built against empty volumes. The pipeline's scenarios run as a pod inside the
  namespace, reaching services by name, so no local port is used. Afterwards it
  always keeps the namespace's evidence and scales its workloads to zero, leaving
  objects and volumes for the next validation to replace.

Validation has full control of the environment it runs in: it scales, deletes,
and replaces whatever its change's namespace holds without asking. What it never
changes is the commit, or another namespace.

Each part stops at its first failure and keeps each attempt's output apart, under
`.snapshot/validation/<short commit>/<part>/<attempt>/`, so a rerun never overwrites
the evidence of the run before it. It prints one line as each step starts and one
as it ends, so a part can be watched while it runs, then a summary, which it also
writes as `summary.json` beside the logs for the validation report. A step's
result is `passed`, `failed`, or `warning`; a warning does not fail the part.

Contract: openspec/specs/change-workflow/spec.md, "Validation observes a committed
slice" and "Each Helm validation is isolated in its change's namespace".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
import tomllib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import change_namespace

ROOT = Path(__file__).resolve().parents[1]
LOG_ROOT = Path(".snapshot/validation")
DEFAULT_HELM_CONTEXT = "docker-desktop"
DEFAULT_NAMESPACE = "default"
STOREFRONT_PROJECT = "domains/vms/storefront"
STOREFRONT_PYTHON = Path(STOREFRONT_PROJECT, ".venv/bin/python")
# The end-to-end pipeline's scenario selections, one per lane; the Helm run reads
# them from e2e-tests/Makefile so the two lists cannot drift apart.
PIPELINE_MARKER_VARIABLES = ("E2E_MODULE", "E2E_BARE_METAL_MODULE")
# The scenarios run against the Helm deployment. The local release enables
# Alkahest and contact exchange for its one storefront, but the charts deploy no
# second storefront and registry, none of the API-credits and bare-metal services,
# and no Mailpit, so a scenario that needs any of those cannot pass there. Every
# other pipeline scenario is reported as not run against Helm, never as passed. A
# scenario joins this list when the Helm deployment serves what it needs, and
# reads nothing from the checkout that the e2e-tests image does not hold, since
# it runs from that image inside the cluster.
HELM_SCENARIOS = ("contracts", "e2e_alkahest_escrow_codecs")
NOT_SERVED = ("the default charts do not serve it: no settlement mechanism, and not "
              "every service the pipeline's compose stacks run")
# The e2e-tests chart's scenario test pod, which runs the selected scenarios.
SCENARIO_POD = "{release}-e2e-tests-e2e-scenarios"
SCENARIO_TIMEOUT = "30m"
READY_TIMEOUT = "600s"
# How often the namespace's memory is sampled while the scenarios run.
SAMPLE_SECONDS = 15.0
# The memory one release needs, as a change's validation last measured it.
CAPACITY_FILE = Path("helm/validation-capacity.toml")
# How long deleted volumes may take to go.
VOLUME_WAIT_SECONDS = 120.0
# How long a read of the checkout or the cluster may take.
READ_TIMEOUT_SECONDS = 120.0
CREDENTIAL_HELPER_TIMEOUT = 5.0
TAIL_LINES = 40
DIST_CLEAN = ("dist-clean", ["make", "dist-clean"])
_SKIP_LINE = re.compile(r"^skip:.*$", re.M)
_MARKER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# What a Helm upgrade the chart refuses, rather than one that failed, prints: a
# change Kubernetes does not apply in place, such as a Deployment's selector.
_UPGRADE_REFUSED = re.compile(r"field is immutable", re.I)
# A Kubernetes memory quantity: a number and an optional binary or decimal suffix.
_QUANTITY = re.compile(r"^([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|Pi|Ei|k|M|G|T|P|E|m)?$")
_QUANTITY_FACTORS = {None: 1, "Ki": 2**10, "Mi": 2**20, "Gi": 2**30, "Ti": 2**40,
                     "Pi": 2**50, "Ei": 2**60, "k": 10**3, "M": 10**6, "G": 10**9,
                     "T": 10**12, "P": 10**15, "E": 10**18, "m": 10**-3}
# Each Deployment's and StatefulSet's namespace, kind/name, and replicas, one per line.
WORKLOAD_COLUMNS = ("jsonpath={range .items[*]}{.metadata.namespace} {.kind}/"
                    "{.metadata.name} {.spec.replicas}{\"\\n\"}{end}")
# Each workload's containers' requests and limits, as rendered.
RESOURCE_COLUMNS = ("jsonpath={range .items[*]}{.kind}/{.metadata.name}"
                    "{range .spec.template.spec.containers[*]} {.name}={.resources}{end}"
                    "{\"\\n\"}{end}")
# A volume's name and its retention annotation, one per line, as name=policy.
RETENTION_COLUMN = ("jsonpath={range .items[*]}{.metadata.name}="
                    "{.metadata.annotations.helm\\.sh/resource-policy}{\"\\n\"}{end}")

# Runs a command from the repository root, writing its combined output to the log
# file, and returns the exit status.
Runner = Callable[[Sequence[str], Path], int]
# Reads a command's standard output; raises ValidationError when the command fails.
Reader = Callable[[Sequence[str]], str]
# Returns a warning when the Docker credential helper does not answer, else None.
CredentialProbe = Callable[[], "str | None"]


class ValidationError(RuntimeError):
    """A part could not start, or a step failed in a way no log describes."""


@dataclass
class Step:
    name: str
    result: str
    seconds: float = 0.0
    log: str | None = None
    tail: list[str] = field(default_factory=list)
    detail: str | None = None


@dataclass
class Summary:
    part: str
    commit: str
    attempt: int = 1
    passed: bool = True
    steps: list[Step] = field(default_factory=list)
    not_run: dict[str, str] = field(default_factory=dict)
    # The Helm part's namespace, and what it kept after the scenarios: the
    # namespace's sampled memory, the scenario pod's log and exit status, and the
    # rendered resources and other namespaces' workloads a memory failure is read
    # against.
    namespace: str | None = None
    memory: dict = field(default_factory=dict)
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class CapacityFigure:
    """The memory one release needs, and when and from which change it was measured."""

    memory_bytes: int
    measured_at: str
    change: str


@dataclass(frozen=True)
class Workload:
    namespace: str
    name: str  # kind/name, as `kubectl scale` takes it
    replicas: int


def _run_logged(command: Sequence[str], log: Path) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        try:
            return subprocess.run(list(command), cwd=ROOT, stdin=subprocess.DEVNULL,
                                  stdout=stream, stderr=subprocess.STDOUT).returncode
        except OSError as exc:
            stream.write(f"could not run {command[0]}: {exc}\n")
            return 127


def _read(command: Sequence[str]) -> str:
    try:
        return subprocess.run(list(command), cwd=ROOT, capture_output=True, text=True,
                              check=True, timeout=READ_TIMEOUT_SECONDS).stdout
    except FileNotFoundError as exc:
        raise ValidationError(f"{command[0]} is required but was not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise ValidationError(f"{' '.join(command)} failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        # A read that hangs would hold the scale-down after the scenarios with it.
        raise ValidationError(f"{' '.join(command)} did not answer within "
                              f"{READ_TIMEOUT_SECONDS:g}s") from exc


def _docker_config() -> Path:
    return Path(os.environ.get("DOCKER_CONFIG") or Path.home() / ".docker") / "config.json"


def _credential_helper_warning(config: Path | None = None,
                               timeout: float = CREDENTIAL_HELPER_TIMEOUT) -> str | None:
    config = config or _docker_config()
    try:
        store = json.loads(config.read_text("utf-8")).get("credsStore")
    except (OSError, ValueError):
        return None
    if not store:
        return None
    helper = f"docker-credential-{store}"
    try:
        status = subprocess.run([helper, "list"], capture_output=True, timeout=timeout).returncode
        problem = None if status == 0 else f"{helper} exited {status}"
    except subprocess.TimeoutExpired:
        problem = f"{helper} did not answer within {timeout:g}s"
    except OSError as exc:
        problem = f"{helper} could not run: {exc}"
    if problem is None:
        return None
    return (f"{problem}; image builds look up registry credentials through it and may fail. "
            f"The credsStore setting in {config} routes even public pulls through it")


def dirty_paths(read: Reader) -> list[str]:
    """Every tracked change and untracked file Git reports; ignored files excluded."""
    status = read(["git", "status", "--porcelain", "--untracked-files=all"])
    return [line for line in status.splitlines() if line.strip()]


def pipeline_markers(read: Reader) -> list[str]:
    """The pipeline's scenario markers, in lane order, from e2e-tests/Makefile."""
    markers: list[str] = []
    for variable in PIPELINE_MARKER_VARIABLES:
        expression = read(["make", "-s", "--no-print-directory", "-C", "e2e-tests",
                           "--eval", "print-%: ; @echo $($*)", f"print-{variable}"])
        names = [name.strip() for name in expression.split(" or ")]
        # Only a flat disjunction can be filtered by name; anything richer would
        # make an exclusion silently change what the expression selects.
        if not expression.strip() or not all(_MARKER.match(name) for name in names):
            raise ValidationError(
                f"{variable} is not a plain 'a or b' marker list: {expression.strip()!r}")
        markers += [name for name in names if name not in markers]
    return markers


def memory_bytes(quantity: str) -> int:
    """A Kubernetes memory quantity, such as `16331392Ki` or `512Mi`, in bytes."""
    match = _QUANTITY.match(quantity.strip())
    if not match:
        raise ValueError(f"{quantity!r} is not a memory quantity")
    return round(float(match[1]) * _QUANTITY_FACTORS[match[2]])


def read_capacity(path: Path) -> CapacityFigure | None:
    """The figure `helm/validation-capacity.toml` records, or None while it records none."""
    try:
        table = tomllib.loads(path.read_text("utf-8")).get("release", {})
    except FileNotFoundError:
        return None
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(f"{path} is not TOML: {exc}") from exc
    if "memory_bytes" not in table:
        return None
    memory, measured_at, change = (table.get(key) for key in
                                   ("memory_bytes", "measured_at", "change"))
    if (not isinstance(memory, int) or isinstance(memory, bool) or memory <= 0
            or not isinstance(measured_at, str) or not isinstance(change, str)):
        raise ValidationError(f"{path}'s [release] needs a positive memory_bytes, and "
                              "measured_at and change as strings")
    return CapacityFigure(memory, measured_at, change)


CAPACITY_HEADER = """\
# The memory one release of the umbrella chart needs, as a change's Helm
# validation last measured it: the largest of its namespace's sampled usage,
# recorded from that validation's summary.json. Validation's capacity preflight
# (scripts/validate_slice.py) compares the namespaces that would then be running,
# times this figure, with the node's allocatable memory; it is an estimate and
# reserves nothing. Where two branches' figures conflict at a merge, keep the one
# whose measured_at is later.
"""


def write_capacity(path: Path, figure: CapacityFigure) -> None:
    """Record `figure` as the memory one release needs, replacing any earlier one."""
    if (not isinstance(figure.memory_bytes, int) or isinstance(figure.memory_bytes, bool)
            or figure.memory_bytes <= 0):
        # read_capacity refuses it, so every later preflight would fail.
        raise ValueError(f"a release's memory must be a positive number of bytes, not "
                         f"{figure.memory_bytes!r}")
    path.write_text(CAPACITY_HEADER + "\n[release]\n"
                    f"memory_bytes = {figure.memory_bytes}\n"
                    f"measured_at = {json.dumps(figure.measured_at)}\n"
                    f"change = {json.dumps(figure.change)}\n", "utf-8")


def _say(line: str) -> None:
    # Flushed at once: a part's output is read while it runs, often through a
    # pipe, where a buffered line would appear only when the part ends.
    print(line, flush=True)


class Validation:
    def __init__(self, part: str, *, root: Path = ROOT, runner: Runner = _run_logged,
                 read: Reader = _read, clock: Callable[[], float] = time.monotonic,
                 echo: Callable[[str], None] = _say) -> None:
        self.root = root
        self.run = runner
        self.read = read
        self.clock = clock
        self.echo = echo
        commit = read(["git", "rev-parse", "HEAD"]).strip()
        part_dir = root / LOG_ROOT / commit[:12] / part
        earlier = [int(entry.name) for entry in part_dir.glob("*")
                   if entry.is_dir() and entry.name.isdigit()]
        attempt = max(earlier, default=0) + 1
        self.summary = Summary(part=part, commit=commit, attempt=attempt)
        self.log_dir = part_dir / str(attempt)

    @property
    def failed(self) -> bool:
        return not self.summary.passed

    def fail(self, name: str, detail: str) -> None:
        self.summary.steps.append(Step(name, "failed", detail=detail))
        self.summary.passed = False

    def note(self, name: str, detail: str) -> None:
        self.summary.steps.append(Step(name, "passed", detail=detail))

    def warn(self, name: str, detail: str) -> None:
        self.summary.steps.append(Step(name, "warning", detail=detail))

    def clean(self, name: str) -> bool:
        try:
            dirty = dirty_paths(self.read)
        except ValidationError as exc:
            self.fail(name, str(exc))
            return False
        if dirty:
            self.fail(name, "the worktree is not clean:\n" + "\n".join(dirty))
            return False
        self.note(name, "the worktree is clean")
        return True

    def step(self, name: str, command: Sequence[str]) -> Step:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log = self.log_dir / f"{name}.log"
        self.echo(f"{name}: running ({' '.join(command)}; log {log.relative_to(self.root)})")
        started = self.clock()
        status = self.run(command, log)
        step = Step(name, "passed" if status == 0 else "failed",
                    seconds=round(self.clock() - started, 1),
                    log=str(log.relative_to(self.root)))
        if status != 0:
            step.detail = f"{' '.join(command)} exited {status}"
            step.tail = _tail(log)
            self.summary.passed = False
        if changed := self.commit_changed():
            # Whatever the command reported, the evidence after it no longer
            # describes the commit; the caller stops at a step that did not pass.
            step.result = "failed"
            step.detail = "\n".join(filter(None, [step.detail, changed]))
            self.summary.passed = False
        self.summary.steps.append(step)
        self.echo(f"{name}: {step.result} in {step.seconds}s")
        return step

    def commit_changed(self) -> str | None:
        """How the checkout no longer is the recorded commit, clean; None while it is."""
        try:
            head = self.read(["git", "rev-parse", "HEAD"]).strip()
            dirty = dirty_paths(self.read)
        except ValidationError as exc:
            return f"could not check the checkout: {exc}"
        if head != self.summary.commit:
            return (f"HEAD is now {head[:12]}, not the validated commit "
                    f"{self.summary.commit[:12]}: a commit or branch switch happened")
        if dirty:
            return "the worktree changed:\n" + "\n".join(dirty)
        return None

    def finish(self) -> Summary:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        (self.log_dir / "summary.json").write_text(
            json.dumps(asdict(self.summary), indent=2) + "\n", "utf-8")
        return self.summary


def _tail(log: Path) -> list[str]:
    if not log.is_file():
        return []
    return log.read_text("utf-8", errors="replace").splitlines()[-TAIL_LINES:]


def validate_local(validation: Validation) -> Summary:
    if not validation.clean("clean before"):
        return validation.finish()
    for name, command in (DIST_CLEAN,
                          ("check-packaging", ["make", "check-packaging"]),
                          ("test", ["make", "test"])):
        if validation.step(name, command).result != "passed":
            break
    validation.clean("clean after")
    return validation.finish()


@dataclass
class HelmRun:
    """What one Helm part works on: its change's namespace, release, and images."""

    change: str | None
    namespace: str
    release: str = ""
    test_volumes: tuple[str, ...] = ()
    metrics: bool = False
    # Whether the release came up, so that its memory is worth sampling.
    ready: bool = False

    @classmethod
    def of(cls, change: str | None) -> HelmRun:
        return cls(change, change_namespace.namespace(change) if change else DEFAULT_NAMESPACE)

    @property
    def image_suffix(self) -> str:
        return change_namespace.image_suffix(self.change) if self.change else ""

    @property
    def selector(self) -> str:
        # The release's own objects: `default` may hold an owner's other releases,
        # such as the bare-metal seller's, which validation never touches.
        return f"app.kubernetes.io/instance={self.release}"

    @property
    def scope(self) -> list[str]:
        # A step's own `make` passes its CHANGE, or a NAMESPACE, down through
        # MAKEFLAGS, so every helm/Makefile call names this run's namespace rather
        # than inherit one: by its change, beside which helm/Makefile refuses an
        # inherited NAMESPACE, or as `default` itself.
        if self.change:
            return [f"CHANGE={self.change}"]
        return ["CHANGE=", f"NAMESPACE={DEFAULT_NAMESPACE}"]

    def make(self, target: str, *arguments: str) -> list[str]:
        return ["make", "-C", "helm", target, *self.scope, *arguments]


def validate_helm(validation: Validation, *, change: str | None = None,
                  context: str = DEFAULT_HELM_CONTEXT,
                  scenarios: Sequence[str] | None = HELM_SCENARIOS,
                  sleep: Callable[[float], None] = time.sleep,
                  volume_wait: float = VOLUME_WAIT_SECONDS,
                  credentials: CredentialProbe = _credential_helper_warning,
                  capacity: Path | None = None,
                  sample_interval: float = SAMPLE_SECONDS) -> Summary:
    run = HelmRun.of(change)
    validation.summary.namespace = run.namespace
    if not validation.clean("clean before") or not _helm_preflight(validation, context,
                                                                   credentials):
        return validation.finish()
    try:
        run.release = _helm_setting(validation, run, "RELEASE")
        run.test_volumes = tuple(_helm_setting(validation, run, "TEST_VOLUMES").split())
    except ValidationError as exc:
        validation.fail("release", str(exc))
        return validation.finish()
    if (not _capacity_preflight(validation, run, capacity or validation.root / CAPACITY_FILE)
            or (run.namespace == DEFAULT_NAMESPACE and not _no_retained_volumes(validation, run))):
        return validation.finish()
    try:
        markers = pipeline_markers(validation.read)
    except ValidationError as exc:
        validation.fail("scenarios", str(exc))
        return validation.finish()
    # `scenarios=None` runs every pipeline scenario, to find which the charts serve.
    selected = list(markers if scenarios is None else scenarios)
    validation.summary.not_run = {marker: NOT_SERVED for marker in markers
                                  if marker not in selected}

    # The loader check runs in the VM storefront's own environment, which holds the
    # internal wheels it last synced. The images are built first, rebuilding the
    # wheelhouse from this commit, and the environment is then reinstalled from it,
    # so the check loads the commit's code rather than another branch's.
    for name, command in (DIST_CLEAN,
                          ("build-dev", ["make", "build-dev",
                                         f"IMAGE_SUFFIX={run.image_suffix}"]),
                          ("storefront environment", ["make", "-C", STOREFRONT_PROJECT,
                                                      "reinit"])):
        if validation.step(name, command).result != "passed":
            return _after_helm(validation)
    render = validation.step("test-render", run.make("test-render"))
    if render.result == "passed" and render.log:
        skipped = _SKIP_LINE.findall((validation.root / render.log).read_text("utf-8"))
        if skipped:
            render.result = "failed"
            render.detail = "a render check reported a skip, so it did not run"
            render.tail = skipped
            validation.summary.passed = False
    if validation.failed:
        return _after_helm(validation)

    overlay = _write_overlay(validation, run, selected)
    try:
        if _replace_release(validation, run, overlay, sleep, volume_wait):
            _sample_memory(validation, run)
            if selected:
                _run_scenarios(validation, run, sample_interval)
            else:
                validation.note("e2e", "no scenario is selected for the Helm run")
    finally:
        _after_scenarios(validation, run)
    return _after_helm(validation)


def _after_helm(validation: Validation) -> Summary:
    validation.clean("clean after")
    return validation.finish()


def _helm_setting(validation: Validation, run: HelmRun, name: str) -> str:
    return validation.read(["make", "-s", "--no-print-directory", "-C", "helm",
                            "--eval", "print-%: ; @echo $($*)", f"print-{name}",
                            *run.scope]).strip()


def _workloads(validation: Validation, *scope: str) -> list[Workload]:
    listed = validation.read(["kubectl", "get", "deployments,statefulsets", *scope,
                              "--output", WORKLOAD_COLUMNS])
    workloads = []
    for line in listed.splitlines():
        parts = line.split()
        if len(parts) == 3:
            namespace, name, replicas = parts
            workloads.append(Workload(namespace, name.lower(), int(replicas or 0)))
    return workloads


def _release_workloads(validation: Validation, run: HelmRun) -> list[Workload]:
    return _workloads(validation, "--namespace", run.namespace, "--selector", run.selector)


def _other_namespaces(validation: Validation, run: HelmRun) -> dict[str, int]:
    """Every other namespace's workloads of the validation release, as
    `<namespace> <kind/name>` to replicas; only these count as releases running."""
    return {f"{w.namespace} {w.name}": w.replicas for w in _workloads(
        validation, "--all-namespaces", "--selector", f"app.kubernetes.io/instance={run.release}")
        if w.namespace != run.namespace}


def _scale_to_zero(validation: Validation, run: HelmRun, name: str,
                   workloads: Sequence[Workload]) -> Step:
    return validation.step(name, ["kubectl", "scale", "--namespace", run.namespace,
                                  "--replicas=0", *(w.name for w in workloads)])


def _helm_preflight(validation: Validation, context: str,
                    credentials: CredentialProbe) -> bool:
    try:
        current = validation.read(["kubectl", "config", "current-context"]).strip()
    except ValidationError as exc:
        validation.fail("kube context", str(exc))
        return False
    if current != context:
        validation.fail("kube context",
                        f"the current kube context is {current!r}, not {context!r}; the Helm "
                        "part deploys unattended, so it runs only against HELM_CONTEXT")
        return False
    validation.note("kube context", current)
    if not os.access(validation.root / STOREFRONT_PYTHON, os.X_OK):
        validation.fail("storefront environment",
                        f"{STOREFRONT_PYTHON} is missing, so the chart-to-loader check cannot "
                        "run; create it with `make init-storefront` and validate again")
        return False
    validation.note("storefront environment", str(STOREFRONT_PYTHON))
    try:
        validation.read(["docker", "info", "--format", "{{.ServerVersion}}"])
    except ValidationError as exc:
        validation.fail("docker", f"the Docker daemon is not reachable: {exc}")
        return False
    validation.note("docker", "the daemon answers")
    try:
        nodes = validation.read(["kubectl", "get", "nodes", "--output",
                                 "jsonpath={range .items[*]}{.metadata.name}="
                                 "{.status.conditions[?(@.type==\"Ready\")].status}"
                                 "{\"\\n\"}{end}"]).split()
    except ValidationError as exc:
        validation.fail("kube node", str(exc))
        return False
    not_ready = [node for node in nodes if not node.endswith("=True")]
    if not nodes or not_ready:
        validation.fail("kube node", "no node is Ready" if not nodes
                        else f"not Ready: {', '.join(not_ready)}")
        return False
    validation.note("kube node", ", ".join(nodes))
    # `make -C helm topology-secrets` derives every development key with Foundry's.
    try:
        validation.read(["cast", "--version"])
    except ValidationError as exc:
        validation.fail("cast", f"{exc}; the namespace's Secrets are derived with Foundry's "
                        "cast, so install Foundry and validate again")
        return False
    validation.note("cast", "Foundry's cast answers")
    warning = credentials()
    if warning:
        validation.warn("credential helper", warning)
    return True


def _capacity_preflight(validation: Validation, run: HelmRun, path: Path) -> bool:
    """Whether one more running release fits the node, by the recorded figure.

    An advisory estimate that reserves nothing: two preflights can pass together,
    so a pod may still fail for memory, which validation then classifies from the
    namespace's evidence. With no recorded figure, or no metrics source, it warns
    and goes on.
    """
    try:
        validation.read(["kubectl", "get", "--raw", "--request-timeout=10s",
                         "/apis/metrics.k8s.io/v1beta1/nodes"])
        run.metrics = True
    except ValidationError:
        validation.warn("metrics", "no metrics source answers (metrics-server is not "
                        "installed), so no memory figure will be recorded for "
                        f"{run.namespace}; the part goes on")
    try:
        figure = read_capacity(path)
    except ValidationError as exc:
        validation.fail("capacity", str(exc))
        return False
    # Kept whatever the figure, so a memory failure is read against what ran
    # beside it from the start as well as at the end.
    others: dict[str, int] | None = None
    problem = ""
    try:
        others = _other_namespaces(validation, run)
    except ValidationError as exc:
        problem = f"could not read the other namespaces' workloads: {exc}"
    validation.summary.evidence["other_namespaces_at_start"] = others
    if figure is None:
        validation.warn("capacity", f"no memory figure is recorded in {CAPACITY_FILE}, so "
                        "the capacity check was skipped; the part goes on"
                        + (f"; and {problem}" if problem else ""))
        return True
    if others is None:
        validation.fail("capacity", problem)
        return False
    running = sorted({key.split()[0] for key, replicas in others.items() if replicas > 0})
    try:
        allocatable = sum(memory_bytes(quantity) for quantity in validation.read(
            ["kubectl", "get", "nodes", "--output",
             "jsonpath={.items[*].status.allocatable.memory}"]).split())
    except (ValidationError, ValueError) as exc:
        validation.fail("capacity", f"could not read the cluster's memory: {exc}")
        return False
    needed = (len(running) + 1) * figure.memory_bytes
    sizes = (f"{len(running) + 1} release(s) at {figure.memory_bytes} bytes each "
             f"(measured {figure.measured_at} from {figure.change}) against the node's "
             f"allocatable {allocatable} bytes")
    if needed > allocatable:
        validation.fail("capacity",
                        f"environmental: deploying would not fit: {sizes}. Running now: "
                        f"{', '.join(running)}. Scale one of them to zero (`kubectl scale "
                        "--namespace <namespace> --replicas=0 deployments,statefulsets "
                        f"--selector {run.selector}`), or rerun once one is down")
        return False
    validation.note("capacity", f"fits: {sizes}" + (f"; running now: {', '.join(running)}"
                                                    if running else ""))
    return True


def _no_retained_volumes(validation: Validation, run: HelmRun) -> bool:
    """Refuse, before anything slow, a volume an owner's own deploy kept.

    Only `default` holds the owner's own deployments; a change's namespace is
    validation's alone, and its volumes are deleted outright.
    """
    try:
        listed = validation.read(_volume_query(run, RETENTION_COLUMN)).split()
    except ValidationError as exc:
        validation.fail("retained volumes", str(exc))
        return False
    retained = [entry.split("=", 1)[0] for entry in listed if entry.endswith("=keep")]
    if retained:
        validation.fail("retained volumes",
                        f"{', '.join(retained)} carry helm.sh/resource-policy: keep, so "
                        f"they hold state an owner's deploy of {run.release} meant to keep; "
                        "they were last applied without the local overlay, and are settled "
                        "with the owner before anything is built")
        return False
    validation.note("retained volumes", f"none for {run.release} in {run.namespace}")
    return True


def _volume_query(run: HelmRun, output: str = "name") -> list[str]:
    return ["kubectl", "get", "pvc", "--namespace", run.namespace, "--selector",
            f"app.kubernetes.io/instance={run.release}", "--output", output]


def _write_overlay(validation: Validation, run: HelmRun, selected: Sequence[str]) -> list[str]:
    """The values files layered over the chart's: the local overlay, the change's
    image tags, and the scenarios the scenario pod runs."""
    validation.log_dir.mkdir(parents=True, exist_ok=True)
    files = ["local-values.yaml"]
    if run.change:
        images = change_namespace.write_image_overlay(run.change,
                                                      validation.log_dir / "images.json")
        files.append(str(images))
    scenario_values = validation.log_dir / "scenarios.json"
    scenario_values.write_text(json.dumps(
        {"e2e-tests": {"scenarios": {"markers": " or ".join(selected)}}}) + "\n", "utf-8")
    files.append(str(scenario_values))
    return files


def _deploy_command(run: HelmRun, overlay: Sequence[str]) -> list[str]:
    return run.make("deploy", "EXTRA_VALUES=" + " ".join(f"--values {path}" for path in overlay))


def _replace_release(validation: Validation, run: HelmRun, overlay: Sequence[str],
                     sleep: Callable[[float], None], volume_wait: float) -> bool:
    """Start the change's release anew: from zero, over no volumes, on the new images."""
    try:
        up = [w for w in _release_workloads(validation, run) if w.replicas > 0]
    except ValidationError as exc:
        validation.fail("workloads", str(exc))
        return False
    if up:
        # A run that ended without scaling down left these up; their pods would
        # hold the volumes about to be deleted.
        step = _scale_to_zero(validation, run, "scale down", up)
        if step.result != "passed":
            return False
        step.detail = "left up by an earlier run: " + ", ".join(w.name for w in up)
    if not _delete_volumes(validation, run, sleep, volume_wait):
        return False
    if validation.step("namespace secrets", run.make("topology-secrets")).result != "passed":
        return False
    deploy = validation.step("deploy", _deploy_command(run, overlay))
    if deploy.result != "passed":
        refusal = _refusal(validation, deploy)
        if refusal is None:
            return False
        # The chart refuses some changes in place; the release is then replaced
        # whole. Its uninstall deletes the volumes it owns; the test volumes no
        # chart owns were just recreated empty by `topology-secrets`, and stay.
        deploy.result = "warning"
        deploy.detail = (f"the upgrade was refused ({refusal}), so the release is "
                         "uninstalled and installed")
        validation.summary.passed = not any(s.result == "failed"
                                            for s in validation.summary.steps)
        if (validation.step("undeploy", run.make("undeploy")).result != "passed"
                or not _wait_for_no_volumes(validation, run, sleep, volume_wait,
                                            test_volumes=False)
                or validation.step("install", _deploy_command(run, overlay)).result != "passed"):
            return False
    # An upgrade over workloads scaled to zero restores the counts the chart
    # renders; resuming them from the release's manifest makes that so whatever
    # the Helm release's merge does with a count scaled outside it. Only this
    # release: `default` may hold an owner's others, left as they are.
    if validation.step("resume", run.make("resume",
                                          f"RESUME_RELEASES={run.release}")).result != "passed":
        return False
    # A rollout's status waits for the scaled generation's pods to be available;
    # a Deployment's Available condition can still be true from before it was
    # scaled up.
    try:
        workloads = _release_workloads(validation, run)
    except ValidationError as exc:
        validation.fail("ready", str(exc))
        return False
    for workload in workloads:
        if validation.step(f"ready {workload.name.split('/', 1)[1]}", [
                "kubectl", "rollout", "status", "--namespace", run.namespace, workload.name,
                f"--timeout={READY_TIMEOUT}"]).result != "passed":
            return False
    run.ready = True
    return True


def _refusal(validation: Validation, deploy: Step) -> str | None:
    """The line saying the chart refused the upgrade, when that is why it failed."""
    if not deploy.log or validation.commit_changed():
        return None
    text = (validation.root / deploy.log).read_text("utf-8", errors="replace")
    for line in text.splitlines():
        if _UPGRADE_REFUSED.search(line):
            return line.strip()
    return None


def _delete_volumes(validation: Validation, run: HelmRun, sleep: Callable[[float], None],
                    wait: float) -> bool:
    # A claim is deleted only once no pod uses it, and the release's test pods —
    # the scenario and deal tests, which mount the buyer-profile volume — outlive
    # their runs; with its workloads at zero, every pod of the release can go.
    if validation.step("delete pods", [
            "kubectl", "delete", "pods", "--namespace", run.namespace, "--selector",
            f"app.kubernetes.io/instance={run.release}", "--ignore-not-found",
            "--wait=false"]).result != "passed":
        return False
    if validation.step("delete volumes", [
            "kubectl", "delete", "pvc", "--namespace", run.namespace, "--selector",
            f"app.kubernetes.io/instance={run.release}", "--ignore-not-found",
            "--wait=false"]).result != "passed":
        return False
    # The deal test's buyer-profile volume carries no release label, since no
    # chart creates it.
    if run.test_volumes and validation.step("delete test volumes", [
            "kubectl", "delete", "pvc", "--namespace", run.namespace, *run.test_volumes,
            "--ignore-not-found", "--wait=false"]).result != "passed":
        return False
    return _wait_for_no_volumes(validation, run, sleep, wait)


def _wait_for_no_volumes(validation: Validation, run: HelmRun,
                         sleep: Callable[[float], None], wait: float, *,
                         test_volumes: bool = True) -> bool:
    # A volume that outlives its deletion would hand the new release state
    # another commit wrote.
    named = (["kubectl", "get", "pvc", "--namespace", run.namespace, *run.test_volumes,
              "--ignore-not-found", "--output", "name"]
             if test_volumes and run.test_volumes else None)
    deadline = validation.clock() + wait
    while True:
        try:
            remaining = validation.read(_volume_query(run)).split()
            if named:
                remaining += validation.read(named).split()
        except ValidationError as exc:
            validation.fail("volumes gone", str(exc))
            return False
        if not remaining:
            validation.note("volumes gone", f"none remain for {run.release} in {run.namespace}")
            return True
        if validation.clock() >= deadline:
            validation.fail("volumes gone",
                            f"{', '.join(remaining)} still exist {wait:g}s after their deletion; "
                            "deploying now would hand them to the new release")
            return False
        sleep(2.0)


class _Sampler:
    """Samples the namespace's memory every `interval` seconds while a step runs,
    so the peak includes the scenarios' load, not only the release at rest."""

    def __init__(self, validation: Validation, run: HelmRun, interval: float) -> None:
        self.validation, self.run, self.interval = validation, run, interval
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def __enter__(self) -> _Sampler:
        if self.run.metrics and self.interval > 0:
            self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop.set()
        if self.thread.is_alive():
            self.thread.join()

    def _loop(self) -> None:
        while not self.stop.wait(self.interval):
            # A failed sample is skipped here; the samples around the step warn.
            _sample_memory(self.validation, self.run, warn=False)


def _run_scenarios(validation: Validation, run: HelmRun, sample_interval: float) -> None:
    pod = SCENARIO_POD.format(release=run.release)
    with _Sampler(validation, run, sample_interval):
        step = validation.step("e2e", ["helm", "test", run.release, "--namespace",
                                       run.namespace, "--filter", f"name={pod}",
                                       "--timeout", SCENARIO_TIMEOUT])
    record: dict = {"pod": pod, "log": None, "exit_code": None}
    validation.summary.evidence["scenarios"] = record
    if validation.commit_changed():
        # No evidence describes the commit now, but validation stops what it started.
        _stop_scenario_pod(validation, run, pod)
        return
    record["log"] = _kept(validation, "the scenario pod's log", [
        "kubectl", "logs", "--namespace", run.namespace, pod],
        validation.log_dir / "scenarios.log")
    try:
        code = validation.read(["kubectl", "get", "pod", pod, "--namespace", run.namespace,
                                "--output", "jsonpath={.status.containerStatuses[0]"
                                ".state.terminated.exitCode}"]).strip()
        record["exit_code"] = int(code) if code else None
    except (ValidationError, ValueError) as exc:
        validation.warn("scenario pod", f"could not read {pod}'s exit status: {exc}")
    (validation.log_dir / "scenarios.exit").write_text(f"{record['exit_code']}\n", "utf-8")
    if step.result == "passed" and record["exit_code"] != 0:
        # `helm test` passes when its filter matches no test, so a passed run is
        # evidence only with the pod's own exit status of 0.
        step.result = "failed"
        step.detail = (f"{pod} exited {record['exit_code']}" if record["exit_code"] is not None
                       else f"{pod} has no exit status, so its scenarios are not shown to "
                       "have run")
        validation.summary.passed = False
    if record["exit_code"] is None:
        _stop_scenario_pod(validation, run, pod)


def _stop_scenario_pod(validation: Validation, run: HelmRun, pod: str) -> None:
    # A pod with no exit status may still be running, as after `helm test` timed
    # out: scaling the workloads down would not stop it.
    validation.step("stop scenario pod", ["kubectl", "delete", "pod", pod, "--namespace",
                                          run.namespace, "--ignore-not-found", "--wait=false"])


def _sample_memory(validation: Validation, run: HelmRun, *, warn: bool = True) -> None:
    """Add the release's current memory use to its samples, when it can be measured."""
    if not run.metrics:
        return
    selector = run.selector.replace("/", "%2F").replace("=", "%3D")
    try:
        listed = json.loads(validation.read([
            "kubectl", "get", "--raw", "--request-timeout=10s",
            f"/apis/metrics.k8s.io/v1beta1/namespaces/{run.namespace}/pods"
            f"?labelSelector={selector}"]))
        used = sum(memory_bytes(container["usage"]["memory"])
                   for pod in listed.get("items", []) for container in pod.get("containers", []))
    except (ValidationError, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        if warn:
            validation.warn("memory", f"could not sample {run.namespace}'s memory: {exc}")
        return
    memory = validation.summary.memory
    memory.setdefault("samples_bytes", []).append(used)
    memory["peak_bytes"] = max(memory["samples_bytes"])


def _after_scenarios(validation: Validation, run: HelmRun) -> None:
    """Keep the namespace's evidence, then scale the release to zero, whatever happened.

    Evidence is collected only while the checkout is still the commit, and memory
    only once the release came up; the release is scaled down even then, since
    validation stops what it started.
    """
    if not validation.commit_changed():
        try:
            if run.ready:
                _sample_memory(validation, run)
            _keep_evidence(validation, run)
        except Exception as exc:  # noqa: BLE001 - the scale-down below must still run
            validation.warn("evidence", f"stopped keeping evidence: {type(exc).__name__}: {exc}")
    try:
        up = [w for w in _release_workloads(validation, run) if w.replicas > 0]
    except ValidationError as exc:
        validation.fail("scale to zero", str(exc))
        return
    if up:
        _scale_to_zero(validation, run, "scale to zero", up)
    else:
        validation.note("scale to zero", f"nothing of {run.release} is up in {run.namespace}")


def _kept(validation: Validation, name: str, command: Sequence[str], path: Path) -> str | None:
    """Run an evidence command into `path`; its path, or None, warned, when it failed."""
    if validation.run(command, path) == 0:
        return str(path.relative_to(validation.root))
    validation.warn("evidence", f"{' '.join(command)} failed, so {name} was not kept; "
                    f"its output is {path.relative_to(validation.root)}")
    return None


def _keep_evidence(validation: Validation, run: HelmRun) -> None:
    """Every pod's log and status, the namespace's and the nodes' events, and what a
    memory failure is read against: the other namespaces' workloads, and the
    rendered requests and limits beside the previous validation's.

    A container killed at its own limit shows in its status (`OOMKilled`) and its
    previous log; an eviction or a pod that could not be scheduled, in the events.
    """
    evidence = validation.summary.evidence
    pods_dir = validation.log_dir / "pods"
    scope = ["--namespace", run.namespace, "--selector", run.selector]
    try:
        # Each pod's name, then each container's restart count.
        listed = validation.read(["kubectl", "get", "pods", *scope,
                                  "--output", "jsonpath={range .items[*]}{.metadata.name}"
                                  "{range .status.containerStatuses[*]} {.restartCount}{end}"
                                  "{\"\\n\"}{end}"])
    except ValidationError as exc:
        validation.warn("evidence", f"could not list {run.namespace}'s pods: {exc}")
        listed = ""
    pods = [line.split() for line in listed.splitlines() if line.strip()]
    logs = []
    for pod, *restarts in pods:
        logs.append(_kept(validation, f"{pod}'s log", [
            "kubectl", "logs", "--namespace", run.namespace, pod, "--all-containers",
            "--prefix"], pods_dir / f"{pod}.log"))
        if any(count.isdigit() and int(count) > 0 for count in restarts):
            _kept(validation, f"{pod}'s previous log", [
                "kubectl", "logs", "--namespace", run.namespace, pod, "--all-containers",
                "--prefix", "--previous"], pods_dir / f"{pod}.previous.log")
    evidence["pods"] = str(pods_dir.relative_to(validation.root)) if any(logs) else None
    evidence["pod_statuses"] = _kept(validation, "the pods' statuses", [
        "kubectl", "get", "pods", *scope, "--output", "json"],
        validation.log_dir / "pods.json")
    evidence["events"] = _kept(validation, "the namespace's events", [
        "kubectl", "get", "events", "--namespace", run.namespace,
        "--sort-by=.lastTimestamp"], validation.log_dir / "events.log")
    # A node out of memory is recorded against the node, outside the namespace.
    evidence["node_events"] = _kept(validation, "the nodes' events", [
        "kubectl", "get", "events", "--all-namespaces", "--field-selector",
        "involvedObject.kind=Node", "--sort-by=.lastTimestamp"],
        validation.log_dir / "node-events.log")
    evidence["other_namespaces"] = evidence["resources"] = None
    try:
        evidence["other_namespaces"] = _other_namespaces(validation, run)
    except ValidationError as exc:
        validation.warn("evidence", f"could not read the other namespaces' workloads: {exc}")
    try:
        rendered = validation.read(["kubectl", "get", "deployments,statefulsets", *scope,
                                    "--output", RESOURCE_COLUMNS])
    except ValidationError as exc:
        validation.warn("evidence", f"could not read the release's rendered resources: {exc}")
        return
    resources = validation.log_dir / "resources.txt"
    resources.write_text("\n".join(sorted(rendered.splitlines())) + "\n", "utf-8")
    previous = _previous_resources(validation, run)
    evidence["resources"] = {
        "file": str(resources.relative_to(validation.root)),
        "previous": str(previous.relative_to(validation.root)) if previous else None,
        "changed": None if previous is None
        else previous.read_text("utf-8") != resources.read_text("utf-8"),
    }
    validation.note("evidence", f"pod logs, events, workloads, and resources kept in "
                    f"{validation.log_dir.relative_to(validation.root)}")


def _previous_resources(validation: Validation, run: HelmRun) -> Path | None:
    """The rendered resources the latest earlier validation in this namespace kept."""
    candidates = []
    for summary in (validation.root / LOG_ROOT).glob("*/helm/*/summary.json"):
        if summary.parent == validation.log_dir:
            continue
        try:
            recorded = json.loads(summary.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        resources = summary.parent / "resources.txt"
        if recorded.get("namespace") == run.namespace and resources.is_file():
            candidates.append(resources)
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def render(summary: Summary) -> str:
    lines = [f"{summary.part} validation of {summary.commit[:12]}, attempt "
             f"{summary.attempt}: {'PASSED' if summary.passed else 'FAILED'}"]
    if summary.namespace:
        lines.append(f"  namespace {summary.namespace}")
    for step in summary.steps:
        timing = f" ({step.seconds:g}s)" if step.log else ""
        lines.append(f"  {step.result:<7} {step.name}{timing}")
        if step.detail:
            lines += [f"          {line}" for line in step.detail.splitlines()]
        if step.result == "failed" and step.log:
            lines.append(f"          log: {step.log}")
            lines += [f"          | {line}" for line in step.tail]
    for marker, reason in summary.not_run.items():
        lines.append(f"  not run {marker}: {reason}")
    if "peak_bytes" in summary.memory:
        lines.append(f"  memory  peak {summary.memory['peak_bytes']} bytes over "
                     f"{len(summary.memory['samples_bytes'])} sample(s)")
    scenarios = summary.evidence.get("scenarios")
    if scenarios:
        lines.append(f"  scenarios pod {scenarios['pod']}: exit {scenarios['exit_code']}, "
                     f"log {scenarios['log']}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("part", choices=("local", "helm"))
    parser.add_argument("--context", default=DEFAULT_HELM_CONTEXT,
                        help="the only kube context the Helm part may deploy to")
    parser.add_argument("--change",
                        help="the change whose namespace and image tags the Helm part uses; "
                             "without it, `default` and the bare tags")
    parser.add_argument("--all-scenarios", action="store_true",
                        help="run every pipeline scenario on Helm rather than the ones the "
                             "default charts serve; for establishing which those are")
    args = parser.parse_args(argv)
    try:
        if args.change:
            change_namespace.namespace(args.change)
        validation = Validation(args.part)
        if args.part == "local":
            summary = validate_local(validation)
        else:
            summary = validate_helm(validation, change=args.change,
                                    context=args.context or DEFAULT_HELM_CONTEXT,
                                    scenarios=None if args.all_scenarios else HELM_SCENARIOS)
    except (ValidationError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(render(summary))
    print(f"Attempt {summary.attempt} logs and summary.json: "
          f"{validation.log_dir.relative_to(ROOT)}")
    return 0 if summary.passed else 1


if __name__ == "__main__":
    sys.exit(main())
