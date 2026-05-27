from __future__ import annotations

import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from issue_discovery.config import load_yaml, validate_config


@dataclass(frozen=True)
class CleanRoomStep:
    id: str
    mode: str
    workarounds: tuple[str, ...]
    continue_on_failure: bool
    description: str | None = None


@dataclass(frozen=True)
class CleanRoomSequence:
    id: str
    steps: tuple[CleanRoomStep, ...]
    description: str | None = None


def load_clean_room_sequence(path: Path, sequence_id: str) -> CleanRoomSequence:
    schema_path = path.parents[2] / "schemas" / "clean-room.schema.json"
    if schema_path.exists():
        validate_config(path, schema_path)
    data = load_yaml(path)
    for sequence in data.get("sequences", []):
        if sequence.get("id") == sequence_id:
            return _parse_sequence(sequence)
    raise KeyError(sequence_id)


def render_step_command(step: CleanRoomStep) -> tuple[str, ...]:
    if step.mode == "strict":
        return ("./scripts/issue-discovery", "strict")
    if step.mode == "continue":
        args = ["./scripts/issue-discovery", "continue"]
        for workaround in step.workarounds:
            args.extend(["--with", workaround])
        return tuple(args)
    raise ValueError(f"unsupported clean-room step mode: {step.mode}")


def render_clean_room_script(sequence: CleanRoomSequence) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -u",
        "",
        'status_file="${SCM_CLEAN_ROOM_STATUS_FILE:-.scm-local/clean-room/step-status.tsv}"',
        'mkdir -p "$(dirname "$status_file")"',
        ': > "$status_file"',
        "overall=0",
        "",
        "run_step() {",
        '  step_id="$1"',
        '  continue_on_failure="$2"',
        "  shift 2",
        '  printf \'[clean-room] step %s: %s\\n\' "$step_id" "$*"',
        '  "$@"',
        "  rc=$?",
        '  printf \'%s\\t%s\\n\' "$step_id" "$rc" >> "$status_file"',
        '  if [ "$rc" -ne 0 ]; then',
        "    overall=1",
        '    if [ "$continue_on_failure" != "true" ]; then',
        '      exit "$overall"',
        "    fi",
        "  fi",
        "}",
        "",
    ]
    for step in sequence.steps:
        continue_flag = "true" if step.continue_on_failure else "false"
        args = " ".join(shlex.quote(part) for part in render_step_command(step))
        lines.append(f"run_step {shlex.quote(step.id)} {continue_flag} {args}")
    lines.extend(["", 'exit "$overall"', ""])
    return "\n".join(lines)


def _parse_sequence(raw: dict[str, Any]) -> CleanRoomSequence:
    steps = tuple(_parse_step(step) for step in raw.get("steps", []))
    return CleanRoomSequence(
        id=str(raw["id"]),
        description=raw.get("description"),
        steps=steps,
    )


def _parse_step(raw: dict[str, Any]) -> CleanRoomStep:
    return CleanRoomStep(
        id=str(raw["id"]),
        mode=str(raw["mode"]),
        workarounds=tuple(str(item) for item in raw.get("workarounds", ())),
        continue_on_failure=bool(raw["continue_on_failure"]),
        description=raw.get("description"),
    )
