#!/usr/bin/env python3
"""Evidence only a push produces: dispatching a CI workflow, and reading its run.

A change branch's push triggers no CI workflow, so a plan names what it needs from
one as owed by validation, which dispatches the workflow on the branch and judges
the run of the validated commit.

`dispatch <workflow>` runs `gh workflow run <workflow> --ref <branch>` for a
workflow on `DISPATCHABLE`, and refuses any other, naming the list. Several
workflows that accept a dispatch publish a release, so a plan naming one must not
be able to publish from a feature branch; the list is held here rather than in the
step table because the table binds only unattended runs. Before dispatching it
prints the newest run of the workflow on the branch, as `CI_AFTER_RUN=<id>`, so the
fetch that follows waits for a run newer than it.

The rest is the comparison validation's `ci` part makes (`validate_slice.py ci`).
A workflow may fail on `dev` in jobs no change owes, so a run's conclusion says
little; every failure of a job is compared instead with the same job in a
baseline, the latest completed run of the workflow on `dev` whose head commit is an
ancestor of the validated commit, so its code is code the branch contains. A
failure is a failing test's ID with its exception type, read from pytest's short
summary (`FAILED <id> - <type>: <message>`); the type tells a test failing another
way from one failing as it does on `dev`. A job that prints no failing test — a
TypeScript or Rust job, or a setup step — is known by its failing step and the
runner's error lines instead. Each failure is classed:

- `inherited`: the baseline's same job fails that test with the same type and
  outcome, or fails at the same step with the same error lines;
- `new`: it does not, the baseline's job passing, failing at other steps, or
  failing otherwise;
- `uncomparable`: there is no baseline; the baseline has no such job, or skipped
  it; either log holds no line of the job; a failing test's line names no type; a
  job failed naming no failing step; a step's error lines say only that it
  failed; or one side names failing tests where the other names only the same
  step failing.

Contract: openspec/specs/change-workflow/spec.md, "Validation observes a committed
slice".
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, Sequence

# The workflows validation may dispatch. None publishes; adding one is the owner's
# tracked change. `e2e.yml` is validation's pipeline part, dispatched by `make run-e2e`.
DISPATCHABLE = ("tests.yml",)
BASELINE_BRANCH = "dev"
RUN_LIST_LIMIT = 100

INHERITED, NEW, UNCOMPARABLE = "inherited", "new", "uncomparable"
# A job conclusion that is not a failure; anything else, a timeout included, is one.
NOT_FAILED = ("success", "skipped", "neutral")

# `gh run view --log` prefixes each line with its job and step, tab-separated, and
# the runner's timestamp, which may follow a byte-order mark.
_TIMESTAMP = re.compile(r"^﻿?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ?")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_SUMMARY_HEADER = re.compile(r"^=+ short test summary info =+$")
# What ends a short summary: pytest's closing count, with or without its rule, as
# `-q` prints it. On CI pytest prints each entry's whole crash message, which may
# run over several lines, so the end is matched this closely: any looser, a line
# of a message could end the summary and hide the entries after it.
_COUNT = (r"(?:\d+ (?:failed|passed|errors?|skipped|deselected|xfailed|xpassed|"
          r"warnings?|rerun)(?:, )?)+ in [0-9.]+s(?: \(\d+:\d\d:\d\d\))?")
_SUMMARY_END = re.compile(rf"^(?:=+ {_COUNT} =+|{_COUNT})$")
# A failing test: its ID, whose parameters may hold spaces, then its crash message,
# which pytest leaves out when it trims a line to the terminal, as it does off CI.
_FAILURE = re.compile(r"^(FAILED|ERROR) (\S+?(?:\[[^\]]*\])?)(?: - (.*))?$")
# An exception's type, before its message; or alone, an exception raised with none.
_EXCEPTION_TYPE = re.compile(r"^([A-Za-z_][\w.]*):(?=\s|$)")
_BARE_EXCEPTION = re.compile(r"^((?:[a-z_]\w*\.)*[A-Z]\w*)$")
_ERROR_LINE = "##[error]"
# The runner's own closing line for a failed step, which says only that it failed.
_EXIT_LINE = re.compile(r"^Process completed with exit code \d+\.$")

# Runs a command as subprocess.run does, given `capture_output=True`, `text=True`,
# and `check=False`; GitHub's and Git's command lines are this script's boundary.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class CIError(RuntimeError):
    """A workflow could not be dispatched, or a run or commit could not be read."""


@dataclass(frozen=True)
class Failure:
    """One failing test of a job, as pytest's short summary names it."""

    test: str
    type: str | None
    outcome: str  # FAILED, or ERROR for an error outside the test body


@dataclass
class Job:
    """A job of a run: its conclusion, what failed, and its log lines."""

    name: str
    conclusion: str
    failed_steps: list[str] = field(default_factory=list)
    failures: list[Failure] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return self.conclusion not in NOT_FAILED


def _run(command: Sequence[str], runner: Runner) -> subprocess.CompletedProcess[str]:
    try:
        return runner(list(command), capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise CIError(f"{command[0]} is required but was not found") from exc


def _checked(command: Sequence[str], runner: Runner) -> str:
    result = _run(command, runner)
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        raise CIError(f"{' '.join(command)} exited {result.returncode}"
                      + (f": {detail}" if detail else ""))
    return result.stdout


def refuse_unlisted(workflow: str) -> None:
    """Raise unless validation may dispatch `workflow`."""
    if workflow not in DISPATCHABLE:
        raise CIError(f"{workflow or 'no workflow'} is not a workflow validation may "
                      f"dispatch; it may dispatch: {', '.join(DISPATCHABLE)}")


def newest_run(workflow: str, branch: str, runner: Runner) -> int:
    """The ID of the workflow's newest run on the branch, or 0 when it has none."""
    command = ["gh", "run", "list", "--workflow", workflow, "--branch", branch,
               "--limit", "1", "--json", "databaseId"]
    try:
        listed = json.loads(_checked(command, runner) or "[]")
        if listed and isinstance(listed, list) and isinstance(listed[0], dict):
            return int(listed[0].get("databaseId") or 0)
    except ValueError as exc:
        raise CIError(f"{' '.join(command)} gave no run list: {exc}") from exc
    return 0


def dispatch(workflow: str, *, runner: Runner = subprocess.run,
             echo: Callable[[str], None] = print) -> int:
    """Dispatch a listed workflow on the current branch; the newest run before it."""
    refuse_unlisted(workflow)
    branch = _checked(["git", "branch", "--show-current"], runner).strip()
    if not branch:
        raise CIError("a checked-out branch is required: the workflow runs on it")
    after = newest_run(workflow, branch, runner)
    echo(f"Newest {workflow} run on {branch} before the dispatch: {after or 'none'}")
    echo(f"CI_AFTER_RUN={after}")
    echo(f"Dispatching {workflow} on {branch}...")
    _checked(["gh", "workflow", "run", workflow, "--ref", branch], runner)
    return after


def _git_answer(command: Sequence[str], runner: Runner) -> bool:
    """Git's yes (0) or no (1); any other exit is a failure, not an answer."""
    result = _run(command, runner)
    if result.returncode in (0, 1):
        return result.returncode == 0
    raise CIError(f"{' '.join(command)} exited {result.returncode}: "
                  f"{(result.stderr or '').strip()}")


def is_ancestor(ancestor: str, commit: str, runner: Runner = subprocess.run) -> bool:
    """Whether `ancestor` is `commit` or one of its ancestors in this repository."""
    # A commit this repository lacks cannot be an ancestor of one it holds.
    if not _git_answer(["git", "rev-parse", "--verify", "--quiet", f"{ancestor}^{{commit}}"],
                       runner):
        return False
    return _git_answer(["git", "merge-base", "--is-ancestor", ancestor, commit], runner)


def baseline_run(listed: list, contains: Callable[[str], bool]) -> dict | None:
    """The newest completed run in `listed` whose head commit `contains` accepts.

    `listed` is `gh run list --status completed --json
    databaseId,headSha,conclusion,event` on the baseline branch. A cancelled run
    is skipped, since it completed without its jobs finishing, and so is a pull
    request's, which tests a merge of the branch rather than its head commit.
    """
    runs = [run for run in listed
            if isinstance(run, dict) and str(run.get("databaseId", "")).isdigit()
            and isinstance(run.get("headSha"), str)]
    for run in sorted(runs, key=lambda run: int(run["databaseId"]), reverse=True):
        if (run.get("conclusion") != "cancelled"
                and not str(run.get("event", "")).startswith("pull_request")
                and contains(run["headSha"])):
            return {"id": int(run["databaseId"]), "commit": run["headSha"],
                    "conclusion": run.get("conclusion")}
    return None


def exception_type(message: str | None) -> str | None:
    """The exception type a short-summary message starts with, if it names one."""
    if not message:
        return None
    match = _EXCEPTION_TYPE.match(message) or _BARE_EXCEPTION.match(message)
    if match:
        return match[1]
    # pytest gives a failed plain `assert` as the assertion itself.
    return "AssertionError" if message.startswith("assert ") else None


def _log_lines(log: str) -> Iterable[tuple[str, str, str]]:
    """Each line of a run's log as (job, step, text), its prefix, timestamp, and
    colour gone; a line without the prefix belongs to the line before it."""
    job = step = ""
    for raw in log.splitlines():
        parts = raw.split("\t", 2)
        if len(parts) == 3:
            job, step, text = parts
        else:
            text = raw
        yield job, step, _ANSI.sub("", _TIMESTAMP.sub("", text)).rstrip()


def read_jobs(run: dict, log: str) -> dict[str, Job]:
    """The run's jobs, from `gh run view --json jobs` and its whole log."""
    jobs: dict[str, Job] = {}
    for entry in run.get("jobs") or []:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            continue
        jobs[entry["name"]] = Job(
            entry["name"], str(entry.get("conclusion") or entry.get("status") or "unknown"),
            [step["name"] for step in entry.get("steps") or []
             if isinstance(step, dict) and step.get("conclusion") == "failure"
             and isinstance(step.get("name"), str)])
    # Each job's open short summary, by the step printing it.
    in_summary: dict[str, str] = {}
    for name, step, text in _log_lines(log):
        job = jobs.get(name)
        if job is None:
            continue
        job.lines.append(text)
        if text.startswith(_ERROR_LINE):
            job.errors.append(text[len(_ERROR_LINE):].strip())
        if _SUMMARY_HEADER.match(text):
            in_summary[name] = step
            continue
        if name not in in_summary:
            continue
        # The closing count ends a summary; so does the runner's own output, or the
        # step's end, should pytest have printed none.
        if (in_summary[name] != step or text.startswith("##[")
                or _SUMMARY_END.match(text)):
            del in_summary[name]
        elif match := _FAILURE.match(text):
            failure = Failure(match[2], exception_type(match[3]), match[1])
            if failure not in job.failures:
                job.failures.append(failure)
    return jobs


NO_BASELINE = f"no completed {BASELINE_BRANCH} run of code the branch contains"


def _step_failures(job: Job) -> list[dict]:
    # A job printing no failing test is known only by where it failed and the
    # error lines the runner printed.
    return [{"step": step, "errors": job.errors} for step in (job.failed_steps or [None])]


def _classed(failures: list[dict], name: str) -> list[dict]:
    return [dict(failure, **{"class": name}) for failure in failures]


def _telling_errors(job: Job) -> list[str]:
    """The job's error lines that say what failed, not only that a step did."""
    return [line for line in job.errors if not _EXIT_LINE.match(line)]


def _by_test(failure: dict, known: set[tuple[str, str | None, str]]) -> dict:
    if failure["type"] is None:
        # Without its type a test's failure is its ID alone, which cannot tell a
        # test failing another way from one failing as it does on `dev`.
        return dict(failure, **{"class": UNCOMPARABLE,
                                "reason": "its line names no exception type"})
    key = (failure["test"], failure["type"], failure["outcome"])
    return dict(failure, **{"class": INHERITED if key in known else NEW})


def _classify(job: Job, baseline: dict[str, Job] | None,
              no_baseline: str) -> tuple[list[dict], str | None]:
    """Each failure of a failing job with its class, and why, when it has one reason."""
    by_test = bool(job.failures)
    failures = [asdict(f) for f in job.failures] if by_test else _step_failures(job)
    if not job.lines:
        return _classed(failures, UNCOMPARABLE), (
            "the run's log holds no line of this job, so nothing shows what failed")
    if baseline is None:
        return _classed(failures, UNCOMPARABLE), no_baseline
    other = baseline.get(job.name)
    if other is None:
        return _classed(failures, UNCOMPARABLE), "the baseline run has no job of this name"
    if other.conclusion == "success":
        return _classed(failures, NEW), None
    if not other.failed:
        return _classed(failures, UNCOMPARABLE), (
            f"the baseline's job was {other.conclusion}, so it shows nothing of these")
    if not other.lines:
        return _classed(failures, UNCOMPARABLE), (
            "the baseline's log holds no line of this job, so nothing shows what failed")
    if by_test and other.failures:
        known = {(f.test, f.type, f.outcome) for f in other.failures}
        return [_by_test(failure, known) for failure in failures], None
    if not job.failed_steps or not other.failed_steps:
        return _classed(failures, UNCOMPARABLE), (
            "the job, or the baseline's, failed naming no failing step")
    if not set(job.failed_steps) & set(other.failed_steps):
        # The steps that fail here passed in the baseline.
        return _classed(failures, NEW), None
    if not by_test and not other.failures:
        errors = _telling_errors(job)
        if not errors or not _telling_errors(other):
            # Both failing at one step with no more said cannot show that they
            # fail the same way.
            return _classed(failures, UNCOMPARABLE), (
                "the step's error lines say only that it failed, not what failed")
        # The same step failing with the same error lines fails as it does on `dev`.
        return [dict(failure, **{"class": INHERITED if failure["step"] in other.failed_steps
                                 and errors == _telling_errors(other) else NEW})
                for failure in failures], None
    return _classed(failures, UNCOMPARABLE), (
        "one side names failing tests and the other only the step that failed, so the "
        "two cannot be compared")


def compare(run_jobs: dict[str, Job], baseline_jobs: dict[str, Job] | None,
            no_baseline: str = NO_BASELINE) -> list[dict]:
    """Every job of the run, its failures classed against the baseline's same job.

    `baseline_jobs` is None when there is no baseline run to compare with, and
    `no_baseline` then says why.
    """
    compared = []
    for job in run_jobs.values():
        entry: dict = {"name": job.name, "conclusion": job.conclusion,
                       "failed_steps": job.failed_steps, "errors": job.errors,
                       "failures": [], "reason": None}
        if job.failed:
            entry["failures"], entry["reason"] = _classify(job, baseline_jobs, no_baseline)
        compared.append(entry)
    return compared


def classes(compared: Sequence[dict]) -> dict[str, int]:
    """How many failures fall in each class, over every job."""
    counts = {INHERITED: 0, NEW: 0, UNCOMPARABLE: 0}
    for job in compared:
        for failure in job["failures"]:
            counts[failure["class"]] += 1
    return counts


def main(argv: Sequence[str] | None = None, runner: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    dispatching = commands.add_parser(
        "dispatch", help="dispatch a workflow validation may dispatch on the current branch")
    dispatching.add_argument("workflow", help=f"one of: {', '.join(DISPATCHABLE)}")
    args = parser.parse_args(argv)
    try:
        dispatch(args.workflow.strip(), runner=runner)
    except CIError as exc:
        print(f"ci_evidence: {exc}", file=sys.stderr)
        return 2 if args.workflow.strip() not in DISPATCHABLE else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
