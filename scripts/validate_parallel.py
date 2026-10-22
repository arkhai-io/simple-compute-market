#!/usr/bin/env python3
"""Validate two changes' clones on the Helm charts at once, and report whether each
kept to its own namespace, tags, and scenario pod.

Each change's Helm validation runs in a namespace of its own, on images tagged for
that change alone (`scripts/validate_slice.py`), so two of them may share one
cluster. This is the evidence that they do. It starts both clones'
`make validate-helm` at the same moment, waits for both, and then reads their
summaries and the cluster to report:

- that the two runs overlapped, and whether their scenario pods ran together;
- each Helm part's result;
- separate namespaces, each the one its change derives;
- separate tags: the two runs' image overlays share no tag, and every image built
  here that a run's pods ran carries a tag of that run's own overlay;
- each run's scenario pod, in its own namespace and on its own image, exiting 0;
- what each run's namespace holds of the validation release once both have ended,
  as the Helm part itself scopes it — the release's labelled pods, workloads, and
  volumes, and the claims its pods mounted: exactly one release revision made
  since the check started, every such volume and pod created during that
  namespace's own run and every pod on that run's own images, every mounted claim
  still present, and its workloads at zero. A namespace whose own Helm part did
  not pass is not judged, since what it holds then is its own run's unfinished
  work, and the check fails with `results`.

The cluster is read only after both runs, and the two runs overlap almost
entirely, so the times separate nothing between them: a disturbance shows only by
what it left — a second release revision, a pod on the other's images, a missing
claim, a workload scaled up again — and one that left nothing, such as a pod
deleted and recreated by its own ReplicaSet, or the release uninstalled and
installed again, is not shown. That each run's own commands name only its
namespace is `scripts/tests/test_validate_slice.py`'s.

A clone is a directory `make change-clone` made, `<workspace>.changes/<change>/`,
with its change's branch checked out and its bootstrap succeeded, since the Helm
part needs the clone's environments; its change is read from where it stands. Each
run's output is kept as `<change>.log`, with `report.json` beside it, under
`.snapshot/parallel-validation/<time>/` in the checkout this runs from.

Contract: openspec/specs/change-workflow/spec.md, "Each Helm validation is isolated
in its change's namespace", scenario "Two changes are validated at once".
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Protocol, Sequence

import change_clone
import change_namespace

ROOT = Path(__file__).resolve().parents[1]
LOG_ROOT = Path(".snapshot/parallel-validation")
DEFAULT_HELM_CONTEXT = "docker-desktop"
READ_TIMEOUT_SECONDS = 120.0
# The image name every image the build targets write carries.
BUILT_HERE = change_namespace.BUILT_HERE
# What `validate_slice.py` prints last: where the attempt's logs and summary are.
_ATTEMPT = re.compile(r"^Attempt \d+ logs and summary\.json: (?P<path>\S+)\s*$", re.M)
_TIMESTAMP = re.compile(r"^(?P<time>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.(?P<fraction>\d+))?"
                        r"(?P<zone>Z|[+-]\d\d:\d\d)$")
# Variables `make` hands down to every `make` it runs: neither the clones' targets
# nor the reads here may take this command line's variables or a step's CHANGE.
_INHERITED = ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "MAKEOVERRIDES", "CHANGE")
TAIL_LINES = 20
# Errors a malformed document raises where a field is missing or of another type.
_MALFORMED = (KeyError, TypeError, AttributeError, ValueError)


class CheckError(RuntimeError):
    """The check could not start, or something it reads could not be read."""


class Process(Protocol):
    def wait(self) -> int: ...


# Starts a command in a directory, its combined output to a log, and returns it running.
Launch = Callable[[Sequence[str], Path, Path], Process]
# Reads a command's standard output; raises CheckError when the command fails.
Reader = Callable[[Sequence[str]], str]
# The change a clone was made for; raises CheckError for a directory that is not one.
Locate = Callable[[Path], str]


@dataclass
class Check:
    name: str
    passed: bool
    detail: str


@dataclass
class Run:
    clone: Path
    change: str
    log: Path
    started: datetime | None = None
    ended: datetime | None = None
    status: int | None = None
    attempt: Path | None = None
    summary: dict = field(default_factory=dict)
    release: str = ""
    release_error: str = ""

    @property
    def namespace(self) -> str:
        return change_namespace.namespace(self.change)

    @property
    def passed(self) -> bool:
        return self.status == 0 and self.summary.get("passed") is True

    def window(self) -> tuple[datetime, datetime]:
        # Kubernetes records creation times in whole seconds, so the window is
        # widened to them rather than miss an object made in its first or last.
        assert self.started is not None and self.ended is not None
        end = self.ended.replace(microsecond=0)
        if end < self.ended:
            end += timedelta(seconds=1)
        return self.started.replace(microsecond=0), end


@dataclass
class Report:
    runs: list[Run]
    checks: list[Check]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


class _Exited:
    """A run that could not be started, as a process that has already ended."""

    def __init__(self, status: int) -> None:
        self.status = status

    def wait(self) -> int:
        return self.status


def _environment() -> dict[str, str]:
    return {name: value for name, value in os.environ.items() if name not in _INHERITED}


def _launch(command: Sequence[str], cwd: Path, log: Path) -> Process:
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        return subprocess.Popen(list(command), cwd=cwd, env=_environment(),
                                stdin=subprocess.DEVNULL, stdout=stream,
                                stderr=subprocess.STDOUT)


def _read(command: Sequence[str]) -> str:
    try:
        return subprocess.run(list(command), cwd=ROOT, env=_environment(),
                              capture_output=True, text=True, check=True,
                              timeout=READ_TIMEOUT_SECONDS).stdout
    except FileNotFoundError as exc:
        raise CheckError(f"{command[0]} is required but was not found") from exc
    except subprocess.CalledProcessError as exc:
        raise CheckError(f"{' '.join(command)} failed: {(exc.stderr or '').strip()}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CheckError(f"{' '.join(command)} did not answer within "
                         f"{READ_TIMEOUT_SECONDS:g}s") from exc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def change_of(clone: Path) -> str:
    """The change `clone` was made for, once it holds that change's branch and its
    bootstrap has succeeded."""
    clone = clone.resolve()
    workspace = change_clone.workspace_of(clone)
    if workspace is None:
        raise CheckError(f"{clone} is not a change's clone: no `workspace` remote of it "
                         "names a directory")
    change = clone.name
    if change_clone.clone_of(workspace, change) != clone:
        raise CheckError(f"{clone} is not {workspace}'s clone of {change} with that "
                         "change's branch checked out")
    bootstrap = change_clone.bootstrap_state(clone)
    if bootstrap.state != change_clone.SUCCEEDED:
        log = f"; its log is {bootstrap.log}" if bootstrap.log else ""
        raise CheckError(f"{clone}'s bootstrap is {bootstrap.state}{log}: the Helm part "
                         "needs the clone's environments, which `make change-clone` builds")
    return change


def parse_time(text: str) -> datetime:
    """A Kubernetes or Helm timestamp, to the microsecond."""
    match = _TIMESTAMP.match(text.strip())
    if not match:
        raise ValueError(f"{text!r} is not a timestamp")
    fraction = (match["fraction"] or "")[:6].ljust(6, "0")
    zone = "+00:00" if match["zone"] == "Z" else match["zone"]
    return datetime.fromisoformat(f"{match['time']}.{fraction}{zone}")


def _items(text: str) -> list[dict]:
    listed = json.loads(text)
    if not isinstance(listed, dict) or not isinstance(listed.get("items", []), list):
        raise ValueError("not a Kubernetes list")
    return listed.get("items", [])


def _images(pod: dict) -> list[str]:
    spec = pod.get("spec") or {}
    return [container.get("image", "") for key in ("initContainers", "containers")
            for container in spec.get(key) or []]


def _built_here(image: object) -> str | None:
    """The tag of an image built here, `arkhai:<tag>`; None for any other image."""
    if not isinstance(image, str):
        raise TypeError(f"{image!r} is not an image name")
    name, _, tag = image.rpartition(":")
    return tag if name == BUILT_HERE else None


def _claims(pod: dict) -> set[str]:
    return {volume["persistentVolumeClaim"]["claimName"]
            for volume in (pod.get("spec") or {}).get("volumes") or []
            if "persistentVolumeClaim" in volume}


def _leaves(overlay: object) -> set[str]:
    if isinstance(overlay, dict):
        return {tag for value in overlay.values() for tag in _leaves(value)}
    return {overlay} if isinstance(overlay, str) else set()


def _created(item: dict) -> datetime:
    return parse_time(item["metadata"]["creationTimestamp"])


def _terminated(pod: dict) -> dict:
    statuses = (pod.get("status") or {}).get("containerStatuses") or [{}]
    return (statuses[0].get("state") or {}).get("terminated") or {}


class ParallelValidation:
    """Two clones' Helm parts run together, and their evidence read afterwards."""

    def __init__(self, clones: Sequence[Path], *, root: Path = ROOT,
                 context: str = DEFAULT_HELM_CONTEXT, launch: Launch = _launch,
                 read: Reader = _read, locate: Locate = change_of,
                 clock: Callable[[], datetime] = _now) -> None:
        if len(clones) != 2:
            raise CheckError(f"two clones are needed, not {len(clones)}")
        self.root, self.context = root, context
        self.launch, self.read, self.clock = launch, read, clock
        changes = [locate(clone) for clone in clones]
        for change in changes:
            change_namespace.namespace(change)
        if changes[0] == changes[1]:
            raise CheckError(f"both clones are of {changes[0]}: two changes are needed, since "
                             "one change's validations share its namespace")
        self.started = clock()
        self.directory = root / LOG_ROOT / self.started.strftime("%Y%m%dT%H%M%SZ")
        self.runs = [Run(clone.resolve(), change, self.directory / f"{change}.log")
                     for clone, change in zip(clones, changes)]

    def run(self) -> Report:
        processes = []
        for run in self.runs:
            run.started = self.clock()
            try:
                process = self.launch(
                    ["make", "-C", str(run.clone), "validate-helm", f"CHANGE={run.change}",
                     f"HELM_CONTEXT={self.context}"], run.clone, run.log)
            except OSError as exc:
                # The other run may already be going: it is still waited for and
                # reported.
                run.log.parent.mkdir(parents=True, exist_ok=True)
                run.log.write_text(f"ERROR: could not start: {exc}\n", "utf-8")
                process = _Exited(127)
            processes.append(process)
        # Each run's end is taken as it ends, not when the other has.
        waiters = [threading.Thread(target=self._wait, args=(run, process))
                   for run, process in zip(self.runs, processes)]
        for waiter in waiters:
            waiter.start()
        for waiter in waiters:
            waiter.join()
        for run in self.runs:
            self._load(run)
        report = Report(self.runs, self._checks())
        self._write(report)
        return report

    def _wait(self, run: Run, process: Process) -> None:
        try:
            run.status = process.wait()
        except OSError:
            run.status = None
        finally:
            run.ended = self.clock()

    def _kubectl(self, *arguments: str) -> str:
        # Every read names the context the runs deployed to, whatever is current.
        return self.read(["kubectl", "--context", self.context, *arguments])

    def _load(self, run: Run) -> None:
        text = run.log.read_text("utf-8", errors="replace") if run.log.is_file() else ""
        found = _ATTEMPT.findall(text)
        if found:
            run.attempt = run.clone / found[-1]
            try:
                summary = json.loads((run.attempt / "summary.json").read_text("utf-8"))
            except (OSError, ValueError):
                summary = {}
            run.summary = summary if isinstance(summary, dict) else {}
        try:
            run.release = self.read(["make", "-s", "--no-print-directory", "-C",
                                     str(run.clone / "helm"), "--eval",
                                     "print-%: ; @echo $($*)", "print-RELEASE",
                                     f"CHANGE={run.change}"]).strip()
        except CheckError as exc:
            run.release_error = str(exc)

    def _checks(self) -> list[Check]:
        # Each check reads what the runs left; a read that fails fails the check
        # that needed it, naming the read, and the other checks still report.
        return [self._together(), self._results(), self._namespaces(), self._tags(),
                self._scenario_pods(), self._untouched()]

    def _together(self) -> Check:
        first, second = self.runs
        overlap = first.started < second.ended and second.started < first.ended
        spans = "; ".join(f"{run.change} {run.started:%H:%M:%S}–{run.ended:%H:%M:%S}"
                          for run in self.runs)
        scenarios = []
        for run in self.runs:
            try:
                state = _terminated(self._scenario_pod(run))
                scenarios.append((parse_time(state["startedAt"]),
                                  parse_time(state["finishedAt"])))
            except (CheckError, *_MALFORMED):
                scenarios.append(None)
        if None in scenarios:
            pods = "their scenario pods' run times could not both be read"
        else:
            (a_start, a_end), (b_start, b_end) = scenarios
            pods = ("their scenario pods ran together" if a_start < b_end and b_start < a_end
                    else "their scenario pods ran one after the other")
        return Check("together", overlap, f"{spans}; {pods}")

    def _results(self) -> Check:
        details = []
        for run in self.runs:
            if run.passed:
                details.append(f"{run.change} passed, attempt {run.summary.get('attempt')} "
                               f"in {run.attempt.relative_to(run.clone)}")
            elif run.summary:
                steps = run.summary.get("steps")
                failed = [str(step.get("name")) for step in steps if isinstance(step, dict)
                          and step.get("result") == "failed"] if isinstance(steps, list) else []
                details.append(f"{run.change} failed at {', '.join(failed) or 'no step'}, "
                               f"in {run.attempt.relative_to(run.clone)}")
            else:
                tail = run.log.read_text("utf-8", errors="replace").splitlines()[-TAIL_LINES:] \
                    if run.log.is_file() else []
                details.append(f"{run.change} exited {run.status} with no summary; its log "
                               f"ends:\n" + "\n".join(f"| {line}" for line in tail))
        return Check("results", all(run.passed for run in self.runs), "\n".join(details))

    def _namespaces(self) -> Check:
        problems = [f"{run.change} ran in {run.summary.get('namespace')!r}, not {run.namespace}"
                    for run in self.runs if run.summary.get("namespace") != run.namespace]
        first, second = self.runs
        if first.namespace == second.namespace:
            problems.append(f"both changes derive {first.namespace}")
        return Check("namespaces", not problems,
                     "; ".join(problems) or ", ".join(run.namespace for run in self.runs))

    def _overlay(self, run: Run) -> set[str]:
        """The tags of the run's image overlay; CheckError when it cannot be read."""
        if run.attempt is None:
            raise CheckError(f"{run.change} left no attempt directory")
        path = run.attempt / "images.json"
        try:
            return _leaves(json.loads(path.read_text("utf-8")))
        except (OSError, ValueError) as exc:
            raise CheckError(f"{path} could not be read: {exc}") from exc

    def _ran(self, run: Run) -> list[dict]:
        """The pods the run kept the status of while its release was up; CheckError
        when they cannot be read."""
        evidence = run.summary.get("evidence")
        recorded = evidence.get("pod_statuses") if isinstance(evidence, dict) else None
        if not isinstance(recorded, str) or not recorded:
            raise CheckError(f"{run.change}'s summary names no kept pod statuses")
        try:
            pods = _items((run.clone / recorded).read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise CheckError(f"{run.clone / recorded} could not be read: {exc}") from exc
        if not all(isinstance(pod, dict) for pod in pods):
            raise CheckError(f"{run.clone / recorded} holds an item that is not a pod")
        return pods

    def _tags(self) -> Check:
        problems, details, overlays = [], [], []
        for run in self.runs:
            try:
                own, kept = self._overlay(run), self._ran(run)
                ran = sorted({tag for pod in kept for image in _images(pod)
                              if (tag := _built_here(image)) is not None})
            except (CheckError, *_MALFORMED) as exc:
                problems.append(f"{run.change}: {exc}")
                overlays.append(set())
                continue
            overlays.append(own)
            if not own:
                problems.append(f"{run.change}'s image overlay names no tag")
            if not ran:
                problems.append(f"{run.change}'s kept pod statuses show no image built here")
            stray = [tag for tag in ran if tag not in own]
            if stray:
                problems.append(f"{run.change}'s pods ran {', '.join(stray)}, outside its "
                                "own overlay")
            details.append(f"{run.change}: {', '.join(ran)}")
        shared = overlays[0] & overlays[1]
        if shared:
            problems.append(f"both overlays name {', '.join(sorted(shared))}")
        return Check("tags", not problems, "; ".join(problems) or "; ".join(details))

    def _scenario_pod(self, run: Run) -> dict:
        evidence = run.summary.get("evidence")
        record = evidence.get("scenarios") if isinstance(evidence, dict) else None
        if not isinstance(record, dict) or not isinstance(record.get("pod"), str):
            raise CheckError(f"{run.change}'s summary names no scenario pod")
        pod = json.loads(self._kubectl("get", "pod", record["pod"], "--namespace",
                                       run.namespace, "--output", "json"))
        if not isinstance(pod, dict):
            raise ValueError(f"{record['pod']} is not a pod document")
        return pod

    def _scenario_pods(self) -> Check:
        problems, details = [], []
        for run in self.runs:
            try:
                own = self._overlay(run)
                pod = self._scenario_pod(run)
                metadata = pod.get("metadata") or {}
                name, namespace = metadata.get("name"), metadata.get("namespace")
                code = _terminated(pod).get("exitCode")
                images = [image for image in _images(pod) if _built_here(image) is not None]
            except (CheckError, *_MALFORMED) as exc:
                problems.append(f"{run.change}: {exc}")
                continue
            if namespace != run.namespace:
                problems.append(f"{run.change}'s scenario pod {name} is in {namespace}")
            if code != 0:
                problems.append(f"{run.change}'s scenario pod {name} exited {code}")
            if not images or any(_built_here(image) not in own for image in images):
                ran = ", ".join(images) or "no image built here"
                problems.append(f"{run.change}'s scenario pod {name} ran {ran}, not its own")
            details.append(f"{namespace}/{name} on {', '.join(images)}, exit {code}")
        return Check("scenario pods", not problems, "; ".join(problems) or "; ".join(details))

    def _untouched(self) -> Check:
        problems, details = [], []
        for run in self.runs:
            if not run.passed:
                details.append(f"{run.namespace}: not judged, since its own Helm part did "
                               "not pass")
                continue
            try:
                found = self._namespace_problems(run, self._overlay(run))
            except (CheckError, *_MALFORMED) as exc:
                problems.append(f"{run.namespace}: could not be read: {exc}")
                continue
            problems += [f"{run.namespace}: {problem}" for problem in found]
            if not found:
                details.append(f"{run.namespace}: one revision of {run.release}, its volumes "
                               "and pods made during its own run on its own images, "
                               "workloads at zero")
        passed = not problems and all(run.passed for run in self.runs)
        return Check("untouched", passed, "; ".join(problems + details))

    def _namespace_problems(self, run: Run, own: set[str]) -> list[str]:
        if not run.release:
            raise CheckError(f"its release could not be read from {run.clone}'s "
                             f"helm/Makefile: {run.release_error or 'it names none'}")
        start, end = run.window()
        scope = ["--namespace", run.namespace, "--output", "json"]
        problems = []
        history = json.loads(self.read(["helm", "history", run.release, "--kube-context",
                                        self.context, *scope]))
        if not isinstance(history, list):
            raise ValueError(f"helm history of {run.release} is not a list")
        # Helm records a revision's time to the nanosecond; whole seconds suffice.
        revisions = [entry for entry in history
                     if parse_time(entry["updated"]) >= self.started.replace(microsecond=0)]
        if len(revisions) != 1:
            problems.append(f"{len(revisions)} revisions of {run.release} since the check "
                            "started, where its own run makes one: "
                            + ", ".join(f"{entry['revision']} ({entry.get('description')})"
                                        for entry in revisions))
        # Only what the run replaces is judged — the release's labelled objects and
        # the claims its pods mounted, the test volume no chart labels among them —
        # since the namespace may also hold what the run leaves alone.
        selector = ["--selector", f"app.kubernetes.io/instance={run.release}"]
        mounted = set().union(*map(_claims, self._ran(run)))
        volumes = _items(self._kubectl("get", "pvc", *scope))
        names = {volume["metadata"]["name"] for volume in volumes}
        for volume in volumes:
            labels = volume["metadata"].get("labels") or {}
            if (labels.get("app.kubernetes.io/instance") != run.release
                    and volume["metadata"]["name"] not in mounted):
                continue
            if not start <= _created(volume) <= end:
                problems.append(f"volume {volume['metadata']['name']} was created at "
                                f"{volume['metadata']['creationTimestamp']}, outside its run")
        missing = sorted(mounted - names)
        if missing:
            problems.append(f"{', '.join(missing)}, which its pods mounted, no longer exist")
        for pod in _items(self._kubectl("get", "pods", *scope, *selector)):
            name = pod["metadata"]["name"]
            if not start <= _created(pod) <= end:
                problems.append(f"pod {name} was created at "
                                f"{pod['metadata']['creationTimestamp']}, outside its run")
            stray = [image for image in _images(pod)
                     if (tag := _built_here(image)) is not None and tag not in own]
            if stray:
                problems.append(f"pod {name} runs {', '.join(stray)}, not its own images")
        up = [f"{workload['kind']}/{workload['metadata']['name']}"
              for workload in _items(self._kubectl("get", "deployments,statefulsets", *scope,
                                                   *selector))
              if (workload.get("spec") or {}).get("replicas", 0)]
        if up:
            problems.append(f"{', '.join(up)} up after its run ended")
        return problems

    def _write(self, report: Report) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        runs = [{"clone": str(run.clone), "change": run.change, "namespace": run.namespace,
                 "started": run.started.isoformat(), "ended": run.ended.isoformat(),
                 "status": run.status, "log": str(run.log.relative_to(self.root)),
                 "attempt": str(run.attempt) if run.attempt else None}
                for run in report.runs]
        (self.directory / "report.json").write_text(json.dumps(
            {"passed": report.passed, "started": self.started.isoformat(), "runs": runs,
             "checks": [asdict(check) for check in report.checks]}, indent=2) + "\n", "utf-8")


def render(report: Report) -> str:
    changes = " and ".join(f"{run.change} ({run.clone})" for run in report.runs)
    lines = [f"parallel Helm validation of {changes}: "
             f"{'PASSED' if report.passed else 'FAILED'}"]
    for check in report.checks:
        lines.append(f"  {'passed' if check.passed else 'failed':<7} {check.name}")
        lines += [f"          {line}" for line in check.detail.splitlines()]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("clones", nargs="*", type=Path, metavar="CLONE",
                        help="two changes' clones, as `make change-clone` made them")
    parser.add_argument("--context", default=DEFAULT_HELM_CONTEXT,
                        help="the only kube context the Helm parts may deploy to")
    args = parser.parse_args(argv)
    try:
        check = ParallelValidation(args.clones, context=args.context or DEFAULT_HELM_CONTEXT)
    except (CheckError, change_clone.CloneError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    report = check.run()
    print(render(report))
    print(f"Logs and report.json: {check.directory.relative_to(ROOT)}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
