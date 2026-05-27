from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from issue_discovery.artifacts import ArtifactStore, utc_now_iso
from issue_discovery.collectors import CollectorRunner, load_collectors
from issue_discovery.commands import CommandResult, run_shell_command
from issue_discovery.config import ToolPaths, load_yaml
from issue_discovery.issues import IssuePacketGenerator, IssueRepository
from issue_discovery.phases import CommandSpec, PhaseFile, PhaseSpec, load_phase_file
from issue_discovery.redaction import Redactor
from issue_discovery.workarounds import WorkaroundSpec, load_workarounds


@dataclass
class RunState:
    phase_status: dict[str, str] = field(default_factory=dict)
    failed_phases: list[str] = field(default_factory=list)
    skipped_phases: list[str] = field(default_factory=list)
    blocking_failure: str | None = None

    @property
    def failed(self) -> bool:
        return bool(self.failed_phases or self.blocking_failure)


class DiscoveryRunner:
    def __init__(self, repo_root: Path, output_dir: Path | None = None, dry_run: bool = False) -> None:
        self.repo_root = repo_root.resolve()
        self.output_dir = output_dir.resolve() if output_dir is not None else None
        self.dry_run = dry_run
        self.paths = ToolPaths(self.repo_root)

    def run_strict(self) -> int:
        phase_path = self.paths.config_dir / "phases" / "local.yaml"
        return self._run_phase_file(
            mode="strict",
            phase_path=phase_path,
            selected_phase_ids=None,
            workaround=None,
        )

    def run_continue(self, workaround: str) -> int:
        workarounds = load_workarounds(self.paths.config_dir / "workarounds.yaml")
        spec = workarounds.get(workaround)
        if spec is None:
            print(f"unknown workaround: {workaround}")
            print("available workarounds:")
            for key in sorted(workarounds):
                print(f"  - {key}")
            return 2
        phase_path = self.paths.config_dir / "phases" / "local.yaml"
        return self._run_phase_file(
            mode="continue",
            phase_path=phase_path,
            selected_phase_ids=None,
            workaround=spec,
        )

    def run_profile(self, name: str) -> int:
        profiles = load_yaml(self.paths.config_dir / "profiles.yaml").get("profiles", [])
        selected = next((item for item in profiles if item.get("id") == name), None)
        if selected is None:
            print(f"unknown profile: {name}")
            print("available profiles:")
            for item in profiles:
                print(f"  - {item['id']}")
            return 2
        phase_path = self.paths.config_dir / str(selected["phase_file"])
        phase_ids = tuple(str(item) for item in selected.get("phases", []))
        return self._run_phase_file(
            mode=f"profile:{name}",
            phase_path=phase_path,
            selected_phase_ids=phase_ids,
            workaround=None,
        )

    def issue_list(self, run_dir: Path) -> int:
        repository = IssueRepository(run_dir.resolve())
        for candidate in repository.list():
            labels = ",".join(candidate.get("labels", []))
            print(
                f"{candidate['fingerprint']}\t{candidate['classification']}\t"
                f"{candidate['phase']}\t{labels}\t{candidate['title']}"
            )
        return 0

    def issue_show(self, run_dir: Path, fingerprint: str) -> int:
        repository = IssueRepository(run_dir.resolve())
        body_path = repository.body_path(fingerprint)
        print(body_path.read_text(encoding="utf-8"), end="")
        return 0

    def issue_create(self, run_dir: Path, fingerprint: str, dry_run: bool) -> int:
        repository = IssueRepository(run_dir.resolve())
        return repository.create(fingerprint, dry_run=dry_run)

    def _run_phase_file(
        self,
        *,
        mode: str,
        phase_path: Path,
        selected_phase_ids: tuple[str, ...] | None,
        workaround: WorkaroundSpec | None,
    ) -> int:
        phase_file = load_phase_file(phase_path)
        phases = _select_phases(phase_file, selected_phase_ids)
        env = workaround.env if workaround and workaround.env else {}
        skip_phases = set(workaround.skip_phases if workaround else ())

        if self.dry_run:
            self._print_plan(mode, phase_path, phases, workaround, skip_phases)
            return 0

        store = self._create_store()
        redactor = Redactor.from_file(self.paths.config_dir / "redactions.yaml")
        collectors = CollectorRunner(
            repo_root=self.repo_root,
            store=store,
            collectors=load_collectors(self.paths.config_dir / "collectors.yaml"),
            redactor=redactor,
            env=env,
        )
        manifest = {
            "schema_version": 1,
            "run_id": store.run_id,
            "mode": mode,
            "status": "running",
            "repo_root": str(self.repo_root),
            "phase_file": self._display_path(phase_path),
            "selected_phases": [phase.id for phase in phases],
            "workaround": _workaround_json(workaround),
            "output_dir": str(store.run_dir),
            "started_at": utc_now_iso(),
        }
        store.write_json("manifest.json", redactor.redact_mapping(manifest))
        print(f"issue-discovery run: {store.run_id}")
        print(f"artifacts: {store.run_dir}")

        collectors.collect_many(["git_status", "tool_versions"], reason="run_start")

        state = RunState()
        if workaround is not None and not self._apply_workaround(workaround, store, redactor, env):
            state.blocking_failure = f"workaround:{workaround.id}"
        else:
            self._run_phases(phases, store, redactor, collectors, state, env, skip_phases)

        status = "failed" if state.failed else "passed"
        manifest.update(
            {
                "status": status,
                "completed_at": utc_now_iso(),
                "failed_phases": state.failed_phases,
                "skipped_phases": state.skipped_phases,
                "blocking_failure": state.blocking_failure,
            }
        )
        store.write_json("manifest.json", redactor.redact_mapping(manifest))
        candidates = IssuePacketGenerator(store.run_dir).generate()
        print(f"issue candidates: {len(candidates)}")
        print(f"status: {status}")
        return 1 if state.failed else 0

    def _run_phases(
        self,
        phases: tuple[PhaseSpec, ...],
        store: ArtifactStore,
        redactor: Redactor,
        collectors: CollectorRunner,
        state: RunState,
        env: dict[str, str],
        skip_phases: set[str],
    ) -> None:
        normal_phases = tuple(phase for phase in phases if not phase.always_run)
        always_phases = tuple(phase for phase in phases if phase.always_run)

        for phase in normal_phases:
            if state.blocking_failure is not None:
                self._record_skip(store, state, phase, "blocked")
                continue
            self._run_one_phase(phase, store, redactor, collectors, state, env, skip_phases)

        for phase in always_phases:
            self._run_one_phase(phase, store, redactor, collectors, state, env, set())

    def _run_one_phase(
        self,
        phase: PhaseSpec,
        store: ArtifactStore,
        redactor: Redactor,
        collectors: CollectorRunner,
        state: RunState,
        env: dict[str, str],
        skip_phases: set[str],
    ) -> None:
        if phase.id in skip_phases:
            self._record_skip(store, state, phase, "workaround_skip")
            return
        missing = [required for required in phase.requires if state.phase_status.get(required) != "passed"]
        if missing and not phase.always_run:
            self._record_skip(store, state, phase, "dependency_not_passed", {"missing": missing})
            return

        print(f"phase: {phase.id}")
        command_results: list[CommandResult] = []
        failed_command: CommandResult | None = None
        started_at = utc_now_iso()
        for command in phase.commands:
            result = self._run_command(store, redactor, phase.id, command, env)
            command_results.append(result)
            if not result.ok:
                failed_command = result
                break

        status = "failed" if failed_command else "passed"
        state.phase_status[phase.id] = status
        if status == "failed":
            state.failed_phases.append(phase.id)
            collectors.collect_many(phase.collect_on_failure, reason=f"phase_failed:{phase.id}")
            if phase.blocking and not phase.always_run:
                state.blocking_failure = phase.id
        else:
            collectors.collect_many(phase.collect_on_success, reason=f"phase_passed:{phase.id}")

        record = {
            "id": phase.id,
            "name": phase.name,
            "category": phase.category,
            "blocking": phase.blocking,
            "status": status,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "commands": [result.to_json(store.run_dir) for result in command_results],
            "failed_command": failed_command.id if failed_command else None,
            "classifiers": phase.classifiers if status == "failed" else (),
        }
        store.append_jsonl("phases.jsonl", redactor.redact_mapping(record))

    def _run_command(
        self,
        store: ArtifactStore,
        redactor: Redactor,
        phase_id: str,
        command: CommandSpec,
        env: dict[str, str],
    ) -> CommandResult:
        cwd = (self.repo_root / command.workdir).resolve()
        return run_shell_command(
            command_id=command.id,
            command=command.run,
            cwd=cwd,
            output_dir=store.path("commands") / phase_id,
            env=env,
            timeout_seconds=command.timeout_seconds,
            redactor=redactor,
        )

    def _apply_workaround(
        self,
        workaround: WorkaroundSpec,
        store: ArtifactStore,
        redactor: Redactor,
        env: dict[str, str],
    ) -> bool:
        print(f"workaround: {workaround.id}")
        results = []
        ok = True
        for command in workaround.commands:
            result = self._run_command(store, redactor, f"workaround_{workaround.id}", command, env)
            results.append(result.to_json(store.run_dir))
            ok = ok and result.ok
            if not result.ok:
                break
        store.append_jsonl(
            "workarounds.jsonl",
            redactor.redact_mapping(
                {
                    "id": workaround.id,
                    "status": "passed" if ok else "failed",
                    "reason": workaround.reason,
                    "removal_condition": workaround.removal_condition,
                    "commands": results,
                    "env": env,
                    "skip_phases": workaround.skip_phases,
                    "completed_at": utc_now_iso(),
                }
            ),
        )
        return ok

    def _record_skip(
        self,
        store: ArtifactStore,
        state: RunState,
        phase: PhaseSpec,
        reason: str,
        extra: dict[str, Any] | None = None,
    ) -> None:
        state.phase_status[phase.id] = "skipped"
        state.skipped_phases.append(phase.id)
        record: dict[str, Any] = {
            "id": phase.id,
            "name": phase.name,
            "category": phase.category,
            "blocking": phase.blocking,
            "status": "skipped",
            "reason": reason,
            "commands": [],
            "completed_at": utc_now_iso(),
        }
        if extra:
            record.update(extra)
        store.append_jsonl("phases.jsonl", record)

    def _create_store(self) -> ArtifactStore:
        if self.output_dir is not None:
            return ArtifactStore.use_exact_dir(self.output_dir)
        return ArtifactStore.create(self.paths.default_output_root)

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.paths.config_dir))
        except ValueError:
            return str(path)

    def _print_plan(
        self,
        mode: str,
        phase_path: Path,
        phases: tuple[PhaseSpec, ...],
        workaround: WorkaroundSpec | None,
        skip_phases: set[str],
    ) -> None:
        output = self.output_dir if self.output_dir is not None else self.paths.default_output_root
        print(f"issue-discovery command: {mode}")
        print(f"repo_root: {self.repo_root}")
        print(f"output: {output}")
        print("dry_run: yes")
        print(f"phase_file: {phase_path}")
        if workaround is not None:
            print(f"workaround: {workaround.id}")
        print("phases:")
        for phase in phases:
            suffix = " (skipped by workaround)" if phase.id in skip_phases else ""
            print(f"  - {phase.id}{suffix}")

    def _print_pending(self, command: str) -> None:
        output = self.output_dir if self.output_dir is not None else self.paths.default_output_root
        dry_run = "yes" if self.dry_run else "no"
        print(f"issue-discovery command: {command}")
        print(f"repo_root: {self.repo_root}")
        print(f"output: {output}")
        print(f"dry_run: {dry_run}")


def _select_phases(phase_file: PhaseFile, selected_phase_ids: tuple[str, ...] | None) -> tuple[PhaseSpec, ...]:
    if selected_phase_ids is None:
        return phase_file.phases
    by_id = {phase.id: phase for phase in phase_file.phases}
    missing = [phase_id for phase_id in selected_phase_ids if phase_id not in by_id]
    if missing:
        raise ValueError(f"unknown phase ids in {phase_file.name}: {', '.join(missing)}")
    included: set[str] = set()
    visiting: set[str] = set()

    def include_with_dependencies(phase_id: str) -> None:
        if phase_id in included:
            return
        if phase_id in visiting:
            raise ValueError(f"cyclic phase dependency in {phase_file.name}: {phase_id}")
        phase = by_id.get(phase_id)
        if phase is None:
            raise ValueError(f"unknown required phase id in {phase_file.name}: {phase_id}")
        visiting.add(phase_id)
        for required in phase.requires:
            include_with_dependencies(required)
        visiting.remove(phase_id)
        included.add(phase_id)

    for phase_id in selected_phase_ids:
        include_with_dependencies(phase_id)

    return tuple(phase for phase in phase_file.phases if phase.id in included)


def _workaround_json(workaround: WorkaroundSpec | None) -> dict[str, Any] | None:
    if workaround is None:
        return None
    return {
        "id": workaround.id,
        "status": workaround.status,
        "issue": workaround.issue,
        "reason": workaround.reason,
        "removal_condition": workaround.removal_condition,
        "skip_phases": workaround.skip_phases,
        "env": workaround.env or {},
    }
