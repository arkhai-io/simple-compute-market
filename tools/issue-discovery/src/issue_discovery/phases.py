from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from issue_discovery.config import load_yaml


@dataclass(frozen=True)
class CommandSpec:
    id: str
    run: str
    workdir: str = "."
    timeout_seconds: int | None = None


@dataclass(frozen=True)
class PhaseSpec:
    id: str
    name: str
    category: str
    blocking: bool
    commands: tuple[CommandSpec, ...] = ()
    requires: tuple[str, ...] = ()
    always_run: bool = False
    collect_on_failure: tuple[str, ...] = ()
    collect_on_success: tuple[str, ...] = ()
    classifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class PhaseFile:
    schema_version: int
    name: str
    phases: tuple[PhaseSpec, ...] = field(default_factory=tuple)


def load_phase_file(path: Path) -> PhaseFile:
    raw = load_yaml(path)
    phases = tuple(_parse_phase(item) for item in raw.get("phases", []))
    return PhaseFile(
        schema_version=int(raw["schema_version"]),
        name=str(raw["name"]),
        phases=phases,
    )


def _parse_phase(raw: dict[str, Any]) -> PhaseSpec:
    commands = tuple(_parse_command(command) for command in raw.get("commands", []))
    return PhaseSpec(
        id=str(raw["id"]),
        name=str(raw["name"]),
        category=str(raw["category"]),
        blocking=bool(raw.get("blocking", True)),
        commands=commands,
        requires=tuple(raw.get("requires", [])),
        always_run=bool(raw.get("always_run", False)),
        collect_on_failure=tuple(raw.get("collect_on_failure", [])),
        collect_on_success=tuple(raw.get("collect_on_success", [])),
        classifiers=tuple(raw.get("classifiers", [])),
    )


def _parse_command(raw: dict[str, Any]) -> CommandSpec:
    timeout = raw.get("timeout_seconds")
    return CommandSpec(
        id=str(raw["id"]),
        run=str(raw["run"]),
        workdir=str(raw.get("workdir", ".")),
        timeout_seconds=int(timeout) if timeout is not None else None,
    )
