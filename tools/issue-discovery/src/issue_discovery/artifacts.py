from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")


def make_run_id() -> str:
    stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


@dataclass
class ArtifactStore:
    run_dir: Path
    run_id: str
    phases_jsonl: Path = field(init=False)
    commands_dir: Path = field(init=False)

    @classmethod
    def create(cls, output_root: Path, run_id: str | None = None) -> ArtifactStore:
        actual_run_id = run_id or make_run_id()
        run_dir = output_root / actual_run_id
        store = cls(run_dir=run_dir, run_id=actual_run_id)
        store.run_dir.mkdir(parents=True, exist_ok=False)
        store.commands_dir.mkdir(parents=True, exist_ok=True)
        (store.run_dir / "context").mkdir(parents=True, exist_ok=True)
        return store

    @classmethod
    def use_exact_dir(cls, run_dir: Path, run_id: str | None = None) -> ArtifactStore:
        actual_run_id = run_id or run_dir.name
        store = cls(run_dir=run_dir, run_id=actual_run_id)
        if store.run_dir.exists() and any(store.run_dir.iterdir()):
            raise FileExistsError(
                f"output directory already exists and is not empty: {store.run_dir}"
            )
        store.run_dir.mkdir(parents=True, exist_ok=True)
        store.commands_dir.mkdir(parents=True, exist_ok=True)
        (store.run_dir / "context").mkdir(parents=True, exist_ok=True)
        return store

    def __post_init__(self) -> None:
        self.phases_jsonl = self.run_dir / "phases.jsonl"
        self.commands_dir = self.run_dir / "commands"

    def path(self, relative: str | Path) -> Path:
        destination = self.run_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        return destination

    def write_text(self, relative: str | Path, content: str) -> Path:
        destination = self.path(relative)
        destination.write_text(content, encoding="utf-8")
        return destination

    def write_json(self, relative: str | Path, value: dict[str, Any]) -> Path:
        destination = self.path(relative)
        destination.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def append_jsonl(self, relative: str | Path, value: dict[str, Any]) -> Path:
        destination = self.path(relative)
        with destination.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(value, sort_keys=True) + "\n")
        return destination
