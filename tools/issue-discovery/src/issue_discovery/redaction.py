from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from issue_discovery.config import load_yaml


@dataclass(frozen=True)
class RedactionRule:
    id: str
    pattern: re.Pattern[str]
    replacement: str


class Redactor:
    def __init__(self, rules: tuple[RedactionRule, ...] = ()) -> None:
        self._rules = rules

    @classmethod
    def from_file(cls, path: Path) -> Redactor:
        raw = load_yaml(path)
        rules = []
        for item in raw.get("patterns", []):
            rules.append(
                RedactionRule(
                    id=str(item["id"]),
                    pattern=re.compile(str(item["regex"])),
                    replacement=str(item["replacement"]),
                )
            )
        return cls(tuple(rules))

    def redact(self, value: str) -> str:
        redacted = value
        for rule in self._rules:
            redacted = rule.pattern.sub(rule.replacement, redacted)
        return redacted

    def redact_mapping(self, value: dict[str, Any]) -> dict[str, Any]:
        return {key: self._redact_value(item) for key, item in value.items()}

    def _redact_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact(value)
        if isinstance(value, dict):
            return self.redact_mapping(value)
        if isinstance(value, list):
            return [self._redact_value(item) for item in value]
        return value
