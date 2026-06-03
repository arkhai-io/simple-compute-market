from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from issue_discovery.artifacts import utc_now
from issue_discovery.redaction import Redactor


@dataclass(frozen=True)
class CommandResult:
    id: str
    command: str
    cwd: Path
    started_at: str
    completed_at: str
    duration_seconds: float
    exit_code: int
    timed_out: bool
    stdout_path: Path
    stderr_path: Path
    meta_path: Path

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out

    def to_json(self, run_dir: Path) -> dict[str, object]:
        return {
            "id": self.id,
            "command": self.command,
            "cwd": str(self.cwd),
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "stdout": str(self.stdout_path.relative_to(run_dir)),
            "stderr": str(self.stderr_path.relative_to(run_dir)),
            "meta": str(self.meta_path.relative_to(run_dir)),
        }


def run_shell_command(
    *,
    command_id: str,
    command: str,
    cwd: Path,
    output_dir: Path,
    env: dict[str, str] | None = None,
    timeout_seconds: int | None = None,
    redactor: Redactor | None = None,
) -> CommandResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    started = utc_now()
    stdout = ""
    stderr = ""
    exit_code = 0
    timed_out = False
    actual_env = os.environ.copy()
    if env:
        actual_env.update(env)

    try:
        completed = subprocess.run(
            ["bash", "-lc", command],
            cwd=cwd,
            env=actual_env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        stdout = _coerce_output(exc.stdout)
        stderr = _coerce_output(exc.stderr)
        stderr = f"{stderr}\nCommand timed out after {timeout_seconds} seconds.\n"
        exit_code = 124
        timed_out = True
    except FileNotFoundError as exc:
        stderr = f"{exc}\n"
        exit_code = 127

    completed_at = utc_now()
    redactor = redactor or Redactor()
    stdout = redactor.redact(stdout)
    stderr = redactor.redact(stderr)

    stdout_path = output_dir / f"{command_id}.stdout.txt"
    stderr_path = output_dir / f"{command_id}.stderr.txt"
    meta_path = output_dir / f"{command_id}.meta.json"
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")

    result = CommandResult(
        id=command_id,
        command=redactor.redact(command),
        cwd=cwd,
        started_at=started.isoformat(timespec="seconds").replace("+00:00", "Z"),
        completed_at=completed_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        duration_seconds=round((completed_at - started).total_seconds(), 3),
        exit_code=exit_code,
        timed_out=timed_out,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        meta_path=meta_path,
    )
    meta_path.write_text(
        _json_dumps(
            {
                "id": result.id,
                "command": result.command,
                "cwd": str(result.cwd),
                "started_at": result.started_at,
                "completed_at": result.completed_at,
                "duration_seconds": result.duration_seconds,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
            }
        ),
        encoding="utf-8",
    )
    return result


def _coerce_output(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _json_dumps(value: dict[str, object]) -> str:
    import json

    return json.dumps(value, indent=2, sort_keys=True) + "\n"
