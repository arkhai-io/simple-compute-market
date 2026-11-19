#!/usr/bin/env python3
"""Wait for a GitHub Actions run, download its logs, and zip the directory.

The run's whole log is downloaded for any workflow. The end-to-end lanes' compose
logs are artifacts only `e2e.yml` uploads, so they are asked for only of its runs:
another workflow's run has none, and asking would warn of each as missing.

Without a run ID, the run is the newest one on the current branch whose head commit
is the commit asked for, local HEAD by default. Matching the commit, not only the
branch, is what makes the fetch safe straight after a dispatch: the new run may not
be listed yet, and the previous, finished run on the branch tested another commit.
A just-dispatched run is waited for, with a bound. When the commit already has a
run — validation repeated on one commit — the earlier run matches before the new
one is listed, so the caller passes the newest run ID it saw before dispatching
(`--after-run`) and only later runs are considered; run IDs only increase.
`--event` narrows the runs considered to those triggered so: a pull request's run
reports the same head commit while testing a merge of the branch, so a caller
that dispatched a run asks for `workflow_dispatch`.

`--evidence <commit>` makes the fetch validation's `pipeline` evidence of that
commit, which a run dispatched for it describes: the run of the commit is waited
for and its logs kept under `.snapshot/evidence/<commit>/pipeline/<attempt>/`, with
a `summary.json` naming the run, its conclusion, the logs kept, and whether it
passed, written whatever happened, so a fetch that found no run leaves an attempt
saying why. An attempt is named by the UTC time it started, of fixed width, as
`scripts/validate_slice.py` names its own, so path order is time order and the last
attempt is the current one. No archive is made of it. The fetch then exits 1 unless
the run concluded `success`.

Contract: openspec/specs/market-change-workflow/spec.md, MCW-r4tx and MCW-7hr1.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Any, Callable, Sequence


DEFAULT_WORKFLOW = "e2e.yml"
DEFAULT_OUTPUT_DIR = Path(".snapshot/e2e-logs")
# Where validation's evidence is kept, under the commit it describes; Git ignores it.
EVIDENCE_ROOT = Path(".snapshot/evidence")
EVIDENCE_KIND = "pipeline"
ATTEMPT_FORMAT = "%Y%m%dT%H%M%S.%fZ"
RUN_LIST_LIMIT = 100
DEFAULT_WAIT_SECONDS = 180.0
POLL_SECONDS = 5.0
LOG_ARTIFACTS = ("e2e-vm-logs", "e2e-bare-metal-logs", "e2e-apicredits-logs")
COMPOSE_LOG = "compose-logs.txt"


# Runs a command as subprocess.run does, given `text=True` and `check=True`; the
# GitHub and Git command line is this script's only boundary.
Runner = Callable[..., "subprocess.CompletedProcess[str]"]


class FetchError(RuntimeError):
    """The requested run or one of its diagnostic logs could not be obtained."""


def _run(
    command: Sequence[str],
    *,
    runner: Runner,
    capture_output: bool = False,
    stdout: IO[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return runner(
            list(command),
            capture_output=capture_output,
            stdout=stdout,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise FetchError(f"{command[0]} is required but was not found") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip()
        suffix = f": {detail}" if detail else ""
        raise FetchError(
            f"{' '.join(command)} failed with exit code {exc.returncode}{suffix}"
        ) from exc


def _json_output(command: Sequence[str], runner: Runner) -> Any:
    result = _run(command, runner=runner, capture_output=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FetchError(f"{' '.join(command)} returned invalid JSON") from exc


def _current_branch(runner: Runner) -> str:
    branch = _run(
        ["git", "branch", "--show-current"],
        runner=runner,
        capture_output=True,
    ).stdout.strip()
    if not branch:
        raise FetchError("a checked-out branch or --run-id is required")
    return branch


def _full_commit(revision: str, runner: Runner) -> str:
    # Runs report full commit IDs, so a short ID or a ref is resolved first.
    return _run(
        ["git", "rev-parse", "--verify", f"{revision}^{{commit}}"],
        runner=runner,
        capture_output=True,
    ).stdout.strip()


def _matching_run_id(
    workflow: str,
    branch: str,
    commit: str,
    after_run: int | None,
    runner: Runner,
    event: str | None = None,
) -> str | None:
    payload = _json_output(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            workflow,
            "--limit",
            str(RUN_LIST_LIMIT),
            "--json",
            "databaseId,headBranch,headSha,event",
        ],
        runner,
    )
    if not isinstance(payload, list):
        raise FetchError("gh run list returned a value other than a run list")

    # gh lists runs newest first, so the first match is the newest run of the commit.
    for run in payload:
        if (
            isinstance(run, dict)
            and run.get("headBranch") == branch
            and run.get("headSha") == commit
            and (event is None or run.get("event") == event)
        ):
            run_id = run.get("databaseId")
            if isinstance(run_id, int) or (
                isinstance(run_id, str) and run_id.isdigit()
            ):
                if after_run is None or int(run_id) > after_run:
                    return str(run_id)
    return None


def _run_id_for_commit(
    workflow: str,
    branch: str,
    commit: str,
    *,
    wait_seconds: float,
    runner: Runner,
    after_run: int | None = None,
    event: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    deadline = clock() + wait_seconds
    while True:
        run_id = _matching_run_id(workflow, branch, commit, after_run, runner, event)
        if run_id is not None:
            return run_id
        if clock() >= deadline:
            raise FetchError(
                f"no {workflow} workflow run of commit {commit[:12]} on branch {branch} "
                f"among the latest {RUN_LIST_LIMIT} runs after waiting "
                f"{wait_seconds:g}s; was the commit pushed and the workflow dispatched?"
            )
        print(
            f"Waiting for a {workflow} run of commit {commit[:12]} to be listed...",
            flush=True,
        )
        sleep(POLL_SECONDS)


def _conclusion(run_id: str, runner: Runner) -> str:
    try:
        payload = _json_output(
            ["gh", "run", "view", run_id, "--json", "conclusion"], runner
        )
    except FetchError as exc:
        print(
            f"WARNING: could not read run {run_id} conclusion: {exc}", file=sys.stderr
        )
        return "unknown"

    if isinstance(payload, dict):
        conclusion = payload.get("conclusion")
        if isinstance(conclusion, str) and conclusion:
            return conclusion
    return "unknown"


def _fetch_actions_log(run_id: str, output_dir: Path, runner: Runner) -> bool:
    target = output_dir / "actions.log"
    try:
        with target.open("w", encoding="utf-8") as stream:
            _run(["gh", "run", "view", run_id, "--log"], runner=runner, stdout=stream)
    except (FetchError, OSError) as exc:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        print(
            f"WARNING: could not fetch the Actions log for run {run_id}: {exc}",
            file=sys.stderr,
        )
        return False
    return True


def _fetch_compose_log(
    run_id: str, output_dir: Path, artifact: str, runner: Runner
) -> bool:
    # Each lane uploads the same filename, so preserve its artifact namespace.
    output_dir = output_dir / artifact
    target = output_dir / COMPOSE_LOG
    if target.is_file():
        return True

    try:
        _run(
            [
                "gh",
                "run",
                "download",
                run_id,
                "--name",
                artifact,
                "--dir",
                str(output_dir),
            ],
            runner=runner,
        )
    except FetchError as exc:
        print(
            f"WARNING: run {run_id} has no downloadable {artifact} artifact: {exc}",
            file=sys.stderr,
        )
        return False

    if not target.is_file():
        print(
            f"WARNING: artifact {artifact} did not contain {COMPOSE_LOG}",
            file=sys.stderr,
        )
        return False
    return True


def _fetch_run(
    workflow: str, run_id: str, output_dir: Path, runner: Runner
) -> tuple[str, bool, dict[str, bool]]:
    """Wait for the run to complete and keep its logs in `output_dir`: its
    conclusion, whether its whole log was kept, and whether each artifact's compose
    log was."""
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FetchError(
            f"could not create the log directory {output_dir}: {exc}"
        ) from exc

    print(f"Waiting for {workflow} workflow run {run_id} to complete...", flush=True)
    _run(["gh", "run", "watch", run_id], runner=runner)
    conclusion = _conclusion(run_id, runner)

    actions_log = _fetch_actions_log(run_id, output_dir, runner)
    artifacts = LOG_ARTIFACTS if workflow == DEFAULT_WORKFLOW else ()
    compose_logs = {
        artifact: _fetch_compose_log(run_id, output_dir, artifact, runner)
        for artifact in artifacts
    }
    if not actions_log and not any(compose_logs.values()):
        raise FetchError(f"no logs could be fetched for {workflow} workflow run {run_id}")
    return conclusion, actions_log, compose_logs


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def fetch_evidence(
    commit: str,
    *,
    root: Path = Path("."),
    workflow: str = DEFAULT_WORKFLOW,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    after_run: int | None = None,
    event: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = _utc_now,
    runner: Runner = subprocess.run,
) -> tuple[Path, dict]:
    """Keep the commit's run of `workflow` as its pipeline evidence: the attempt's
    directory, and the summary written there whatever happened."""
    full = _full_commit(commit, runner)
    attempt = now().astimezone(timezone.utc).strftime(ATTEMPT_FORMAT)
    # The summary names each log by its path from the checkout's root.
    kept = EVIDENCE_ROOT / full / EVIDENCE_KIND / attempt
    directory = root / kept
    summary: dict = {"kind": EVIDENCE_KIND, "commit": full, "attempt": attempt,
                     "workflow": workflow, "run": None, "conclusion": None,
                     "passed": False, "actions_log": None, "compose_logs": {},
                     "error": None}
    try:
        run_id = _run_id_for_commit(
            workflow, _current_branch(runner), full, wait_seconds=wait_seconds,
            runner=runner, after_run=after_run, event=event, sleep=sleep, clock=clock)
        summary["run"] = int(run_id)
        conclusion, actions_log, compose_logs = _fetch_run(workflow, run_id, directory,
                                                           runner)
    except FetchError as exc:
        summary["error"] = str(exc)
    else:
        summary.update(
            conclusion=conclusion, passed=conclusion == "success",
            actions_log=str(kept / "actions.log") if actions_log else None,
            compose_logs={artifact: str(kept / artifact / COMPOSE_LOG) if fetched else None
                          for artifact, fetched in compose_logs.items()})
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", "utf-8")
    return directory, summary


def fetch_logs(
    *,
    workflow: str,
    output_root: Path,
    run_id: str | None,
    commit: str | None = None,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    after_run: int | None = None,
    event: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    runner: Runner = subprocess.run,
) -> Path:
    selected_run = run_id or _run_id_for_commit(
        workflow,
        _current_branch(runner),
        _full_commit(commit or "HEAD", runner),
        wait_seconds=wait_seconds,
        runner=runner,
        after_run=after_run,
        event=event,
        sleep=sleep,
        clock=clock,
    )
    output_dir = output_root / selected_run
    conclusion, _, _ = _fetch_run(workflow, selected_run, output_dir, runner)

    print(f"Fetched {workflow} run {selected_run} ({conclusion}) logs into {output_dir}.")
    try:
        archive = shutil.make_archive(
            str(output_dir), "zip", root_dir=output_dir.parent, base_dir=output_dir.name
        )
    except OSError as exc:
        raise FetchError(f"could not create the log archive for {output_dir}: {exc}") from exc
    print(f"Created log archive {archive}.")
    return output_dir


def main(argv: Sequence[str] | None = None, runner: Runner = subprocess.run) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--commit", help="the commit whose run to fetch; local HEAD by default"
    )
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        help="how long to wait for the commit's run to be listed",
    )
    parser.add_argument(
        "--after-run",
        type=int,
        help="consider only runs with a higher ID: the newest run before dispatching",
    )
    parser.add_argument(
        "--event",
        help="consider only runs triggered so, such as workflow_dispatch: a pull "
        "request's run of the same head commit tests a merge, not the commit",
    )
    parser.add_argument(
        "--evidence",
        metavar="COMMIT",
        help="keep the commit's run as validation's pipeline evidence of it, under "
        f"{EVIDENCE_ROOT}/<commit>/{EVIDENCE_KIND}/, in place of --output-dir",
    )
    args = parser.parse_args(argv)
    if args.run_id and (args.commit or args.after_run is not None or args.event):
        parser.error(
            "--run-id names the run; it cannot be combined with --commit, --after-run, "
            "or --event"
        )
    if args.evidence and (args.run_id or args.commit):
        parser.error(
            "--evidence names the commit whose run is kept; it cannot be combined with "
            "--run-id or --commit"
        )

    if args.evidence:
        try:
            directory, summary = fetch_evidence(
                args.evidence.strip(),
                workflow=args.workflow,
                wait_seconds=args.wait_seconds,
                after_run=args.after_run,
                event=args.event,
                runner=runner,
            )
        except FetchError as exc:
            print(f"fetch-e2e-logs: {exc}", file=sys.stderr)
            return 1
        result = (f"run {summary['run']} concluded {summary['conclusion']}"
                  if summary["error"] is None else summary["error"])
        print(f"{EVIDENCE_KIND} evidence for the commit {summary['commit'][:12]}: {result}; "
              f"logs and summary.json: {directory}")
        return 0 if summary["passed"] else 1

    run_id = args.run_id.strip() if args.run_id else None
    try:
        fetch_logs(
            workflow=args.workflow,
            output_root=args.output_dir,
            run_id=run_id,
            commit=args.commit.strip() if args.commit else None,
            wait_seconds=args.wait_seconds,
            after_run=args.after_run,
            event=args.event,
            runner=runner,
        )
    except FetchError as exc:
        print(f"fetch-e2e-logs: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
