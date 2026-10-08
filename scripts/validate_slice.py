#!/usr/bin/env python3
"""Validate the committed slice at HEAD without changing the checkout.

Validation describes one commit, so it must leave the worktree exactly as it found
it: a step that rewrote a tracked file would validate a tree that is not the
commit. Each part asserts a clean worktree, untracked files included, before it
starts and after it finishes, and fails rather than repairs. The check afterwards
is not redundant: `make test` and the end-to-end image build both sync project
environments, which may rewrite a lock.

- `local` runs `make check-packaging`, then `make test`.
- `helm` runs the chart render checks with the chart-to-loader check able to run,
  builds the images, deploys and forwards the charts, runs the end-to-end pipeline's
  scenarios against the forwarded services, and always unforwards.

Each part stops at its first failure, keeps every step's output under
`.snapshot/validation/<commit>/<part>/`, prints a summary, and writes it as
`summary.json` beside the logs for the validation report.

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
STOREFRONT_PYTHON = Path("domains/vms/storefront/.venv/bin/python")
# The end-to-end pipeline's scenario selections, one per lane; the Helm run reads
# them from e2e-tests/Makefile so the two lists cannot drift apart.
PIPELINE_MARKER_VARIABLES = ("E2E_MODULE", "E2E_BARE_METAL_MODULE")
# Pipeline scenarios the default chart values cannot serve, each with what is
# missing. They are reported as not run against Helm, never as passed. An entry
# leaves this list when the charts and `make -C helm forward` provide what the
# pipeline's compose stacks do.
HELM_EXCLUSIONS = {
    "multi_registry": "a second storefront and a second registry",
    "e2e_credits_deal": "the API-credits service, storefront, and registry",
    "e2e_vm_introduction": "a forwarded Mailpit",
    "e2e_bare_metal_publication": "the bare-metal storefront and registry",
    "e2e_bare_metal_introduction": "the bare-metal storefront and registry",
}
# The local ports `make -C helm forward` binds. Port-forwards start in the
# background, so the scenarios wait for every port to accept a connection.
FORWARDED_PORTS = (8545, 8080, 8001, 8081)
FORWARD_WAIT_SECONDS = 60.0
TAIL_LINES = 40
_SKIP_LINE = re.compile(r"^skip:.*$", re.M)
_MARKER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Runs a command from the repository root, writing its combined output to the log
# file, and returns the exit status.
Runner = Callable[[Sequence[str], Path], int]
# Reads a command's standard output; raises ValidationError when the command fails.
Reader = Callable[[Sequence[str]], str]
PortProbe = Callable[[int], bool]


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
    passed: bool = True
    steps: list[Step] = field(default_factory=list)
    not_run: dict[str, str] = field(default_factory=dict)


def _run_logged(command: Sequence[str], log: Path) -> int:
    with log.open("w", encoding="utf-8") as stream:
        return subprocess.run(list(command), cwd=ROOT, stdin=subprocess.DEVNULL,
                              stdout=stream, stderr=subprocess.STDOUT).returncode


def _read(command: Sequence[str]) -> str:
    try:
        return subprocess.run(list(command), cwd=ROOT, capture_output=True, text=True,
                              check=True).stdout
    except FileNotFoundError as exc:
        raise ValidationError(f"{command[0]} is required but was not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        raise ValidationError(f"{' '.join(command)} failed: {detail}") from exc


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
        self.summary = Summary(part=part, commit=commit)
        self.log_dir = root / LOG_ROOT / commit[:12] / part

    @property
    def failed(self) -> bool:
        return not self.summary.passed

    def fail(self, name: str, detail: str) -> None:
        self.summary.steps.append(Step(name, "failed", detail=detail))
        self.summary.passed = False

    def note(self, name: str, detail: str) -> None:
        self.summary.steps.append(Step(name, "passed", detail=detail))

    def clean(self, name: str) -> bool:
        dirty = dirty_paths(self.read)
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
    for name, command in (("check-packaging", ["make", "check-packaging"]),
                          ("test", ["make", "test"])):
        if validation.step(name, command).result != "passed":
            break
    validation.clean("clean after")
    return validation.finish()


def validate_helm(validation: Validation, *, context: str = DEFAULT_HELM_CONTEXT,
                  probe: PortProbe = _port_open, sleep: Callable[[float], None] = time.sleep,
                  forward_wait: float = FORWARD_WAIT_SECONDS) -> Summary:
    if not validation.clean("clean before") or not _helm_preflight(validation, context):
        return validation.finish()
    try:
        markers = pipeline_markers(validation.read)
    except ValidationError as exc:
        validation.fail("scenarios", str(exc))
        return validation.finish()
    selected = [marker for marker in markers if marker not in HELM_EXCLUSIONS]
    validation.summary.not_run = {marker: f"the charts do not deploy {HELM_EXCLUSIONS[marker]}"
                                  for marker in markers if marker in HELM_EXCLUSIONS}

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

    for name, command in (("build-dev", ["make", "build-dev"]),
                          ("deploy", ["make", "-C", "helm", "deploy"])):
        if validation.step(name, command).result != "passed":
            return _after_helm(validation)
    try:
        if (validation.step("forward", ["make", "-C", "helm", "forward"]).result == "passed"
                and _wait_for_ports(validation, probe, sleep, forward_wait)):
            if selected:
                validation.step("e2e", ["make", "-C", "e2e-tests", "test-module",
                                        f"MODULE={' or '.join(selected)}"])
            else:
                validation.note("e2e", "every pipeline scenario is excluded from the Helm run")
    finally:
        validation.step("unforward", ["make", "-C", "helm", "unforward"])
    return _after_helm(validation)


def _after_helm(validation: Validation) -> Summary:
    validation.clean("clean after")
    return validation.finish()


def _helm_preflight(validation: Validation, context: str) -> bool:
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
    lines = [f"{summary.part} validation of {summary.commit[:12]}: "
             f"{'PASSED' if summary.passed else 'FAILED'}"]
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
    args = parser.parse_args(argv)
    try:
        validation = Validation(args.part)
        if args.part == "local":
            summary = validate_local(validation)
        else:
            summary = validate_helm(validation, context=args.context or DEFAULT_HELM_CONTEXT)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(render(summary))
    print(f"Summary written to {validation.log_dir.relative_to(ROOT) / 'summary.json'}")
    return 0 if summary.passed else 1


if __name__ == "__main__":
    sys.exit(main())
