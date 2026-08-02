from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

from issue_discovery.redaction import Redactor


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
        'container name "/simple-compute-market',
        'container name "/bob-storefront"',
        'container name "/alice-storefront"',
        'container name "/registry"',
        'container name "/provisioning"',
        "already in use by container",
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
    "registry-agent-indexing-race": (
        "no agents found in the registry",
        "expected at least one registered agent",
        "agents_in_page=0",
    ),
    "stale-seller-layer-route": ('status=404 body={"detail":"not found"}',),
    "zerotier-build-path": (
        "zerotier",
        "install.zerotier.com",
        "zerotier-one",
    ),
}

_CAPACITY_PUBLIC_REPOSITORY = "arkhai-io/simple-compute-market"
_CAPACITY_EVALUATION_CLASSIFICATIONS = frozenset(
    {
        "success",
        "expected-scarcity",
        "harness-defect",
        "possible-product-defect",
        "environment-provider-issue",
        "cleanup-failure",
    }
)


class CapacityIssuePlanError(ValueError):
    """Raised when a capacity publication packet cannot be planned safely."""


@dataclass(frozen=True)
class CandidateReadiness:
    state: str
    confidence: str
    reason: str


@dataclass(frozen=True)
class IssueCandidate:
    fingerprint: str
    title: str
    labels: tuple[str, ...]
    classification: str
    phase: str
    body_file: Path
    evidence: tuple[str, ...]
    state: str
    confidence: str
    state_reason: str

    def to_json(self, run_dir: Path) -> dict[str, Any]:
        return {
            "fingerprint": self.fingerprint,
            "title": self.title,
            "labels": list(self.labels),
            "classification": self.classification,
            "phase": self.phase,
            "body_file": str(self.body_file.relative_to(run_dir)),
            "evidence": list(self.evidence),
            "state": self.state,
            "confidence": self.confidence,
            "state_reason": self.state_reason,
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
                handle.write(
                    json.dumps(candidate.to_json(self.run_dir), sort_keys=True) + "\n"
                )
        return candidates

    def _from_failed_phases(
        self,
        manifest: dict[str, Any],
        phases: list[dict[str, Any]],
        collectors: list[dict[str, Any]],
    ) -> list[IssueCandidate]:
        candidates: list[IssueCandidate] = []
        candidate_indexes: dict[str, int] = {}
        primary_phases: dict[str, dict[str, Any]] = {}
        for phase in phases:
            if phase.get("status") != "failed":
                continue
            evidence = _evidence_for_phase(self.run_dir, phase, collectors)
            fingerprints = _fingerprints_for_phase(self.run_dir, phase, evidence)
            for fingerprint in fingerprints:
                readiness = _readiness_for(fingerprint, manifest=manifest)
                if fingerprint in candidate_indexes:
                    index = candidate_indexes[fingerprint]
                    existing = candidates[index]
                    merged_evidence = _merge_evidence(existing.evidence, evidence)
                    existing.body_file.write_text(
                        _render_body(
                            manifest=manifest,
                            phase=primary_phases[fingerprint],
                            fingerprint=fingerprint,
                            evidence=list(merged_evidence),
                            readiness=readiness,
                        ),
                        encoding="utf-8",
                    )
                    candidates[index] = replace(existing, evidence=merged_evidence)
                    continue
                body_file = self.issue_dir / f"{fingerprint}.md"
                body_file.write_text(
                    _render_body(
                        manifest=manifest,
                        phase=phase,
                        fingerprint=fingerprint,
                        evidence=evidence,
                        readiness=readiness,
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
                        state=readiness.state,
                        confidence=readiness.confidence,
                        state_reason=readiness.reason,
                    )
                )
                candidate_indexes[fingerprint] = len(candidates) - 1
                primary_phases[fingerprint] = phase
        return candidates

    def _from_workaround_failure(self, manifest: dict[str, Any]) -> IssueCandidate:
        raw = str(manifest["blocking_failure"])
        fingerprint = _slug(raw.replace(":", "-"))
        readiness = CandidateReadiness(
            state="harness_gap",
            confidence="medium",
            reason="The issue-discovery workaround failed before product/runtime evidence could be gathered.",
        )
        body_file = self.issue_dir / f"{fingerprint}.md"
        body_file.write_text(
            "\n".join(
                [
                    f"# Explicit workaround failed: `{raw}`",
                    "",
                    "## Filing Readiness",
                    f"- State: `{readiness.state}`",
                    f"- Confidence: `{readiness.confidence}`",
                    f"- Reason: {readiness.reason}",
                    "",
                    "## Summary",
                    "An explicit issue-discovery continuation workaround failed before the workflow could continue.",
                    "",
                    "## Reproduction",
                    f"Run `{_reproduction_command(manifest)}`.",
                    "",
                    "## Evidence",
                    f"- Run manifest: `{_rel(self.run_dir / 'manifest.json', self.run_dir)}`",
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
            state=readiness.state,
            confidence=readiness.confidence,
            state_reason=readiness.reason,
        )


class IssueRepository:
    def __init__(self, run_dir: Path, repo_root: Path | None = None) -> None:
        self.run_dir = run_dir
        self.repo_root = (
            repo_root.resolve() if repo_root is not None else Path.cwd().resolve()
        )
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

    def create(self, fingerprint: str, dry_run: bool, force: bool = False) -> int:
        candidate = self.get(fingerprint)
        state = str(candidate.get("state", "unknown"))
        if state != "ready_to_file" and not force:
            print(
                f"candidate {fingerprint} is {state}, not ready_to_file; "
                "rerun with --force to override"
            )
            return 2

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

        if not self._body_is_redacted(body_path):
            return 2

        duplicate = self._find_duplicate(candidate)
        if duplicate is None:
            return 2
        if duplicate:
            print(
                f"duplicate issue exists: {duplicate.get('url') or duplicate.get('title')}"
            )
            return 0

        completed = subprocess.run(command, check=False, text=True, cwd=self.repo_root)
        return completed.returncode

    def _find_duplicate(
        self, candidate: dict[str, Any]
    ) -> dict[str, Any] | bool | None:
        command = [
            "gh",
            "issue",
            "list",
            "--search",
            f"{candidate['fingerprint']} in:title",
            "--json",
            "number,title,state,url",
            "--limit",
            "10",
        ]
        completed = subprocess.run(
            command,
            check=False,
            text=True,
            cwd=self.repo_root,
            capture_output=True,
        )
        if completed.returncode != 0:
            print("duplicate issue check failed")
            return None
        try:
            issues = json.loads(completed.stdout or "[]")
        except json.JSONDecodeError:
            print("duplicate issue check returned invalid JSON")
            return None
        if not isinstance(issues, list):
            print("duplicate issue check returned unexpected JSON")
            return None
        return issues[0] if issues else False

    def _body_is_redacted(self, body_path: Path) -> bool:
        redactions_path = (
            self.repo_root / "tools" / "issue-discovery" / "config" / "redactions.yaml"
        )
        if not redactions_path.exists():
            return True
        body = body_path.read_text(encoding="utf-8")
        if Redactor.from_file(redactions_path).redact(body) == body:
            return True
        print("issue body still contains unredacted data; refusing to create issue")
        return False


def plan_capacity_issues(
    evaluation: dict[str, Any],
    existing_issues: list[dict[str, Any]],
    repo_root: Path,
) -> dict[str, Any]:
    """Plan capacity issue decisions from sanitized data without side effects."""

    from issue_discovery.capacity import validate_finding

    if not isinstance(evaluation, dict):
        raise CapacityIssuePlanError("capacity evaluation must be an object")
    required = {
        "schema_version",
        "scenario_id",
        "scenario_sha256",
        "termination",
        "run",
        "classification",
        "counts",
        "findings",
    }
    missing = sorted(required - set(evaluation))
    if missing:
        raise CapacityIssuePlanError(
            "capacity evaluation is missing required fields: " + ", ".join(missing)
        )
    if evaluation["schema_version"] != 1:
        raise CapacityIssuePlanError("capacity evaluation schema_version must be 1")
    classification = evaluation["classification"]
    if classification not in _CAPACITY_EVALUATION_CLASSIFICATIONS:
        raise CapacityIssuePlanError(
            "capacity evaluation classification is unsupported"
        )
    findings = evaluation["findings"]
    if not isinstance(findings, list):
        raise CapacityIssuePlanError("capacity evaluation findings must be an array")
    counts = evaluation["counts"]
    expected_count_keys = {"success", "expected_scarcity", "findings"}
    if not isinstance(counts, dict) or set(counts) != expected_count_keys:
        raise CapacityIssuePlanError(
            "capacity evaluation counts must contain success, expected_scarcity, and findings"
        )
    if any(
        not isinstance(counts[key], int)
        or isinstance(counts[key], bool)
        or counts[key] < 0
        for key in expected_count_keys
    ) or counts["findings"] != len(findings):
        raise CapacityIssuePlanError("capacity evaluation counts are inconsistent")

    if classification in {"success", "expected-scarcity"}:
        if findings:
            raise CapacityIssuePlanError(
                f"{classification} evaluation cannot contain publishable findings"
            )
        scarcity_suppressed = counts["expected_scarcity"] > 0
        if classification == "expected-scarcity" and not scarcity_suppressed:
            raise CapacityIssuePlanError(
                "expected-scarcity evaluation must count expected scarcity"
            )
        return {
            "schema_version": 1,
            "kind": "capacity-issue-decisions",
            "decision": "suppressed" if scarcity_suppressed else "no-action",
            "reason": "expected-scarcity" if scarcity_suppressed else classification,
            "plans": [],
        }

    if not findings:
        raise CapacityIssuePlanError(
            f"{classification} evaluation must retain at least one finding"
        )
    run = evaluation["run"]
    if not isinstance(run, dict):
        raise CapacityIssuePlanError("capacity evaluation run must be an object")
    run_fields = {
        "repository",
        "branch",
        "sha",
        "run_id",
        "observed_at",
        "timeout_seconds",
    }
    missing_run = sorted(run_fields - set(run))
    if missing_run:
        raise CapacityIssuePlanError(
            "capacity evaluation run is missing required fields: "
            + ", ".join(missing_run)
        )

    grouped: dict[str, list[dict[str, Any]]] = {}
    finding_classifications: set[str] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            raise CapacityIssuePlanError(
                "capacity evaluation findings must contain objects"
            )
        validate_finding(finding, repo_root)
        _require_finding_evaluation_alignment(finding, evaluation, run)
        fingerprint = str(finding["fingerprint"])
        grouped.setdefault(fingerprint, []).append(finding)
        finding_classifications.add(str(finding["classification"]))
    if classification not in finding_classifications:
        raise CapacityIssuePlanError(
            "capacity evaluation classification must identify a retained finding"
        )

    publication_possible = any(
        finding["publication"]["eligible"] is True for finding in findings
    )
    normalized_issues = (
        _validate_capacity_issue_snapshot(existing_issues)
        if publication_possible
        else []
    )
    plans = [
        _plan_capacity_finding_group(grouped[fingerprint], normalized_issues)
        for fingerprint in sorted(grouped)
    ]
    return {
        "schema_version": 1,
        "kind": "capacity-issue-decisions",
        "decision": (
            "withheld"
            if all(plan["action"] == "withhold" for plan in plans)
            else "planned"
        ),
        "reason": "cleanup-not-proven"
        if all(plan["action"] == "withhold" for plan in plans)
        else "sanitized-findings",
        "plans": plans,
    }


def plan_capacity_fix_candidate(
    finding: dict[str, Any],
    proposal: dict[str, Any],
    repo_root: Path,
    *,
    mutation_authorized: bool = False,
) -> dict[str, Any]:
    """Validate a harness-owned draft-fix packet without creating Git state."""

    from issue_discovery.capacity import validate_finding

    validate_finding(finding, repo_root)
    if finding["classification"] != "harness-defect":
        raise CapacityIssuePlanError(
            "draft fixes are limited to harness-defect findings"
        )
    if finding["publication"] != {"eligible": True, "reason": "cleanup-proven"}:
        raise CapacityIssuePlanError(
            "draft fixes require cleanup-proven publication eligibility"
        )
    if not isinstance(mutation_authorized, bool):
        raise CapacityIssuePlanError("mutation_authorized must be a boolean")
    if not isinstance(proposal, dict):
        raise CapacityIssuePlanError("draft-fix proposal must be an object")
    expected_keys = {"schema_version", "ownership", "summary", "paths"}
    if set(proposal) != expected_keys:
        raise CapacityIssuePlanError(
            "draft-fix proposal fields must be exactly: "
            + ", ".join(sorted(expected_keys))
        )
    if proposal["schema_version"] != 1:
        raise CapacityIssuePlanError("draft-fix proposal schema_version must be 1")
    if proposal["ownership"] != "public-harness":
        raise CapacityIssuePlanError(
            "draft-fix proposal ownership must be public-harness"
        )

    fingerprint = str(finding["fingerprint"])
    expected_head = f"fix/{fingerprint}"
    expected_base = str(finding["public_context"]["branch"])
    if expected_head == expected_base or expected_base in {"dev", "main"}:
        raise CapacityIssuePlanError("draft-fix head and base violate branch authority")

    summary = proposal["summary"]
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 240:
        raise CapacityIssuePlanError(
            "draft-fix summary must be a non-empty string of at most 240 chars"
        )
    if summary != summary.strip() or "\n" in summary or "\r" in summary:
        raise CapacityIssuePlanError(
            "draft-fix summary must use a single normalized line"
        )
    summary_probe = dict(finding)
    summary_probe["summary"] = summary
    validate_finding(summary_probe, repo_root)

    raw_paths = proposal["paths"]
    if not isinstance(raw_paths, list) or not raw_paths:
        raise CapacityIssuePlanError("draft-fix paths must be a non-empty array")
    if not all(isinstance(path, str) for path in raw_paths):
        raise CapacityIssuePlanError("draft-fix paths must contain strings")
    paths = sorted(raw_paths)
    if len(paths) != len(set(paths)):
        raise CapacityIssuePlanError("draft-fix paths must be unique")
    for path in paths:
        if not _capacity_fix_path_is_allowed(path):
            raise CapacityIssuePlanError(
                f"draft-fix path is outside the harness allowlist: {path}"
            )

    repository = str(finding["public_context"]["repository"])
    if repository != _CAPACITY_PUBLIC_REPOSITORY:
        raise CapacityIssuePlanError(
            "draft-fix repository is not the public SCM repository"
        )
    commands = [
        {
            "purpose": "create-fix-head",
            "argv": ["git", "switch", "--create", expected_head, expected_base],
        },
        {
            "purpose": "push-fix-head",
            "argv": ["git", "push", "origin", f"{expected_head}:{expected_head}"],
        },
        {
            "purpose": "create-draft-pr",
            "argv": [
                "gh",
                "pr",
                "create",
                "--repo",
                repository,
                "--draft",
                "--base",
                expected_base,
                "--head",
                expected_head,
                "--title",
                summary,
            ],
        },
    ]
    return {
        "schema_version": 1,
        "kind": "capacity-draft-fix-plan",
        "status": "ready-for-authorized-mutation"
        if mutation_authorized
        else "candidate",
        "reason": "mutation-authorized"
        if mutation_authorized
        else "mutation-authority-absent",
        "repository": repository,
        "fingerprint": fingerprint,
        "head": expected_head,
        "base": expected_base,
        "draft": True,
        "auto_merge": False,
        "executed": False,
        "summary": summary,
        "paths": paths,
        "commands": commands,
    }


def _require_finding_evaluation_alignment(
    finding: dict[str, Any],
    evaluation: dict[str, Any],
    run: dict[str, Any],
) -> None:
    expected = {
        "scenario.id": (finding["scenario"]["id"], evaluation["scenario_id"]),
        "scenario.sha256": (
            finding["scenario"]["sha256"],
            evaluation["scenario_sha256"],
        ),
        "occurrence.termination": (
            finding["occurrence"]["termination"],
            evaluation["termination"],
        ),
        "public_context.repository": (
            finding["public_context"]["repository"],
            run["repository"],
        ),
        "public_context.branch": (finding["public_context"]["branch"], run["branch"]),
        "public_context.sha": (finding["public_context"]["sha"], run["sha"]),
        "occurrence.run_id": (finding["occurrence"]["run_id"], run["run_id"]),
        "occurrence.observed_at": (
            finding["occurrence"]["observed_at"],
            run["observed_at"],
        ),
        "occurrence.timeout_seconds": (
            finding["occurrence"]["timeout_seconds"],
            run["timeout_seconds"],
        ),
    }
    mismatches = [label for label, values in expected.items() if values[0] != values[1]]
    if mismatches:
        raise CapacityIssuePlanError(
            "finding does not align with its capacity evaluation: "
            + ", ".join(mismatches)
        )


def _validate_capacity_issue_snapshot(
    existing_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(existing_issues, list):
        raise CapacityIssuePlanError("existing issue snapshot must be an array")
    normalized = []
    numbers: set[int] = set()
    for issue in existing_issues:
        if not isinstance(issue, dict):
            raise CapacityIssuePlanError("existing issue snapshot must contain objects")
        number = issue.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise CapacityIssuePlanError(
                "existing issue number must be a positive integer"
            )
        if number in numbers:
            raise CapacityIssuePlanError("existing issue numbers must be unique")
        numbers.add(number)
        state = str(issue.get("state", "")).upper()
        if state not in {"OPEN", "CLOSED"}:
            raise CapacityIssuePlanError("existing issue state must be OPEN or CLOSED")
        body = issue.get("body")
        if not isinstance(body, str):
            raise CapacityIssuePlanError("existing issue body must be a string")
        comments = issue.get("comments", [])
        if not isinstance(comments, list):
            raise CapacityIssuePlanError("existing issue comments must be an array")
        comment_bodies = []
        for comment in comments:
            if isinstance(comment, str):
                comment_bodies.append(comment)
            elif isinstance(comment, dict) and isinstance(comment.get("body"), str):
                comment_bodies.append(str(comment["body"]))
            else:
                raise CapacityIssuePlanError(
                    "existing issue comments must contain strings or body objects"
                )
        normalized.append(
            {
                "number": number,
                "state": state,
                "texts": [body, *comment_bodies],
            }
        )
    return sorted(normalized, key=lambda issue: issue["number"])


def _plan_capacity_finding_group(
    findings: list[dict[str, Any]],
    existing_issues: list[dict[str, Any]],
) -> dict[str, Any]:
    findings = sorted(findings, key=_capacity_canonical_json)
    first = findings[0]
    fingerprint = str(first["fingerprint"])
    scope_marker = _capacity_scope_marker(first)
    for finding in findings[1:]:
        if (
            finding["fingerprint"] != fingerprint
            or _capacity_scope_marker(finding) != scope_marker
        ):
            raise CapacityIssuePlanError(
                "one fingerprint cannot span multiple public issue scopes"
            )

    eligible = [
        finding for finding in findings if finding["publication"]["eligible"] is True
    ]
    withheld = [
        finding for finding in findings if finding["publication"]["eligible"] is False
    ]
    withheld_markers = sorted(
        {_capacity_occurrence_marker(finding) for finding in withheld}
    )
    common = {
        "schema_version": 1,
        "kind": "capacity-issue-plan",
        "repository": _CAPACITY_PUBLIC_REPOSITORY,
        "fingerprint": fingerprint,
        "scope_marker": scope_marker,
        "withheld_occurrence_markers": withheld_markers,
        "dry_run": True,
    }
    if not eligible:
        return {
            **common,
            "action": "withhold",
            "reason": "cleanup-not-proven",
            "issue_number": None,
            "occurrence_markers": [],
            "operations": [],
        }

    occurrences: dict[str, list[dict[str, Any]]] = {}
    for finding in eligible:
        marker = _capacity_occurrence_marker(finding)
        occurrences.setdefault(marker, []).append(finding)
    merged_occurrences = {
        marker: _merge_capacity_occurrence_findings(items)
        for marker, items in occurrences.items()
    }
    occurrence_blocks = {
        marker: _render_capacity_occurrence(merged_occurrences[marker], marker)
        for marker in merged_occurrences
    }
    occurrence_markers = sorted(occurrence_blocks)
    matches = [
        issue
        for issue in existing_issues
        if any(scope_marker in text for text in issue["texts"])
    ]
    if len(matches) > 1:
        raise CapacityIssuePlanError(
            "multiple issues contain the same stable capacity scope marker"
        )

    for issue in existing_issues:
        has_occurrence = any(
            fingerprint in _capacity_occurrence_fingerprints(text)
            for text in issue["texts"]
        )
        has_scope = any(scope_marker in text for text in issue["texts"])
        if has_occurrence and not has_scope:
            raise CapacityIssuePlanError(
                "capacity occurrence marker exists without its stable scope marker"
            )

    if not matches:
        issue_finding = merged_occurrences[occurrence_markers[0]]
        body = _render_capacity_issue_body(
            issue_finding,
            scope_marker,
            [occurrence_blocks[marker] for marker in occurrence_markers],
        )
        operation = {
            "operation": "create",
            "repository": _CAPACITY_PUBLIC_REPOSITORY,
            "title": _capacity_issue_title(issue_finding),
            "body": body,
            "labels": ["bug", "capacity", "issue-discovery"],
        }
        return {
            **common,
            "action": "create",
            "reason": "no-matching-scope",
            "issue_number": None,
            "occurrence_markers": occurrence_markers,
            "operations": [operation],
        }

    issue = matches[0]
    seen_text = "\n".join(issue["texts"])
    unseen = [marker for marker in occurrence_markers if marker not in seen_text]
    if not unseen:
        return {
            **common,
            "action": "no-op",
            "reason": "occurrence-already-recorded",
            "issue_number": issue["number"],
            "occurrence_markers": occurrence_markers,
            "operations": [],
        }

    comment_body = "\n\n".join(
        [scope_marker, *(occurrence_blocks[marker] for marker in unseen)]
    )
    comment = {
        "operation": "comment",
        "repository": _CAPACITY_PUBLIC_REPOSITORY,
        "issue_number": issue["number"],
        "body": comment_body + "\n",
    }
    if issue["state"] == "CLOSED":
        operations = [
            {
                "operation": "reopen",
                "repository": _CAPACITY_PUBLIC_REPOSITORY,
                "issue_number": issue["number"],
            },
            comment,
        ]
        action = "reopen"
        reason = "closed-scope-has-new-occurrence"
    else:
        operations = [comment]
        action = "update"
        reason = "open-scope-has-new-occurrence"
    return {
        **common,
        "action": action,
        "reason": reason,
        "issue_number": issue["number"],
        "occurrence_markers": unseen,
        "operations": operations,
    }


def _capacity_issue_title(finding: dict[str, Any]) -> str:
    return (
        f"[capacity:{finding['scenario']['id']}] {finding['failure']['code']} "
        f"({str(finding['fingerprint'])[:12]})"
    )


def _merge_capacity_occurrence_findings(
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    ordered = sorted(findings, key=_capacity_canonical_json)
    first = ordered[0]
    stable = {key: value for key, value in first.items() if key != "evidence"}
    if any(
        _capacity_canonical_json(
            {key: value for key, value in finding.items() if key != "evidence"}
        )
        != _capacity_canonical_json(stable)
        for finding in ordered[1:]
    ):
        raise CapacityIssuePlanError(
            "one capacity occurrence marker cannot represent conflicting findings"
        )
    evidence = {
        _capacity_canonical_json(item): item
        for finding in ordered
        for item in finding["evidence"]
    }
    merged = dict(first)
    merged["evidence"] = [evidence[key] for key in sorted(evidence)]
    return merged


def _render_capacity_issue_body(
    finding: dict[str, Any],
    scope_marker: str,
    occurrence_blocks: list[str],
) -> str:
    lines = [
        f"# {_capacity_issue_title(finding)}",
        "",
        scope_marker,
        "",
        "## Sanitized finding",
        f"- Classification: `{finding['classification']}`",
        f"- Scenario: `{finding['scenario']['id']}`",
        f"- Scenario SHA-256: `{finding['scenario']['sha256']}`",
        f"- Public branch: `{finding['public_context']['branch']}`",
        f"- Failure code: `{finding['failure']['code']}`",
        f"- Failure location: `{finding['failure']['location']}`",
        f"- Summary: {_capacity_markdown_text(finding['summary'])}",
        "",
        "## Occurrences",
        "",
        "\n\n".join(occurrence_blocks),
        "",
        "This packet contains sanitized public assertions only. Cleanup must remain proven before publication.",
        "",
    ]
    return "\n".join(lines)


def _render_capacity_occurrence(finding: dict[str, Any], marker: str) -> str:
    occurrence = finding["occurrence"]
    cancellation = finding["cancellation"]
    cleanup = finding["cleanup"]
    lines = [
        marker,
        f"### Run `{occurrence['run_id']}`",
        f"- Observed: `{occurrence['observed_at']}`",
        f"- Public branch: `{finding['public_context']['branch']}`",
        f"- Public SHA: `{finding['public_context']['sha']}`",
        f"- Termination: `{occurrence['termination']}`",
        f"- Timeout seconds: `{occurrence['timeout_seconds']}`",
        f"- Request ordinal: `{occurrence['request_ordinal']}`",
        f"- Cancellation: `{cancellation['status']}`",
        f"- Cleanup: `{cleanup['status']}`; zero residue: `{cleanup['zero_residue']}`",
        f"- Stable evidence: {_capacity_markdown_text(finding['failure']['stable_evidence_summary'])}",
    ]
    for evidence in finding["evidence"]:
        lines.append(
            f"- Evidence `{evidence['kind']}`: {_capacity_markdown_text(evidence['summary'])}"
        )
    return "\n".join(lines)


def _capacity_scope_marker(finding: dict[str, Any]) -> str:
    return _capacity_machine_marker(
        "scope",
        {
            "schema_version": 1,
            "repository": finding["public_context"]["repository"],
            "fingerprint": finding["fingerprint"],
        },
    )


def _capacity_occurrence_marker(finding: dict[str, Any]) -> str:
    occurrence = finding["occurrence"]
    return _capacity_machine_marker(
        "occurrence",
        {
            "schema_version": 1,
            "fingerprint": finding["fingerprint"],
            "repository": finding["public_context"]["repository"],
            "public_branch": finding["public_context"]["branch"],
            "public_sha": finding["public_context"]["sha"],
            "run_id": occurrence["run_id"],
            "observed_at": occurrence["observed_at"],
            "termination": occurrence["termination"],
            "timeout_seconds": occurrence["timeout_seconds"],
            "request_ordinal": occurrence["request_ordinal"],
        },
    )


def _capacity_machine_marker(kind: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    safe_serialized = serialized.replace("--", "\\u002d\\u002d")
    return f"<!-- scm-capacity-{kind} {safe_serialized} -->"


def _capacity_canonical_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _capacity_occurrence_fingerprints(text: str) -> set[str]:
    prefix = "<!-- scm-capacity-occurrence "
    suffix = " -->"
    fingerprints: set[str] = set()
    cursor = 0
    while True:
        start = text.find(prefix, cursor)
        if start < 0:
            return fingerprints
        payload_start = start + len(prefix)
        end = text.find(suffix, payload_start)
        if end < 0:
            raise CapacityIssuePlanError("capacity occurrence marker is malformed")
        try:
            payload = json.loads(text[payload_start:end])
        except json.JSONDecodeError as exc:
            raise CapacityIssuePlanError(
                "capacity occurrence marker is malformed"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != 1
            or not isinstance(payload.get("fingerprint"), str)
        ):
            raise CapacityIssuePlanError("capacity occurrence marker is malformed")
        fingerprints.add(str(payload["fingerprint"]))
        cursor = end + len(suffix)


def _capacity_markdown_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("`", "\\`")
    )


def _capacity_fix_path_is_allowed(value: str) -> bool:
    if not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or "." in path.parts
        or ".." in path.parts
    ):
        return False
    source_root = PurePosixPath("tools/issue-discovery/src/issue_discovery")
    test_root = PurePosixPath("tools/issue-discovery/tests")
    fixture_root = PurePosixPath("tools/issue-discovery/config/capacity")
    schema_root = PurePosixPath("tools/issue-discovery/schemas")
    exact_paths = {
        PurePosixPath("tools/issue-discovery/README.md"),
        PurePosixPath("docs/development/ISSUE_DISCOVERY.md"),
        PurePosixPath("openspec/specs/test-compatibility/spec.md"),
        PurePosixPath("openspec/specs/test-compatibility/architecture.md"),
    }
    if path in exact_paths:
        return True
    if path.is_relative_to(source_root) and path.suffix == ".py":
        return True
    if path.is_relative_to(test_root) and path.suffix in {".py", ".json"}:
        return True
    if path.is_relative_to(fixture_root) and path.suffix == ".json":
        return True
    return (
        path.parent == schema_root
        and path.name.startswith("capacity-")
        and path.suffix == ".json"
    )


def _render_body(
    *,
    manifest: dict[str, Any],
    phase: dict[str, Any],
    fingerprint: str,
    evidence: list[str],
    readiness: CandidateReadiness,
) -> str:
    failed_commands = _failed_commands_for_phase(phase)
    primary_failed_command = failed_commands[0] if failed_commands else None
    command_records = phase.get("commands") or []
    lines = [
        f"# {_title_for_phase(phase, fingerprint)}",
        "",
        "## Filing Readiness",
        f"- State: `{readiness.state}`",
        f"- Confidence: `{readiness.confidence}`",
        f"- Reason: {readiness.reason}",
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


def _readiness_for(
    fingerprint: str,
    *,
    manifest: dict[str, Any] | None = None,
) -> CandidateReadiness:
    mode = str((manifest or {}).get("mode", ""))
    targeted_ready_reasons = {
        ("profile:host-redis-conflict", "redis-host-port-conflict"): (
            "The targeted host Redis conflict profile reproduced the local compose port conflict."
        ),
        ("profile:fresh-volumes", "storefront-volume-ownership"): (
            "The targeted fresh-volume profile reproduced the storefront volume ownership failure."
        ),
        ("profile:zerotier-build-path", "zerotier-build-path"): (
            "The targeted ZeroTier build-path profile reproduced the non-interactive build failure."
        ),
    }
    targeted_reason = targeted_ready_reasons.get((mode, fingerprint))
    if targeted_reason is not None:
        return CandidateReadiness(
            state="ready_to_file",
            confidence="high",
            reason=targeted_reason,
        )

    ready_reasons = {
        "root-service-tests-make-test": (
            "The repo-level test command fails directly and has command-level evidence."
        ),
        "registry-agent-indexing-race": (
            "The registry smoke failure has a known fingerprint and direct evidence from stack tests."
        ),
        "stale-seller-layer-route": (
            "The seller role-layer route mismatch has a known fingerprint and direct evidence."
        ),
    }
    if fingerprint in ready_reasons:
        return CandidateReadiness(
            state="ready_to_file",
            confidence="high",
            reason=ready_reasons[fingerprint],
        )

    targeted_repro_reasons = {
        "redis-host-port-conflict": (
            "Host Redis conflicts need a targeted strict failure and workaround-success repro."
        ),
        "storefront-volume-ownership": (
            "Storefront volume ownership needs a targeted fresh-volume repro before filing."
        ),
        "zerotier-build-path": (
            "ZeroTier build behavior needs an isolated build-path repro before filing."
        ),
        "e2e-marker-tests-e2e-deal": (
            "This e2e marker failure disappeared after continuation and needs targeted confirmation."
        ),
    }
    if fingerprint in targeted_repro_reasons:
        return CandidateReadiness(
            state="needs_targeted_repro",
            confidence="medium",
            reason=targeted_repro_reasons[fingerprint],
        )

    if fingerprint in {"fixed-docker-name-collision", "preexisting-compose-stack"}:
        return CandidateReadiness(
            state="environment_only",
            confidence="medium",
            reason="This finding describes local environment state that should not be filed as a repo bug by default.",
        )

    return CandidateReadiness(
        state="needs_targeted_repro",
        confidence="low",
        reason="Generic phase failures need targeted reproduction before they are fileable.",
    )


def _fingerprints_for_phase(
    run_dir: Path, phase: dict[str, Any], evidence: list[str]
) -> list[str]:
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


def _merge_evidence(existing: tuple[str, ...], new: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys([*existing, *new]))


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
        workarounds = _workarounds_for_manifest(manifest)
        if not workarounds:
            return "./scripts/issue-discovery continue"
        args = " ".join(f"--with {workaround.get('id')}" for workaround in workarounds)
        return f"./scripts/issue-discovery continue {args}"
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
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _shell_quote(value: str) -> str:
    if (
        value.replace("-", "")
        .replace("_", "")
        .replace("/", "")
        .replace(".", "")
        .isalnum()
    ):
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"
