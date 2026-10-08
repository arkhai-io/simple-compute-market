#!/usr/bin/env python3
"""Wait for a GitHub Actions E2E run, download its logs, and zip the directory.

Without a run ID, the run is the newest one on the current branch whose head commit
is the commit asked for, local HEAD by default. Matching the commit, not only the
branch, is what makes the fetch safe straight after a dispatch: the new run may not
be listed yet, and the previous, finished run on the branch tested another commit.
A just-dispatched run is waited for, with a bound.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import IO, Any, Callable, Sequence


DEFAULT_WORKFLOW = "e2e.yml"
DEFAULT_OUTPUT_DIR = Path(".snapshot/e2e-logs")
RUN_LIST_LIMIT = 100
DEFAULT_WAIT_SECONDS = 180.0
POLL_SECONDS = 5.0
LOG_ARTIFACTS = ("e2e-vm-logs", "e2e-bare-metal-logs")
COMPOSE_LOG = "compose-logs.txt"


class FetchError(RuntimeError):
    """The requested run or one of its diagnostic logs could not be obtained."""


def _run(
    command: Sequence[str],
    *,
    capture_output: bool = False,
    stdout: IO[str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
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


def _json_output(command: Sequence[str]) -> Any:
    result = _run(command, capture_output=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise FetchError(f"{' '.join(command)} returned invalid JSON") from exc


def _current_branch() -> str:
    branch = _run(
        ["git", "branch", "--show-current"],
        capture_output=True,
    ).stdout.strip()
    if not branch:
        raise FetchError("a checked-out branch or --run-id is required")
    return branch


def _head_commit() -> str:
    return _run(["git", "rev-parse", "HEAD"], capture_output=True).stdout.strip()


def _matching_run_id(workflow: str, branch: str, commit: str) -> str | None:
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
            "databaseId,headBranch,headSha",
        ]
    )
    if not isinstance(payload, list):
        raise FetchError("gh run list returned a value other than a run list")

    # gh lists runs newest first, so the first match is the newest run of the commit.
    for run in payload:
        if (
            isinstance(run, dict)
            and run.get("headBranch") == branch
            and run.get("headSha") == commit
        ):
            run_id = run.get("databaseId")
            if isinstance(run_id, int) or (
                isinstance(run_id, str) and run_id.isdigit()
            ):
                return str(run_id)
    return None


def _run_id_for_commit(
    workflow: str,
    branch: str,
    commit: str,
    *,
    wait_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    deadline = clock() + wait_seconds
    while True:
        run_id = _matching_run_id(workflow, branch, commit)
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


def _conclusion(run_id: str) -> str:
    try:
        payload = _json_output(["gh", "run", "view", run_id, "--json", "conclusion"])
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


def _fetch_actions_log(run_id: str, output_dir: Path) -> bool:
    target = output_dir / "actions.log"
    try:
        with target.open("w", encoding="utf-8") as stream:
            _run(["gh", "run", "view", run_id, "--log"], stdout=stream)
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


def _fetch_compose_log(run_id: str, output_dir: Path, artifact: str) -> bool:
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
            ]
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


def fetch_logs(
    *,
    workflow: str,
    output_root: Path,
    run_id: str | None,
    commit: str | None = None,
    wait_seconds: float = DEFAULT_WAIT_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Path:
    selected_run = run_id or _run_id_for_commit(
        workflow,
        _current_branch(),
        commit or _head_commit(),
        wait_seconds=wait_seconds,
        sleep=sleep,
        clock=clock,
    )
    output_dir = output_root / selected_run
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise FetchError(
            f"could not create E2E log directory {output_dir}: {exc}"
        ) from exc

    print(f"Waiting for E2E workflow run {selected_run} to complete...", flush=True)
    _run(["gh", "run", "watch", selected_run])
    conclusion = _conclusion(selected_run)

    actions_log = _fetch_actions_log(selected_run, output_dir)
    compose_logs = [
        _fetch_compose_log(selected_run, output_dir, artifact)
        for artifact in LOG_ARTIFACTS
    ]
    if not actions_log and not any(compose_logs):
        raise FetchError(
            f"no logs could be fetched for E2E workflow run {selected_run}"
        )

    print(f"Fetched E2E run {selected_run} ({conclusion}) logs into {output_dir}.")
    try:
        archive = shutil.make_archive(
            str(output_dir), "zip", root_dir=output_dir.parent, base_dir=output_dir.name
        )
    except OSError as exc:
        raise FetchError(f"could not create E2E log archive for {output_dir}: {exc}") from exc
    print(f"Created E2E log archive {archive}.")
    return output_dir


def main(argv: Sequence[str] | None = None) -> int:
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
    args = parser.parse_args(argv)

    run_id = args.run_id.strip() if args.run_id else None
    try:
        fetch_logs(
            workflow=args.workflow,
            output_root=args.output_dir,
            run_id=run_id,
            commit=args.commit.strip() if args.commit else None,
            wait_seconds=args.wait_seconds,
        )
    except FetchError as exc:
        print(f"fetch-e2e-logs: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
