from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_CLASSIFIER_PATTERNS = {
    "fixed-docker-name-collision": (
        "anvil",
        "contracts-deploy",
        "market-agent-sell",
        "market-agent-buy",
        "market-agent-alice",
        "market-redis",
        "market-provisioning",
    ),
    "preexisting-compose-stack": (
        "simple-compute-market",
        "bob-storefront",
        "alice-storefront",
        "registry",
        "provisioning",
    ),
    "redis-host-port-conflict": (
        "port is already allocated",
        "bind for 0.0.0.0:6379",
        "0.0.0.0:6379: bind: address already in use",
        "listen tcp 0.0.0.0:6379",
        "listen tcp4 0.0.0.0:6379",
    ),
    "storefront-volume-ownership": (
        "unable to open database file",
        "attempt to write a readonly database",
        "sqlite3.operationalerror",
        "permission denied",
    ),
    "stale-seller-layer-route": (
        'status=404 body={"detail":"not found"}',
        "storefront at http://localhost:8001 not reachable",
        "test_seller.py",
    ),
}


@dataclass(frozen=True)
class IssueCandidate:
    fingerprint: str
    title: str
    labels: tuple[str, ...]
    classification: str
    phase: str
    body_file: Path
    evidence: tuple[str, ...]

    def to_json(self, run_dir: Path) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "title": self.title,
            "labels": list(self.labels),
            "classification": self.classification,
            "phase": self.phase,
            "body_file": str(self.body_file.relative_to(run_dir)),
            "evidence": list(self.evidence),
        }


class IssuePacketGenerator:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir
        self.issue_dir = run_dir / "issue-candidates"

    def generate(self) -> list[IssueCandidate]:
        self.issue_dir.mkdir(parents=True, exist_ok=True)
        manifest = _read_json(self.run_dir / "manifest.json")
        phases = _read_jsonl(self.run_dir / "phases.jsonl")
        collectors = _read_jsonl(self.run_dir / "collectors.jsonl")
        candidates = self._from_failed_phases(manifest, phases, collectors)
        blocking_failure = manifest.get("blocking_failure") or ""
        if not candidates and str(blocking_failure).startswith("workaround:"):
            candidates = [self._from_workaround_failure(manifest)]

        jsonl_path = self.issue_dir / "candidates.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as handle:
            for candidate in candidates:
                handle.write(json.dumps(candidate.to_json(self.run_dir), sort_keys=True) + "\n")
        return candidates

    def _from_failed_phases(
        self,
        manifest: dict[str, Any],
        phases: list[dict[str, Any]],
        collectors: list[dict[str, Any]],
    ) -> list[IssueCandidate]:
        candidates: list[IssueCandidate] = []
        for phase in phases:
            if phase.get("status") != "failed":
                continue
            evidence = _evidence_for_phase(self.run_dir, phase, collectors)
            fingerprints = _fingerprints_for_phase(self.run_dir, phase, evidence)
            for fingerprint in fingerprints:
                body_file = self.issue_dir / f"{fingerprint}.md"
                body_file.write_text(
                    _render_body(
                        manifest=manifest,
                        phase=phase,
                        fingerprint=fingerprint,
                        evidence=evidence,
                    ),
                    encoding="utf-8",
                )
                candidates.append(
                    IssueCandidate(
                        fingerprint=fingerprint,
                        title=_title_for_phase(phase, fingerprint),
                        labels=_labels_for_phase(phase),
                        classification=str(phase.get("category", "unknown")),
                        phase=str(phase["id"]),
                        body_file=body_file,
                        evidence=tuple(evidence),
                    )
                )
        return candidates

    def _from_workaround_failure(self, manifest: dict[str, Any]) -> IssueCandidate:
        raw = str(manifest["blocking_failure"])
        fingerprint = _slug(raw.replace(":", "-"))
        body_file = self.issue_dir / f"{fingerprint}.md"
        body_file.write_text(
            "\n".join(
                [
                    f"# Explicit workaround failed: `{raw}`",
                    "",
                    "## Summary",
                    "An explicit issue-discovery continuation workaround failed before the workflow could continue.",
                    "",
                    "## Reproduction",
                    f"Run `{_reproduction_command(manifest)}`.",
                    "",
                    "## Evidence",
                    f"- Run manifest: `{_rel(manifest_path := self.run_dir / 'manifest.json', self.run_dir)}`",
                    f"- Workaround records: `{_rel(self.run_dir / 'workarounds.jsonl', self.run_dir)}`",
                    "",
                    "## Run Context",
                    f"- Run id: `{manifest.get('run_id')}`",
                    f"- Mode: `{manifest.get('mode')}`",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        return IssueCandidate(
            fingerprint=fingerprint,
            title=f"Explicit issue-discovery workaround failed: {raw}",
            labels=("bug", "local-dev", "issue-discovery"),
            classification="workaround",
            phase=raw,
            body_file=body_file,
            evidence=("manifest.json", "workarounds.jsonl"),
        )


class IssueRepository:
    def __init__(self, run_dir: Path, repo_root: Path | None = None) -> None:
        self.run_dir = run_dir
        self.repo_root = repo_root.resolve() if repo_root is not None else Path.cwd().resolve()
        self.candidates_path = run_dir / "issue-candidates" / "candidates.jsonl"

    def list(self) -> list[dict[str, Any]]:
        if not self.candidates_path.exists():
            IssuePacketGenerator(self.run_dir).generate()
        return _read_jsonl(self.candidates_path)

    def get(self, fingerprint: str) -> dict[str, Any]:
        for candidate in self.list():
            if candidate["fingerprint"] == fingerprint:
                return candidate
        raise KeyError(fingerprint)

    def body_path(self, fingerprint: str) -> Path:
        candidate = self.get(fingerprint)
        return self.run_dir / str(candidate["body_file"])

    def create(self, fingerprint: str, dry_run: bool) -> int:
        candidate = self.get(fingerprint)
        body_path = self.run_dir / str(candidate["body_file"])
        command = [
            "gh",
            "issue",
            "create",
            "--title",
            str(candidate["title"]),
            "--body-file",
            str(body_path),
        ]
        for label in candidate.get("labels", []):
            command.extend(["--label", str(label)])
        if dry_run:
            print(
                f"cd {_shell_quote(str(self.repo_root))} && "
                + " ".join(_shell_quote(part) for part in command)
            )
            return 0
        completed = subprocess.run(command, check=False, text=True, cwd=self.repo_root)
        return completed.returncode


def _render_body(
    *,
    manifest: dict[str, Any],
    phase: dict[str, Any],
    fingerprint: str,
    evidence: list[str],
) -> str:
    failed_commands = _failed_commands_for_phase(phase)
    primary_failed_command = failed_commands[0] if failed_commands else None
    command_records = phase.get("commands") or []
    lines = [
        f"# {_title_for_phase(phase, fingerprint)}",
        "",
        "## Summary",
        f"`{phase['id']}` failed during `{manifest.get('mode')}` issue discovery.",
        "",
        "## Reproduction",
        f"Run `{_reproduction_command(manifest)}`.",
        "",
        "## Expected",
        "The phase completes without blocking the local issue-discovery workflow.",
        "",
        "## Actual",
        f"The phase failed at command `{primary_failed_command}`.",
    ]
    if len(failed_commands) > 1:
        lines.append(
            "Additional failed commands: "
            + ", ".join(f"`{command_id}`" for command_id in failed_commands[1:])
            + "."
        )
    for failed_record in _failed_command_records(command_records, failed_commands):
        lines.extend(
            [
                "",
                f"### Command `{failed_record.get('id')}`",
                f"- Exit code: `{failed_record.get('exit_code')}`",
                f"- Timed out: `{failed_record.get('timed_out')}`",
                f"- Stdout: `{failed_record.get('stdout')}`",
                f"- Stderr: `{failed_record.get('stderr')}`",
                f"- Metadata: `{failed_record.get('meta')}`",
            ]
        )
    lines.extend(["", "## Evidence"])
    for item in evidence:
        lines.append(f"- `{item}`")
    workarounds = _workarounds_for_manifest(manifest)
    if workarounds:
        lines.extend(
            [
                "",
                "## Continuation Context",
                "This run used explicit workaround(s):",
            ]
        )
        for workaround in workarounds:
            lines.append(f"- `{workaround.get('id')}`: {workaround.get('reason')}")
    lines.extend(
        [
            "",
            "## Run Context",
            f"- Run id: `{manifest.get('run_id')}`",
            f"- Mode: `{manifest.get('mode')}`",
            f"- Phase file: `{manifest.get('phase_file')}`",
            f"- Artifact directory: `{manifest.get('output_dir')}`",
            f"- Started: `{manifest.get('started_at')}`",
            f"- Completed: `{manifest.get('completed_at')}`",
            "",
        ]
    )
    return "\n".join(lines)


def _workarounds_for_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    workarounds = manifest.get("workarounds") or []
    if isinstance(workarounds, list) and workarounds:
        return [item for item in workarounds if isinstance(item, dict)]
    workaround = manifest.get("workaround")
    return [workaround] if isinstance(workaround, dict) else []


def _fingerprints_for_phase(run_dir: Path, phase: dict[str, Any], evidence: list[str]) -> list[str]:
    evidence_text = _evidence_text(run_dir, evidence)
    fingerprints = []
    for classifier in phase.get("classifiers") or []:
        fingerprint = _slug(str(classifier))
        if _classifier_matches(fingerprint, evidence_text):
            fingerprints.append(fingerprint)
    if fingerprints:
        return sorted(dict.fromkeys(fingerprints))
    return [_generic_fingerprint_for_phase(phase)]


def _generic_fingerprint_for_phase(phase: dict[str, Any]) -> str:
    failed_commands = _failed_commands_for_phase(phase)
    failed_command = failed_commands[0] if failed_commands else "failure"
    return _slug(f"{phase['id']}-{failed_command}")


def _classifier_matches(fingerprint: str, evidence_text: str) -> bool:
    patterns = _CLASSIFIER_PATTERNS.get(fingerprint, ())
    return any(pattern in evidence_text for pattern in patterns)


def _evidence_text(run_dir: Path, evidence: list[str]) -> str:
    chunks = []
    for item in evidence:
        path = run_dir / item
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks).lower()


def _failed_commands_for_phase(phase: dict[str, Any]) -> list[str]:
    failed_commands = phase.get("failed_commands") or []
    if failed_commands:
        return [str(command_id) for command_id in failed_commands]
    failed_command = phase.get("failed_command")
    return [str(failed_command)] if failed_command else []


def _failed_command_records(
    command_records: list[dict[str, Any]],
    failed_commands: list[str],
) -> list[dict[str, Any]]:
    failed = set(failed_commands)
    return [record for record in command_records if str(record.get("id")) in failed]


def _evidence_for_phase(
    run_dir: Path,
    phase: dict[str, Any],
    collectors: list[dict[str, Any]],
) -> list[str]:
    evidence = ["manifest.json", "phases.jsonl"]
    for command in phase.get("commands") or []:
        if command.get("stdout"):
            evidence.append(str(command["stdout"]))
        if command.get("stderr"):
            evidence.append(str(command["stderr"]))
        if command.get("meta"):
            evidence.append(str(command["meta"]))
    reason = f"phase_failed:{phase['id']}"
    for collector in collectors:
        if collector.get("reason") == reason:
            if collector.get("output"):
                evidence.append(str(collector["output"]))
            if collector.get("stderr"):
                evidence.append(str(collector["stderr"]))
    return sorted(dict.fromkeys(item for item in evidence if (run_dir / item).exists()))


def _title_for_phase(phase: dict[str, Any], fingerprint: str) -> str:
    return f"{phase.get('name', phase['id'])} failed ({fingerprint})"


def _labels_for_phase(phase: dict[str, Any]) -> tuple[str, ...]:
    labels = ["bug", "local-dev", "issue-discovery"]
    category = phase.get("category")
    if category:
        labels.append(str(category).replace("_", "-"))
    return tuple(labels)


def _reproduction_command(manifest: dict[str, Any]) -> str:
    mode = str(manifest.get("mode", "strict"))
    if mode == "strict":
        return "./scripts/issue-discovery strict"
    if mode == "continue":
        workaround = (manifest.get("workaround") or {}).get("id")
        return f"./scripts/issue-discovery continue --with {workaround}"
    if mode.startswith("profile:"):
        return f"./scripts/issue-discovery profile {mode.split(':', 1)[1]}"
    return f"./scripts/issue-discovery {mode}"


def _slug(value: str) -> str:
    allowed = []
    previous_dash = False
    for character in value.lower():
        if character.isalnum():
            allowed.append(character)
            previous_dash = False
        elif not previous_dash:
            allowed.append("-")
            previous_dash = True
    return "".join(allowed).strip("-") or "failure"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _shell_quote(value: str) -> str:
    if value.replace("-", "").replace("_", "").replace("/", "").replace(".", "").isalnum():
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"
