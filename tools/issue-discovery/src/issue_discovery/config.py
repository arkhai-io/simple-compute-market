from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator


@dataclass(frozen=True)
class ToolPaths:
    repo_root: Path

    @property
    def tool_root(self) -> Path:
        return self.repo_root / "tools" / "issue-discovery"

    @property
    def config_dir(self) -> Path:
        return self.tool_root / "config"

    @property
    def schema_dir(self) -> Path:
        return self.tool_root / "schemas"

    @property
    def template_dir(self) -> Path:
        return self.tool_root / "templates"

    @property
    def default_output_root(self) -> Path:
        return self.repo_root / ".scm-local" / "issue-discovery" / "runs"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return loaded


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return loaded


def validate_config(config_path: Path, schema_path: Path) -> None:
    schema = load_json(schema_path)
    data = load_yaml(config_path)
    Draft202012Validator(schema).validate(data)
