from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from issue_discovery.config import load_yaml
from issue_discovery.phases import CommandSpec


@dataclass(frozen=True)
class WorkaroundSpec:
    id: str
    status: str
    reason: str
    removal_condition: str
    issue: str | None = None
    start_phase: str | None = None
    commands: tuple[CommandSpec, ...] = ()
    skip_phases: tuple[str, ...] = ()
    env: dict[str, str] | None = None


def load_workarounds(path: Path) -> dict[str, WorkaroundSpec]:
    raw = load_yaml(path)
    workarounds: dict[str, WorkaroundSpec] = {}
    for item in raw.get("workarounds", []):
        spec = _parse_workaround(item)
        workarounds[spec.id] = spec
    return workarounds


def _parse_workaround(raw: dict[str, Any]) -> WorkaroundSpec:
    commands = tuple(
        CommandSpec(
            id=str(item["id"]),
            run=str(item["run"]),
            workdir=str(item.get("workdir", ".")),
            timeout_seconds=int(item["timeout_seconds"]) if item.get("timeout_seconds") is not None else None,
        )
        for item in raw.get("commands", [])
    )
    issue = raw.get("issue")
    env = raw.get("env")
    return WorkaroundSpec(
        id=str(raw["id"]),
        status=str(raw["status"]),
        reason=str(raw["reason"]),
        removal_condition=str(raw["removal_condition"]),
        issue=str(issue) if issue is not None else None,
        start_phase=str(raw["start_phase"]) if raw.get("start_phase") is not None else None,
        commands=commands,
        skip_phases=tuple(raw.get("skip_phases", [])),
        env={str(key): str(value) for key, value in env.items()} if isinstance(env, dict) else None,
    )
