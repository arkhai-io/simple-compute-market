from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from issue_discovery.artifacts import ArtifactStore, utc_now_iso
from issue_discovery.commands import run_shell_command
from issue_discovery.config import load_yaml
from issue_discovery.redaction import Redactor


@dataclass(frozen=True)
class CollectorSpec:
    id: str
    command: str
    output: Path
    description: str = ""
    redact: bool = False


def load_collectors(path: Path) -> dict[str, CollectorSpec]:
    raw = load_yaml(path)
    collectors: dict[str, CollectorSpec] = {}
    for item in raw.get("collectors", []):
        spec = CollectorSpec(
            id=str(item["id"]),
            command=str(item["command"]),
            output=Path(str(item["output"])),
            description=str(item.get("description", "")),
            redact=bool(item.get("redact", False)),
        )
        collectors[spec.id] = spec
    return collectors


class CollectorRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        store: ArtifactStore,
        collectors: dict[str, CollectorSpec],
        redactor: Redactor,
        env: dict[str, str] | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.store = store
        self.collectors = collectors
        self.redactor = redactor
        self.env = env or {}

    def collect_many(self, ids: tuple[str, ...] | list[str], reason: str) -> list[dict[str, Any]]:
        records = []
        for collector_id in ids:
            records.append(self.collect(collector_id, reason))
        return records

    def collect(self, collector_id: str, reason: str) -> dict[str, Any]:
        spec = self.collectors.get(collector_id)
        if spec is None:
            record = {
                "id": collector_id,
                "reason": reason,
                "status": "missing",
                "collected_at": utc_now_iso(),
            }
            self.store.append_jsonl("collectors.jsonl", record)
            return record

        result = run_shell_command(
            command_id=spec.id,
            command=spec.command,
            cwd=self.repo_root,
            output_dir=self.store.path("commands/collectors"),
            env=self.env,
            redactor=self.redactor if spec.redact else Redactor(),
        )
        output_text = result.stdout_path.read_text(encoding="utf-8")
        output_path = self.store.write_text(spec.output, output_text)
        record = {
            "id": spec.id,
            "description": spec.description,
            "reason": reason,
            "status": "passed" if result.ok else "failed",
            "exit_code": result.exit_code,
            "timed_out": result.timed_out,
            "output": str(output_path.relative_to(self.store.run_dir)),
            "stderr": str(result.stderr_path.relative_to(self.store.run_dir)),
            "collected_at": utc_now_iso(),
        }
        self.store.append_jsonl("collectors.jsonl", record)
        return record
