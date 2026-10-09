#!/usr/bin/env python3
"""Validate the committed slice at HEAD without changing the checkout.

Validation describes one commit, so it must leave the worktree exactly as it found
it: a step that rewrote a tracked file would validate a tree that is not the
commit. Each part asserts a clean worktree, untracked files included, before it
starts and after it finishes, and fails rather than repairs. The check afterwards
is not redundant: `make test` and the end-to-end image build both sync project
environments, which may rewrite a lock.

Both parts start with `make dist-clean`. The wheelhouse in `.dist` is shared by
every branch built in the checkout, and environments sync internal packages with an
upgrade, so a higher version another branch left there would be installed in place
of the one this commit builds. Removing it makes every wheel tested come from the
commit; it is untracked, so the checkout is unchanged.

- `local` runs `make check-packaging`, then `make test`.
- `helm` builds the images, runs the chart render checks with the chart-to-loader
  check able to run against this commit's code, replaces any installed release
  with a local deployment that starts from no persistent state, forwards it, runs
  the end-to-end pipeline's scenarios against the forwarded services, and always
  unforwards.

Validation has full control of the environment it runs in: it stops port-forwards
and uninstalls the release it finds without asking. What it never changes is the
commit.

Each part stops at its first failure and keeps each attempt's output apart, under
`.snapshot/validation/<short commit>/<part>/<attempt>/`, so a rerun never overwrites
the evidence of the run before it. It prints a summary and writes it as
`summary.json` beside the logs for the validation report. A step's result is
`passed`, `failed`, or `warning`; a warning does not fail the part.

Contract: openspec/specs/change-workflow/spec.md, "Validation observes a committed
slice".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
LOG_ROOT = Path(".snapshot/validation")
DEFAULT_HELM_CONTEXT = "docker-desktop"
STOREFRONT_PROJECT = "domains/vms/storefront"
STOREFRONT_PYTHON = Path(STOREFRONT_PROJECT, ".venv/bin/python")
# The end-to-end pipeline's scenario selections, one per lane; the Helm run reads
# them from e2e-tests/Makefile so the two lists cannot drift apart.
PIPELINE_MARKER_VARIABLES = ("E2E_MODULE", "E2E_BARE_METAL_MODULE")
# The scenarios the default charts can serve, run against the Helm deployment. The
# charts configure no settlement mechanism, so no scenario that creates a listing
# can pass there; nor do they deploy a second storefront and registry, the
# API-credits and bare-metal services, or forward Mailpit. Every other pipeline
# scenario is reported as not run against Helm, never as passed. A scenario joins
# this list when the charts serve what the pipeline's compose stacks do.
HELM_SCENARIOS = ("contracts", "e2e_alkahest_escrow_codecs")
NOT_SERVED = ("the default charts do not serve it: no settlement mechanism, and not "
              "every service the pipeline's compose stacks run")
# The local ports `make -C helm forward` binds. Port-forwards start in the
# background, so the scenarios wait for every port to accept a connection.
FORWARDED_PORTS = (8545, 8080, 8001, 8081)
FORWARD_WAIT_SECONDS = 60.0
# How long an uninstalled release's volumes may take to be deleted.
VOLUME_WAIT_SECONDS = 120.0
CREDENTIAL_HELPER_TIMEOUT = 5.0
# How long stopped port-forwards may take to release their ports.
PORT_RELEASE_SECONDS = 10.0
TAIL_LINES = 40
DIST_CLEAN = ("dist-clean", ["make", "dist-clean"])
_SKIP_LINE = re.compile(r"^skip:.*$", re.M)
_MARKER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Runs a command from the repository root, writing its combined output to the log
# file, and returns the exit status.
Runner = Callable[[Sequence[str], Path], int]
# Reads a command's standard output; raises ValidationError when the command fails.
Reader = Callable[[Sequence[str]], str]
PortProbe = Callable[[int], bool]
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


def _run_logged(command: Sequence[str], log: Path) -> int:
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
                              check=True).stdout
    except FileNotFoundError as exc:
        raise ValidationError(f"{command[0]} is required but was not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise ValidationError(f"{' '.join(command)} failed: {detail}") from exc


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


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


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


class Validation:
    def __init__(self, part: str, *, root: Path = ROOT, runner: Runner = _run_logged,
                 read: Reader = _read, clock: Callable[[], float] = time.monotonic) -> None:
        self.root = root
        self.run = runner
        self.read = read
        self.clock = clock
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
        started = self.clock()
        status = self.run(command, log)
        step = Step(name, "passed" if status == 0 else "failed",
                    seconds=round(self.clock() - started, 1),
                    log=str(log.relative_to(self.root)))
        if status != 0:
            step.detail = f"{' '.join(command)} exited {status}"
            step.tail = _tail(log)
            self.summary.passed = False
        self.summary.steps.append(step)
        return step

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


def validate_helm(validation: Validation, *, context: str = DEFAULT_HELM_CONTEXT,
                  scenarios: Sequence[str] | None = HELM_SCENARIOS,
                  probe: PortProbe = _port_open, sleep: Callable[[float], None] = time.sleep,
                  forward_wait: float = FORWARD_WAIT_SECONDS,
                  volume_wait: float = VOLUME_WAIT_SECONDS,
                  credentials: CredentialProbe = _credential_helper_warning) -> Summary:
    if (not validation.clean("clean before")
            or not _helm_preflight(validation, context, credentials)
            or not _free_ports_and_volumes(validation, probe, sleep)):
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
                          ("build-dev", ["make", "build-dev"]),
                          ("storefront environment", ["make", "-C", STOREFRONT_PROJECT,
                                                      "reinit"])):
        if validation.step(name, command).result != "passed":
            return _after_helm(validation)
    render = validation.step("test-render", ["make", "-C", "helm", "test-render"])
    if render.result == "passed" and render.log:
        skipped = _SKIP_LINE.findall((validation.root / render.log).read_text("utf-8"))
        if skipped:
            render.result = "failed"
            render.detail = "a render check reported a skip, so it did not run"
            render.tail = skipped
            validation.summary.passed = False
    if validation.failed:
        return _after_helm(validation)

    if not _replace_release(validation, sleep, volume_wait):
        return _after_helm(validation)
    try:
        if (validation.step("forward", ["make", "-C", "helm", "forward"]).result == "passed"
                and _wait_for_ports(validation, probe, sleep, forward_wait)):
            if selected:
                validation.step("e2e", ["make", "-C", "e2e-tests", "test-module",
                                        f"MODULE={' or '.join(selected)}"])
            else:
                validation.note("e2e", "no scenario is selected for the Helm run")
    finally:
        validation.step("unforward", ["make", "-C", "helm", "unforward"])
    return _after_helm(validation)


def _after_helm(validation: Validation) -> Summary:
    validation.clean("clean after")
    return validation.finish()


def _free_ports_and_volumes(validation: Validation, probe: PortProbe,
                            sleep: Callable[[float], None]) -> bool:
    """Before anything slow: stop the forwards, and refuse a volume no uninstall removes."""
    if validation.step("stop forwards", ["make", "-C", "helm", "unforward"]).result != "passed":
        return False
    # `unforward` signals the port-forwards and returns; they release their ports
    # as they exit.
    deadline = validation.clock() + PORT_RELEASE_SECONDS
    while held := [port for port in FORWARDED_PORTS if probe(port)]:
        if validation.clock() >= deadline:
            validation.fail("ports free",
                            f"ports {', '.join(map(str, held))} are bound by something other "
                            "than this release's port-forwards; `ss -ltnp` names the process")
            return False
        sleep(0.5)
    validation.note("ports free", ", ".join(map(str, FORWARDED_PORTS)))
    try:
        release, namespace = _release(validation)
        listed = validation.read(_volume_query(release, namespace, RETENTION_COLUMN)).split()
    except ValidationError as exc:
        validation.fail("retained volumes", str(exc))
        return False
    retained = [entry.split("=", 1)[0] for entry in listed if entry.endswith("=keep")]
    if retained:
        validation.fail("retained volumes",
                        f"{', '.join(retained)} carry helm.sh/resource-policy: keep, so "
                        f"uninstalling {release} would leave their state for the next deploy; "
                        "they were last applied without the local overlay, and are settled "
                        "with the owner before anything is built")
        return False
    validation.note("retained volumes", f"none for {release} in {namespace}")
    return True


# A volume's name and its retention annotation, one per line, as name=policy.
RETENTION_COLUMN = ("jsonpath={range .items[*]}{.metadata.name}="
                    "{.metadata.annotations.helm\\.sh/resource-policy}{\"\\n\"}{end}")


def _volume_query(release: str, namespace: str, output: str = "name") -> list[str]:
    return ["kubectl", "get", "pvc", "--namespace", namespace, "--selector",
            f"app.kubernetes.io/instance={release}", "--output", output]


def _release(validation: Validation) -> tuple[str, str]:
    return _helm_setting(validation, "RELEASE"), _helm_setting(validation, "NAMESPACE")


def _replace_release(validation: Validation, sleep: Callable[[float], None],
                     volume_wait: float) -> bool:
    """Uninstall the release, wait for its volumes to go, and deploy it afresh."""
    if validation.step("undeploy", ["make", "-C", "helm", "undeploy"]).result != "passed":
        return False
    if not _wait_for_no_volumes(validation, sleep, volume_wait):
        return False
    return validation.step("deploy-local", ["make", "-C", "helm", "deploy-local"]).result == "passed"


def _helm_setting(validation: Validation, name: str) -> str:
    return validation.read(["make", "-s", "--no-print-directory", "-C", "helm",
                            "--eval", "print-%: ; @echo $($*)", f"print-{name}"]).strip()


def _wait_for_no_volumes(validation: Validation, sleep: Callable[[float], None],
                         wait: float) -> bool:
    # A volume that outlives the uninstall would hand the next deploy state another
    # commit wrote. Retained volumes were refused before the build, so what remains
    # here is deletion still in progress.
    try:
        release, namespace = _release(validation)
    except ValidationError as exc:
        validation.fail("release volumes", str(exc))
        return False
    command = _volume_query(release, namespace)
    deadline = validation.clock() + wait
    while True:
        try:
            remaining = validation.read(command).split()
        except ValidationError as exc:
            validation.fail("release volumes", str(exc))
            return False
        if not remaining:
            validation.note("release volumes", f"none remain for {release} in {namespace}")
            return True
        if validation.clock() >= deadline:
            validation.fail("release volumes",
                            f"{', '.join(remaining)} still exist {wait:g}s after uninstalling "
                            f"{release}; deploying now would hand them to the new release")
            return False
        sleep(2.0)


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
    if validation.step("local secrets",
                       ["make", "-C", "helm", "check-local-secrets"]).result != "passed":
        return False
    warning = credentials()
    if warning:
        validation.warn("credential helper", warning)
    return True


def _wait_for_ports(validation: Validation, probe: PortProbe,
                    sleep: Callable[[float], None], wait: float) -> bool:
    deadline = validation.clock() + wait
    while True:
        closed = [port for port in FORWARDED_PORTS if not probe(port)]
        if not closed:
            validation.note("forwarded ports", ", ".join(map(str, FORWARDED_PORTS)))
            return True
        if validation.clock() >= deadline:
            validation.fail("forwarded ports",
                            f"ports {', '.join(map(str, closed))} did not open within {wait:g}s")
            return False
        sleep(1.0)


def render(summary: Summary) -> str:
    lines = [f"{summary.part} validation of {summary.commit[:12]}, attempt "
             f"{summary.attempt}: {'PASSED' if summary.passed else 'FAILED'}"]
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
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("part", choices=("local", "helm"))
    parser.add_argument("--context", default=DEFAULT_HELM_CONTEXT,
                        help="the only kube context the Helm part may deploy to")
    parser.add_argument("--all-scenarios", action="store_true",
                        help="run every pipeline scenario on Helm rather than the ones the "
                             "default charts serve; for establishing which those are")
    args = parser.parse_args(argv)
    try:
        validation = Validation(args.part)
        if args.part == "local":
            summary = validate_local(validation)
        else:
            summary = validate_helm(validation, context=args.context or DEFAULT_HELM_CONTEXT,
                                    scenarios=None if args.all_scenarios else HELM_SCENARIOS)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(render(summary))
    print(f"Attempt {summary.attempt} logs and summary.json: "
          f"{validation.log_dir.relative_to(ROOT)}")
    return 0 if summary.passed else 1


if __name__ == "__main__":
    sys.exit(main())
