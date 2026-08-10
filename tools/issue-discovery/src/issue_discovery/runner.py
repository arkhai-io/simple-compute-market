from __future__ import annotations

import hashlib
import json
import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from issue_discovery.artifacts import ArtifactStore, utc_now_iso
from issue_discovery.clean_room import (
    CleanRoomSequence,
    load_clean_room_sequence,
    render_clean_room_script,
    render_step_command,
)
from issue_discovery.collectors import CollectorRunner, load_collectors
from issue_discovery.commands import CommandResult, run_shell_command
from issue_discovery.config import ToolPaths, load_yaml
from issue_discovery.capacity import (
    CapacityInputError,
    CapacityValidationError,
    evaluate_capacity_result,
    load_json_text,
    scenario_sha256,
    validate_cancellation_receipt,
    validate_capacity_result,
    validate_cleanup_receipt,
    validate_finding,
    validate_public_capacity_branch,
    validate_public_capacity_data,
    validate_scenario_file,
)
from issue_discovery.issues import (
    CapacityIssuePlanError,
    IssuePacketGenerator,
    IssueRepository,
    plan_capacity_fix_candidate,
    plan_capacity_issues,
)
from issue_discovery.phases import CommandSpec, PhaseFile, PhaseSpec, load_phase_file
from issue_discovery.redaction import Redactor
from issue_discovery.workarounds import WorkaroundSpec, load_workarounds


_CAPACITY_PUBLIC_REPOSITORY = "arkhai-io/simple-compute-market"
_CAPACITY_ADAPTER_KINDS = frozenset(
    {"market", "wallet", "cloud", "host", "provisioning", "github-mutation"}
)
_CAPACITY_ADAPTER_MODES = frozenset({"mock", "fake", "dry-run"})
_CAPACITY_TERMINATIONS = frozenset(
    {
        "completed",
        "timeout",
        "cancelled",
        "partial-launch",
        "role-failure",
        "controller-failure",
    }
)
_CAPACITY_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_CAPACITY_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,119}$")


class CapacityCommandError(ValueError):
    def __init__(self, code: str, *, exit_code: int = 2) -> None:
        super().__init__(code)
        self.code = code
        self.exit_code = exit_code


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
    def __init__(
        self, repo_root: Path, output_dir: Path | None = None, dry_run: bool = False
    ) -> None:
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

    def run_continue(self, workaround_ids: tuple[str, ...]) -> int:
        if not workaround_ids:
            print("at least one workaround is required")
            return 2
        available = load_workarounds(self.paths.config_dir / "workarounds.yaml")
        missing = [
            workaround_id
            for workaround_id in workaround_ids
            if workaround_id not in available
        ]
        if missing:
            print(f"unknown workaround: {', '.join(missing)}")
            print("available workarounds:")
            for key in sorted(available):
                print(f"  - {key}")
            return 2
        specs = tuple(available[workaround_id] for workaround_id in workaround_ids)
        phase_path = self.paths.config_dir / "phases" / "local.yaml"
        return self._run_phase_file(
            mode="continue",
            phase_path=phase_path,
            selected_phase_ids=None,
            workaround=specs,
        )

    def run_profile(self, name: str) -> int:
        profiles = load_yaml(self.paths.config_dir / "profiles.yaml").get(
            "profiles", []
        )
        selected = next((item for item in profiles if item.get("id") == name), None)
        if selected is None:
            print(f"unknown profile: {name}")
            print("available profiles:")
            for item in profiles:
                print(f"  - {item['id']}")
            return 2
        phase_path = self.paths.config_dir / str(selected["phase_file"])
        phase_ids = tuple(str(item) for item in selected.get("phases", []))
        profile_env = {
            str(key): str(value) for key, value in (selected.get("env") or {}).items()
        }
        return self._run_phase_file(
            mode=f"profile:{name}",
            phase_path=phase_path,
            selected_phase_ids=phase_ids,
            workaround=None,
            profile_env=profile_env,
        )

    def issue_list(self, run_dir: Path) -> int:
        repository = IssueRepository(run_dir.resolve(), repo_root=self.repo_root)
        for candidate in repository.list():
            labels = ",".join(candidate.get("labels", []))
            print(
                f"{candidate['fingerprint']}\t{candidate.get('state', 'unknown')}\t"
                f"{candidate['classification']}\t"
                f"{candidate['phase']}\t{labels}\t{candidate['title']}"
            )
        return 0

    def issue_show(self, run_dir: Path, fingerprint: str) -> int:
        repository = IssueRepository(run_dir.resolve(), repo_root=self.repo_root)
        body_path = repository.body_path(fingerprint)
        print(body_path.read_text(encoding="utf-8"), end="")
        return 0

    def issue_create(
        self, run_dir: Path, fingerprint: str, dry_run: bool, force: bool = False
    ) -> int:
        repository = IssueRepository(run_dir.resolve(), repo_root=self.repo_root)
        return repository.create(fingerprint, dry_run=dry_run, force=force)

    def capacity_validate(self, scenario: Path) -> int:
        def operation() -> tuple[dict[str, Any], dict[str, Any], str, int]:
            value = validate_scenario_file(scenario, self.repo_root)
            context = {"scenario": _capacity_scenario_identity(value)}
            return context, {"valid": True}, "ok", 0

        return self._capacity_dispatch("capacity.validate", operation)

    def capacity_hash(self, scenario: Path) -> int:
        def operation() -> tuple[dict[str, Any], dict[str, Any], str, int]:
            value = validate_scenario_file(scenario, self.repo_root)
            identity = _capacity_scenario_identity(value)
            return {"scenario": identity}, {"sha256": identity["sha256"]}, "ok", 0

        return self._capacity_dispatch("capacity.hash", operation)

    def capacity_evaluate(
        self,
        scenario: Path,
        result: Path,
        *,
        repository: str,
        branch: str,
        sha: str,
        run_id: str,
        timeout_seconds: int,
        adapters: tuple[str, ...],
    ) -> int:
        def operation() -> tuple[dict[str, Any], dict[str, Any], str, int]:
            context = _capacity_context(
                repo_root=self.repo_root,
                repository=repository,
                branch=branch,
                sha=sha,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
                adapters=adapters,
            )
            scenario_value = validate_scenario_file(scenario, self.repo_root)
            context = _capacity_context_with_scenario(context, scenario_value)
            result_value = _capacity_read_object(result)
            validate_capacity_result(result_value, scenario_value, self.repo_root)
            _require_capacity_result_context(result_value, context)
            evaluation = evaluate_capacity_result(
                scenario_value,
                result_value,
                self.repo_root,
            )
            has_findings = bool(evaluation["findings"])
            return (
                context,
                evaluation,
                "findings" if has_findings else "ok",
                1 if has_findings else 0,
            )

        return self._capacity_dispatch("capacity.evaluate", operation)

    def capacity_finding(
        self,
        scenario: Path,
        finding: Path,
        *,
        repository: str,
        branch: str,
        sha: str,
        run_id: str,
        timeout_seconds: int,
        adapters: tuple[str, ...],
    ) -> int:
        def operation() -> tuple[dict[str, Any], dict[str, Any], str, int]:
            context = _capacity_context(
                repo_root=self.repo_root,
                repository=repository,
                branch=branch,
                sha=sha,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
                adapters=adapters,
            )
            scenario_value = validate_scenario_file(scenario, self.repo_root)
            context = _capacity_context_with_scenario(context, scenario_value)
            finding_value = _capacity_read_object(finding)
            validate_finding(finding_value, self.repo_root)
            _require_capacity_finding_context(finding_value, context)
            return context, finding_value, "ok", 0

        return self._capacity_dispatch("capacity.finding", operation)

    def capacity_issue_plan(
        self,
        scenario: Path,
        result: Path,
        issues_snapshot: Path | None,
        fix_proposal: Path | None,
        fix_fingerprint: str | None,
        *,
        repository: str,
        branch: str,
        sha: str,
        run_id: str,
        timeout_seconds: int,
        adapters: tuple[str, ...],
    ) -> int:
        def operation() -> tuple[dict[str, Any], dict[str, Any], str, int]:
            context = _capacity_context(
                repo_root=self.repo_root,
                repository=repository,
                branch=branch,
                sha=sha,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
                adapters=adapters,
            )
            scenario_value = validate_scenario_file(scenario, self.repo_root)
            context = _capacity_context_with_scenario(context, scenario_value)
            result_value = _capacity_read_object(result)
            validate_capacity_result(result_value, scenario_value, self.repo_root)
            _require_capacity_result_context(result_value, context)
            evaluation_value = evaluate_capacity_result(
                scenario_value,
                result_value,
                self.repo_root,
            )
            findings = evaluation_value["findings"]
            publication_possible = any(
                finding["publication"]["eligible"] is True for finding in findings
            )
            if publication_possible:
                if issues_snapshot is None:
                    raise CapacityCommandError("issues-snapshot-required")
                snapshot = _capacity_read_value(issues_snapshot)
            else:
                snapshot = []
            decisions = plan_capacity_issues(
                evaluation_value,
                snapshot,
                self.repo_root,
            )
            fix = None
            if (fix_proposal is None) is not (fix_fingerprint is None):
                raise CapacityCommandError("fix-selection-incomplete")
            if fix_proposal is not None and fix_fingerprint is not None:
                matches = [
                    finding
                    for finding in findings
                    if isinstance(finding, dict)
                    and finding.get("fingerprint") == fix_fingerprint
                    and finding.get("publication")
                    == {"eligible": True, "reason": "cleanup-proven"}
                ]
                if not matches:
                    raise CapacityCommandError("fix-finding-not-found")
                selected_finding = min(
                    matches,
                    key=lambda item: json.dumps(
                        item,
                        separators=(",", ":"),
                        sort_keys=True,
                    ),
                )
                fix = plan_capacity_fix_candidate(
                    selected_finding,
                    _capacity_read_object(fix_proposal),
                    self.repo_root,
                    mutation_authorized=False,
                )
            return context, {"issue_decisions": decisions, "draft_fix": fix}, "ok", 0

        return self._capacity_dispatch("capacity.issue-plan", operation)

    def capacity_cancel(
        self,
        scenario: Path,
        *,
        termination: str,
        receipt: Path | None,
        repository: str,
        branch: str,
        sha: str,
        run_id: str,
        timeout_seconds: int,
        adapters: tuple[str, ...],
    ) -> int:
        def operation() -> tuple[dict[str, Any], dict[str, Any], str, int]:
            context = _capacity_context(
                repo_root=self.repo_root,
                repository=repository,
                branch=branch,
                sha=sha,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
                adapters=adapters,
            )
            scenario_value = validate_scenario_file(scenario, self.repo_root)
            context = _capacity_context_with_scenario(context, scenario_value)
            _validate_capacity_termination(termination)
            idempotency_key = _capacity_operation_key("cancel", context, termination)
            if self.dry_run:
                if receipt is not None:
                    raise CapacityCommandError("receipt-not-allowed-in-dry-run")
                result = {
                    "operation": "cancel",
                    "termination": termination,
                    "idempotency_key": idempotency_key,
                    "executed": False,
                    "receipt": None,
                }
                return context, result, "ok", 0
            if receipt is None:
                raise CapacityCommandError("cancellation-receipt-required")
            receipt_value = _capacity_read_bound_receipt(
                receipt,
                operation="cancel",
                context=context,
                termination=termination,
                idempotency_key=idempotency_key,
            )
            validate_cancellation_receipt(
                receipt_value,
                termination=termination,
                repo_root=self.repo_root,
            )
            public_receipt = _public_cancellation_receipt(receipt_value)
            failed = receipt_value["status"] == "failed"
            result = {
                "operation": "cancel",
                "termination": termination,
                "idempotency_key": idempotency_key,
                "executed": False,
                "receipt": public_receipt,
            }
            return (
                context,
                result,
                "negative-evidence" if failed else "ok",
                1 if failed else 0,
            )

        return self._capacity_dispatch("capacity.cancel", operation)

    def capacity_cleanup(
        self,
        scenario: Path,
        *,
        termination: str,
        receipt: Path | None,
        repository: str,
        branch: str,
        sha: str,
        run_id: str,
        timeout_seconds: int,
        adapters: tuple[str, ...],
    ) -> int:
        def operation() -> tuple[dict[str, Any], dict[str, Any], str, int]:
            context = _capacity_context(
                repo_root=self.repo_root,
                repository=repository,
                branch=branch,
                sha=sha,
                run_id=run_id,
                timeout_seconds=timeout_seconds,
                adapters=adapters,
            )
            scenario_value = validate_scenario_file(scenario, self.repo_root)
            context = _capacity_context_with_scenario(context, scenario_value)
            _validate_capacity_termination(termination)
            idempotency_key = _capacity_operation_key("cleanup", context, termination)
            if self.dry_run:
                if receipt is not None:
                    raise CapacityCommandError("receipt-not-allowed-in-dry-run")
                result = {
                    "operation": "cleanup",
                    "termination": termination,
                    "idempotency_key": idempotency_key,
                    "executed": False,
                    "receipt": None,
                }
                return context, result, "ok", 0
            if receipt is None:
                raise CapacityCommandError("cleanup-receipt-required")
            receipt_value = _capacity_read_bound_receipt(
                receipt,
                operation="cleanup",
                context=context,
                termination=termination,
                idempotency_key=idempotency_key,
            )
            validate_cleanup_receipt(receipt_value, repo_root=self.repo_root)
            public_receipt = _public_cleanup_receipt(receipt_value)
            failed = not (
                receipt_value["status"] == "succeeded"
                and receipt_value["zero_residue"] is True
            )
            result = {
                "operation": "cleanup",
                "termination": termination,
                "idempotency_key": idempotency_key,
                "executed": False,
                "receipt": public_receipt,
            }
            return (
                context,
                result,
                "negative-evidence" if failed else "ok",
                1 if failed else 0,
            )

        return self._capacity_dispatch("capacity.cleanup", operation)

    def _capacity_dispatch(self, command: str, operation: Any) -> int:
        try:
            context, result, status, exit_code = operation()
        except CapacityCommandError as exc:
            _print_capacity_output(command, "error", None, None, exc.code)
            return exc.exit_code
        except (CapacityValidationError, CapacityIssuePlanError):
            _print_capacity_output(command, "error", None, None, "validation-failed")
            return 2
        except (
            CapacityInputError,
            json.JSONDecodeError,
            OSError,
            RecursionError,
            UnicodeError,
        ):
            _print_capacity_output(
                command, "error", None, None, "input-unavailable-or-invalid"
            )
            return 2
        except ValueError:
            _print_capacity_output(
                command, "error", None, None, "input-unavailable-or-invalid"
            )
            return 2
        _print_capacity_output(command, status, context, result, None)
        return exit_code

    def clean_room_plan(self, sequence_name: str) -> int:
        sequence = self._load_clean_room_sequence(sequence_name)
        if sequence is None:
            return 2
        print(f"clean-room sequence: {sequence.id}")
        for index, step in enumerate(sequence.steps, start=1):
            print(f"{index}. {step.id}: {shlex.join(render_step_command(step))}")
        return 0

    def clean_room_script(self, sequence_name: str) -> int:
        sequence = self._load_clean_room_sequence(sequence_name)
        if sequence is None:
            return 2
        print(render_clean_room_script(sequence), end="")
        return 0

    def _run_phase_file(
        self,
        *,
        mode: str,
        phase_path: Path,
        selected_phase_ids: tuple[str, ...] | None,
        workaround: WorkaroundSpec | tuple[WorkaroundSpec, ...] | None,
        profile_env: dict[str, str] | None = None,
    ) -> int:
        phase_file = load_phase_file(phase_path)
        workarounds = _normalize_workarounds(workaround)
        phase_scope_start = _earliest_start_phase(phase_file, workarounds)
        if selected_phase_ids is None and phase_scope_start is not None:
            phases, assumed_phase_ids = _select_phases_from_start(
                phase_file, phase_scope_start
            )
        else:
            phases = _select_phases(phase_file, selected_phase_ids)
            assumed_phase_ids = ()
        profile_env = profile_env or {}
        env = {**profile_env, **_merged_workaround_env(workarounds)}
        skip_phases = {
            phase_id for spec in workarounds for phase_id in spec.skip_phases
        }

        if self.dry_run:
            self._print_plan(
                mode,
                phase_path,
                phases,
                workarounds,
                skip_phases,
                phase_scope_start,
                assumed_phase_ids,
                profile_env,
            )
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
            "phase_scope_start": phase_scope_start,
            "assumed_passed_phases": list(assumed_phase_ids),
            "profile_env": profile_env,
            "workaround": _workaround_json(workarounds[0])
            if len(workarounds) == 1
            else None,
            "workarounds": [_workaround_json(spec) for spec in workarounds],
            "output_dir": str(store.run_dir),
            "started_at": utc_now_iso(),
        }
        store.write_json("manifest.json", redactor.redact_mapping(manifest))
        print(f"issue-discovery run: {store.run_id}")
        print(f"artifacts: {store.run_dir}")

        collectors.collect_many(["git_status", "tool_versions"], reason="run_start")

        state = RunState()
        for spec in workarounds:
            if not self._apply_workaround(spec, store, redactor, env):
                state.blocking_failure = f"workaround:{spec.id}"
                break
        if state.blocking_failure is None:
            self._record_assumed_phases(phase_file, assumed_phase_ids, store, state)
            self._run_phases(
                phases, store, redactor, collectors, state, env, skip_phases
            )

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
            self._run_one_phase(
                phase, store, redactor, collectors, state, env, skip_phases
            )

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
        missing = [
            required
            for required in phase.requires
            if not _dependency_satisfied(state.phase_status.get(required))
        ]
        if missing and not phase.always_run:
            self._record_skip(
                store, state, phase, "dependency_not_passed", {"missing": missing}
            )
            return

        print(f"phase: {phase.id}")
        command_results: list[CommandResult] = []
        failed_commands: list[CommandResult] = []
        started_at = utc_now_iso()
        for command in phase.commands:
            result = self._run_command(store, redactor, phase.id, command, env)
            command_results.append(result)
            if not result.ok:
                failed_commands.append(result)
                if phase.blocking:
                    break

        first_failed_command = failed_commands[0] if failed_commands else None
        status = "failed" if failed_commands else "passed"
        state.phase_status[phase.id] = status
        if status == "failed":
            state.failed_phases.append(phase.id)
            collectors.collect_many(
                phase.collect_on_failure, reason=f"phase_failed:{phase.id}"
            )
            if phase.blocking and not phase.always_run:
                state.blocking_failure = phase.id
        else:
            collectors.collect_many(
                phase.collect_on_success, reason=f"phase_passed:{phase.id}"
            )

        record = {
            "id": phase.id,
            "name": phase.name,
            "category": phase.category,
            "blocking": phase.blocking,
            "status": status,
            "started_at": started_at,
            "completed_at": utc_now_iso(),
            "commands": [result.to_json(store.run_dir) for result in command_results],
            "failed_command": first_failed_command.id if first_failed_command else None,
            "failed_commands": [result.id for result in failed_commands],
            "classifiers": phase.classifiers if status == "failed" else (),
        }
        store.append_jsonl("phases.jsonl", redactor.redact_mapping(record))

    def _record_assumed_phases(
        self,
        phase_file: PhaseFile,
        assumed_phase_ids: tuple[str, ...],
        store: ArtifactStore,
        state: RunState,
    ) -> None:
        if not assumed_phase_ids:
            return
        assumed = set(assumed_phase_ids)
        for phase in phase_file.phases:
            if phase.id not in assumed:
                continue
            state.phase_status[phase.id] = "assumed_passed"
            store.append_jsonl(
                "phases.jsonl",
                {
                    "id": phase.id,
                    "name": phase.name,
                    "category": phase.category,
                    "blocking": phase.blocking,
                    "status": "assumed_passed",
                    "reason": "continuation_scope",
                    "commands": [],
                    "completed_at": utc_now_iso(),
                },
            )

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
            result = self._run_command(
                store, redactor, f"workaround_{workaround.id}", command, env
            )
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
                    "start_phase": workaround.start_phase,
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

    def _load_clean_room_sequence(self, sequence_name: str) -> CleanRoomSequence | None:
        sequence_dir = self.paths.config_dir / "clean-room"
        sequence_path = sequence_dir / f"{sequence_name}.yaml"
        if not sequence_path.exists():
            print(f"unknown clean-room sequence: {sequence_name}")
            available = sorted(path.stem for path in sequence_dir.glob("*.yaml"))
            if available:
                print("available clean-room sequences:")
                for name in available:
                    print(f"  - {name}")
            return None
        try:
            return load_clean_room_sequence(sequence_path, sequence_name)
        except KeyError:
            print(f"unknown clean-room sequence: {sequence_name}")
            return None

    def _print_plan(
        self,
        mode: str,
        phase_path: Path,
        phases: tuple[PhaseSpec, ...],
        workarounds: tuple[WorkaroundSpec, ...],
        skip_phases: set[str],
        phase_scope_start: str | None,
        assumed_phase_ids: tuple[str, ...],
        profile_env: dict[str, str],
    ) -> None:
        output = (
            self.output_dir
            if self.output_dir is not None
            else self.paths.default_output_root
        )
        print(f"issue-discovery command: {mode}")
        print(f"repo_root: {self.repo_root}")
        print(f"output: {output}")
        print("dry_run: yes")
        print(f"phase_file: {phase_path}")
        if phase_scope_start is not None:
            print(f"phase_scope_start: {phase_scope_start}")
            print("assumed_passed_phases:")
            for phase_id in assumed_phase_ids:
                print(f"  - {phase_id}")
        if workarounds:
            print("workarounds:")
            for workaround in workarounds:
                print(f"  - {workaround.id}")
        if profile_env:
            print("profile_env:")
            for key in sorted(profile_env):
                print(f"  {key}={profile_env[key]}")
        print("phases:")
        for phase in phases:
            suffix = " (skipped by workaround)" if phase.id in skip_phases else ""
            print(f"  - {phase.id}{suffix}")

    def _print_pending(self, command: str) -> None:
        output = (
            self.output_dir
            if self.output_dir is not None
            else self.paths.default_output_root
        )
        dry_run = "yes" if self.dry_run else "no"
        print(f"issue-discovery command: {command}")
        print(f"repo_root: {self.repo_root}")
        print(f"output: {output}")
        print(f"dry_run: {dry_run}")


def _capacity_context(
    *,
    repo_root: Path,
    repository: str,
    branch: str,
    sha: str,
    run_id: str,
    timeout_seconds: Any,
    adapters: Any,
) -> dict[str, Any]:
    parsed_adapters = _parse_capacity_adapters(adapters)
    if repository != _CAPACITY_PUBLIC_REPOSITORY:
        raise CapacityCommandError("invalid-public-context")
    try:
        validate_public_capacity_branch(
            branch,
            repo_root,
            label="capacity public branch",
        )
    except CapacityValidationError:
        raise CapacityCommandError("invalid-public-context") from None
    if not isinstance(sha, str) or _CAPACITY_SHA_RE.fullmatch(sha) is None:
        raise CapacityCommandError("invalid-public-context")
    if not isinstance(run_id, str) or _CAPACITY_RUN_ID_RE.fullmatch(run_id) is None:
        raise CapacityCommandError("invalid-run-context")
    if isinstance(timeout_seconds, str):
        if re.fullmatch(r"[1-9][0-9]{0,4}", timeout_seconds) is None:
            raise CapacityCommandError("invalid-run-context")
        normalized_timeout = int(timeout_seconds)
    elif isinstance(timeout_seconds, int) and not isinstance(timeout_seconds, bool):
        normalized_timeout = timeout_seconds
    else:
        raise CapacityCommandError("invalid-run-context")
    if not 1 <= normalized_timeout <= 86_400:
        raise CapacityCommandError("invalid-run-context")
    try:
        validate_public_capacity_data(
            run_id,
            repo_root,
            subject="capacity run metadata",
        )
    except CapacityValidationError:
        raise CapacityCommandError("invalid-run-context") from None
    return {
        "public_context": {
            "repository": repository,
            "branch": branch,
            "sha": sha,
        },
        "run": {
            "run_id": run_id,
            "timeout_seconds": normalized_timeout,
        },
        "adapters": parsed_adapters,
    }


def _parse_capacity_adapters(values: Any) -> dict[str, str]:
    if not isinstance(values, (list, tuple)) or not values:
        raise CapacityCommandError("invalid-adapter-selection", exit_code=3)
    parsed: dict[str, str] = {}
    for value in values:
        if not isinstance(value, str) or value.count("=") != 1:
            raise CapacityCommandError("invalid-adapter-selection", exit_code=3)
        kind, mode = value.split("=", 1)
        if kind not in _CAPACITY_ADAPTER_KINDS or mode not in _CAPACITY_ADAPTER_MODES:
            raise CapacityCommandError("invalid-adapter-selection", exit_code=3)
        if kind in parsed:
            raise CapacityCommandError("invalid-adapter-selection", exit_code=3)
        parsed[kind] = mode
    return {kind: parsed[kind] for kind in sorted(parsed)}


def _capacity_context_with_scenario(
    context: dict[str, Any],
    scenario: dict[str, Any],
) -> dict[str, Any]:
    return {**context, "scenario": _capacity_scenario_identity(scenario)}


def _capacity_scenario_identity(scenario: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(scenario["scenario_id"]),
        "sha256": scenario_sha256(scenario),
    }


def _capacity_read_value(path: Path) -> Any:
    return load_json_text(path.read_text(encoding="utf-8"), path)


def _capacity_read_object(path: Path) -> dict[str, Any]:
    value = _capacity_read_value(path)
    if not isinstance(value, dict):
        raise CapacityCommandError("input-must-be-object")
    return value


def _capacity_read_bound_receipt(
    path: Path,
    *,
    operation: str,
    context: dict[str, Any],
    termination: str,
    idempotency_key: str,
) -> dict[str, Any]:
    envelope = _capacity_read_object(path)
    expected_keys = {
        "schema_version",
        "operation",
        "idempotency_key",
        "public_context",
        "scenario",
        "run",
        "adapters",
        "termination",
        "receipt",
    }
    if set(envelope) != expected_keys:
        raise CapacityCommandError("receipt-envelope-invalid")
    expected = {
        "schema_version": 1,
        "operation": operation,
        "idempotency_key": idempotency_key,
        "public_context": context["public_context"],
        "scenario": context["scenario"],
        "run": context["run"],
        "adapters": context["adapters"],
        "termination": termination,
    }
    if any(envelope[key] != value for key, value in expected.items()):
        raise CapacityCommandError("receipt-context-mismatch")
    receipt = envelope["receipt"]
    if not isinstance(receipt, dict):
        raise CapacityCommandError("receipt-envelope-invalid")
    return receipt


def _require_capacity_result_context(
    result: dict[str, Any],
    context: dict[str, Any],
) -> None:
    run = result["run"]
    public = context["public_context"]
    expected = {
        "repository": public["repository"],
        "branch": public["branch"],
        "sha": public["sha"],
        "run_id": context["run"]["run_id"],
        "timeout_seconds": context["run"]["timeout_seconds"],
    }
    if any(run[key] != value for key, value in expected.items()):
        raise CapacityCommandError("context-mismatch")


def _require_capacity_finding_context(
    finding: dict[str, Any],
    context: dict[str, Any],
) -> None:
    public = context["public_context"]
    occurrence = finding["occurrence"]
    expected = {
        "repository": (finding["public_context"]["repository"], public["repository"]),
        "branch": (finding["public_context"]["branch"], public["branch"]),
        "sha": (finding["public_context"]["sha"], public["sha"]),
        "scenario_id": (finding["scenario"]["id"], context["scenario"]["id"]),
        "scenario_sha256": (
            finding["scenario"]["sha256"],
            context["scenario"]["sha256"],
        ),
        "run_id": (occurrence["run_id"], context["run"]["run_id"]),
        "timeout_seconds": (
            occurrence["timeout_seconds"],
            context["run"]["timeout_seconds"],
        ),
    }
    if any(values[0] != values[1] for values in expected.values()):
        raise CapacityCommandError("context-mismatch")


def _validate_capacity_termination(value: str) -> None:
    if value not in _CAPACITY_TERMINATIONS:
        raise CapacityCommandError("invalid-termination")


def _capacity_operation_key(
    operation: str,
    context: dict[str, Any],
    termination: str,
) -> str:
    identity = {
        "schema_version": 1,
        "operation": operation,
        "public_context": context["public_context"],
        "scenario": context["scenario"],
        "run": context["run"],
        "adapters": context["adapters"],
        "termination": termination,
    }
    encoded = json.dumps(identity, separators=(",", ":"), sort_keys=True).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _public_cancellation_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    failure = receipt["failure"]
    return {
        "attempted": receipt["attempted"],
        "status": receipt["status"],
        "failure": (
            None
            if failure is None
            else {"code": failure["code"], "location": failure["location"]}
        ),
    }


def _public_cleanup_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    failure = receipt["failure"]
    return {
        "attempted": receipt["attempted"],
        "status": receipt["status"],
        "zero_residue": receipt["zero_residue"],
        "failure": (
            None
            if failure is None
            else {"code": failure["code"], "location": failure["location"]}
        ),
    }


def _print_capacity_output(
    command: str,
    status: str,
    context: dict[str, Any] | None,
    result: dict[str, Any] | None,
    error_code: str | None,
) -> None:
    output = {
        "schema_version": 1,
        "command": command,
        "status": status,
        "context": context,
        "result": result,
        "error": None if error_code is None else {"code": error_code},
    }
    print(json.dumps(output, separators=(",", ":"), sort_keys=True))


def _select_phases(
    phase_file: PhaseFile, selected_phase_ids: tuple[str, ...] | None
) -> tuple[PhaseSpec, ...]:
    if selected_phase_ids is None:
        return phase_file.phases
    by_id = {phase.id: phase for phase in phase_file.phases}
    missing = [phase_id for phase_id in selected_phase_ids if phase_id not in by_id]
    if missing:
        raise ValueError(
            f"unknown phase ids in {phase_file.name}: {', '.join(missing)}"
        )
    included: set[str] = set()
    visiting: set[str] = set()

    def include_with_dependencies(phase_id: str) -> None:
        if phase_id in included:
            return
        if phase_id in visiting:
            raise ValueError(
                f"cyclic phase dependency in {phase_file.name}: {phase_id}"
            )
        phase = by_id.get(phase_id)
        if phase is None:
            raise ValueError(
                f"unknown required phase id in {phase_file.name}: {phase_id}"
            )
        visiting.add(phase_id)
        for required in phase.requires:
            include_with_dependencies(required)
        visiting.remove(phase_id)
        included.add(phase_id)

    for phase_id in selected_phase_ids:
        include_with_dependencies(phase_id)

    return tuple(phase for phase in phase_file.phases if phase.id in included)


def _select_phases_from_start(
    phase_file: PhaseFile,
    start_phase: str,
) -> tuple[tuple[PhaseSpec, ...], tuple[str, ...]]:
    phase_ids = [phase.id for phase in phase_file.phases]
    try:
        start_index = phase_ids.index(start_phase)
    except ValueError as exc:
        raise ValueError(
            f"unknown continuation start phase in {phase_file.name}: {start_phase}"
        ) from exc
    selected = tuple(phase_file.phases[start_index:])
    assumed = _dependency_closure_outside_selection(phase_file, selected)
    return selected, assumed


def _earliest_start_phase(
    phase_file: PhaseFile,
    workarounds: tuple[WorkaroundSpec, ...],
) -> str | None:
    phase_indexes = {phase.id: index for index, phase in enumerate(phase_file.phases)}
    starts = []
    for workaround in workarounds:
        if workaround.start_phase is None:
            continue
        if workaround.start_phase not in phase_indexes:
            raise ValueError(
                f"unknown continuation start phase for {workaround.id}: {workaround.start_phase}"
            )
        starts.append(workaround.start_phase)
    if not starts:
        return None
    return min(starts, key=lambda phase_id: phase_indexes[phase_id])


def _dependency_satisfied(status: str | None) -> bool:
    return status in {"passed", "assumed_passed"}


def _dependency_closure_outside_selection(
    phase_file: PhaseFile,
    selected: tuple[PhaseSpec, ...],
) -> tuple[str, ...]:
    by_id = {phase.id: phase for phase in phase_file.phases}
    selected_ids = {phase.id for phase in selected}
    required: set[str] = set()
    visiting: set[str] = set()

    def visit(phase_id: str) -> None:
        if phase_id in visiting:
            raise ValueError(
                f"cyclic phase dependency in {phase_file.name}: {phase_id}"
            )
        phase = by_id.get(phase_id)
        if phase is None:
            raise ValueError(
                f"unknown required phase id in {phase_file.name}: {phase_id}"
            )
        visiting.add(phase_id)
        for required_id in phase.requires:
            if required_id not in selected_ids:
                required.add(required_id)
                visit(required_id)
        visiting.remove(phase_id)

    for phase in selected:
        visit(phase.id)

    return tuple(phase.id for phase in phase_file.phases if phase.id in required)


def _workaround_json(workaround: WorkaroundSpec | None) -> dict[str, Any] | None:
    if workaround is None:
        return None
    return {
        "id": workaround.id,
        "status": workaround.status,
        "issue": workaround.issue,
        "start_phase": workaround.start_phase,
        "reason": workaround.reason,
        "removal_condition": workaround.removal_condition,
        "skip_phases": workaround.skip_phases,
        "env": workaround.env or {},
    }


def _normalize_workarounds(
    workaround: WorkaroundSpec | tuple[WorkaroundSpec, ...] | None,
) -> tuple[WorkaroundSpec, ...]:
    if workaround is None:
        return ()
    if isinstance(workaround, tuple):
        return workaround
    return (workaround,)


def _merged_workaround_env(workarounds: tuple[WorkaroundSpec, ...]) -> dict[str, str]:
    env: dict[str, str] = {}
    for workaround in workarounds:
        env.update(workaround.env or {})
    return env
