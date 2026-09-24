#!/usr/bin/env python3
"""Wait for a GitHub Actions E2E run and download its diagnostic logs."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import IO, Any, Sequence


DEFAULT_WORKFLOW = "e2e.yml"
DEFAULT_OUTPUT_DIR = Path(".snapshot/e2e-logs")
RUN_LIST_LIMIT = 100
LOG_ARTIFACT = "e2e-logs"
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


def _latest_run_id(workflow: str, branch: str) -> str:
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
            "databaseId,headBranch",
        ]
    )
    if not isinstance(payload, list):
        raise FetchError("gh run list returned a value other than a run list")

    for run in payload:
        if isinstance(run, dict) and run.get("headBranch") == branch:
            run_id = run.get("databaseId")
            if isinstance(run_id, int) or (
                isinstance(run_id, str) and run_id.isdigit()
            ):
                return str(run_id)

    raise FetchError(
        f"no {workflow} workflow run found for branch {branch} "
        f"among the latest {RUN_LIST_LIMIT} runs"
    )


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


def _fetch_compose_log(run_id: str, output_dir: Path) -> bool:
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
                LOG_ARTIFACT,
                "--dir",
                str(output_dir),
            ]
        )
    except FetchError as exc:
        print(
            f"WARNING: run {run_id} has no downloadable {LOG_ARTIFACT} artifact: {exc}",
            file=sys.stderr,
        )
        return False

    if not target.is_file():
        print(
            f"WARNING: artifact {LOG_ARTIFACT} did not contain {COMPOSE_LOG}",
            file=sys.stderr,
        )
        return False
    return True


def fetch_logs(
    *,
    workflow: str,
    output_root: Path,
    run_id: str | None,
) -> Path:
    selected_run = run_id or _latest_run_id(workflow, _current_branch())
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
    compose_log = _fetch_compose_log(selected_run, output_dir)
    if not actions_log and not compose_log:
        raise FetchError(
            f"no logs could be fetched for E2E workflow run {selected_run}"
        )

    print(f"Fetched E2E run {selected_run} ({conclusion}) logs into {output_dir}.")
    return output_dir


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workflow", default=DEFAULT_WORKFLOW)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)

    run_id = args.run_id.strip() if args.run_id else None
    try:
        fetch_logs(
            workflow=args.workflow,
            output_root=args.output_dir,
            run_id=run_id,
        )
    except FetchError as exc:
        print(f"fetch-e2e-logs: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
