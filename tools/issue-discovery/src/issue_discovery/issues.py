from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
    "stale-seller-layer-route": (
        'status=404 body={"detail":"not found"}',
    ),
    "zerotier-build-path": (
        "zerotier",
        "install.zerotier.com",
        "zerotier-one",
    ),
}

_CAPACITY_REPOSITORIES = {
    "simple-compute-market": (
        "github.com/arkhai-io/simple-compute-market",
        "feat/issue-discovery-harness",
    ),
    "compute-market-internal-infra": (
        "github.com/arkhai-io/compute-market-internal-infra",
        "tools/agent-orchestration-scratch",
    ),
}
_FORBIDDEN_BASE_BRANCHES = {"dev", "main"}


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
    working_branch: str | None = None
    observed_ref: str | None = None
    scenario_id: str | None = None
    scenario_fingerprint: str | None = None
    run_id: str | None = None
    destination_repo: str | None = None
    lifecycle_state: str | None = None

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
            "working_branch": self.working_branch,
            "observed_ref": self.observed_ref,
            "scenario_id": self.scenario_id,
            "scenario_fingerprint": self.scenario_fingerprint,
            "run_id": self.run_id,
            "destination_repo": self.destination_repo,
            "lifecycle_state": self.lifecycle_state,
        }


class IssuePacketGenerator:
    def __init__(self, run_dir: Path, repo_root: Path | None = None) -> None:
        self.run_dir = run_dir
        self.repo_root = repo_root.resolve() if repo_root is not None else None
        self.issue_dir = run_dir / "issue-candidates"

    def generate(self) -> list[IssueCandidate]:
        self.issue_dir.mkdir(parents=True, exist_ok=True)
        manifest = _read_json(self.run_dir / "manifest.json")
        phases = _read_jsonl(self.run_dir / "phases.jsonl")
        collectors = _read_jsonl(self.run_dir / "collectors.jsonl")
        candidates = self._from_failed_phases(manifest, phases, collectors)
        candidates.extend(
            self._from_capacity_findings(
                manifest,
                _read_jsonl(self.run_dir / "capacity-findings.jsonl"),
            )
        )
        blocking_failure = manifest.get("blocking_failure") or ""
        if not candidates and str(blocking_failure).startswith("workaround:"):
            candidates = [self._from_workaround_failure(manifest)]

        jsonl_path = self.issue_dir / "candidates.jsonl"
        with jsonl_path.open("w", encoding="utf-8") as handle:
            for candidate in candidates:
                handle.write(json.dumps(candidate.to_json(self.run_dir), sort_keys=True) + "\n")
        return candidates

    def _from_capacity_findings(
        self,
        manifest: dict[str, Any],
        findings: list[dict[str, Any]],
    ) -> list[IssueCandidate]:
        if not findings:
            return []
        repo_root = self.repo_root
        if repo_root is None:
            configured = manifest.get("repo_root")
            repo_root = Path(str(configured)).resolve() if configured else Path.cwd().resolve()
        from issue_discovery.capacity import validate_finding

        candidates = []
        for finding in findings:
            validate_finding(finding, repo_root)
            readiness_data = finding["filing_readiness"]
            readiness = CandidateReadiness(
                state=readiness_data["state"],
                confidence=readiness_data["confidence"],
                reason=readiness_data["reason"],
            )
            fingerprint = _capacity_fingerprint(finding)
            body_file = self.issue_dir / f"{fingerprint}.md"
            body = _render_capacity_body(finding=finding, fingerprint=fingerprint)
            redactions_path = repo_root / "tools" / "issue-discovery" / "config" / "redactions.yaml"
            if not redactions_path.is_file():
                raise ValueError("capacity issue generation requires the SCM redaction policy")
            body_file.write_text(
                Redactor.from_file(redactions_path).redact(body), encoding="utf-8"
            )
            candidates.append(
                IssueCandidate(
                    fingerprint=fingerprint,
                    title=f"{finding['summary']} ({fingerprint})",
                    labels=("bug",),
                    classification=finding["classification"],
                    phase=finding["observed"]["stage"],
                    body_file=body_file,
                    evidence=tuple(finding["evidence"]),
                    state=readiness.state,
                    confidence=readiness.confidence,
                    state_reason=readiness.reason,
                    working_branch=finding["observed"]["working_branch"],
                    observed_ref=finding["observed"]["observed_ref"],
                    scenario_id=finding["scenario_id"],
                    scenario_fingerprint=finding["scenario_fingerprint"],
                    run_id=finding["observed"]["run_id"],
                    destination_repo=finding["destination_repo"],
                    lifecycle_state="detected",
                )
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
                        working_branch=str(manifest.get("working_branch")) if manifest.get("working_branch") else None,
                        observed_ref=str(manifest.get("observed_ref")) if manifest.get("observed_ref") else None,
                        run_id=str(manifest.get("run_id")) if manifest.get("run_id") else None,
                        destination_repo="simple-compute-market",
                        lifecycle_state="detected",
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
            labels=("bug",),
            classification="workaround",
            phase=raw,
            body_file=body_file,
            evidence=("manifest.json", "workarounds.jsonl"),
            state=readiness.state,
            confidence=readiness.confidence,
            state_reason=readiness.reason,
            working_branch=str(manifest.get("working_branch")) if manifest.get("working_branch") else None,
            observed_ref=str(manifest.get("observed_ref")) if manifest.get("observed_ref") else None,
            run_id=str(manifest.get("run_id")) if manifest.get("run_id") else None,
            destination_repo="simple-compute-market",
            lifecycle_state="detected",
        )


class IssueRepository:
    def __init__(
        self,
        run_dir: Path,
        repo_root: Path | None = None,
        policy_root: Path | None = None,
    ) -> None:
        self.run_dir = run_dir
        self.repo_root = repo_root.resolve() if repo_root is not None else Path.cwd().resolve()
        self.policy_root = (
            policy_root.resolve() if policy_root is not None else self.repo_root
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
        destination = _candidate_repository(candidate)
        if destination is not None:
            command.extend(["--repo", destination])
        for label in candidate.get("labels", []):
            command.extend(["--label", str(label)])
        if not self._branch_is_authorized(candidate):
            return 2
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
            if candidate.get("lifecycle_state") == "detected":
                return self._record_capacity_occurrence(candidate, duplicate, body_path)
            print(f"duplicate issue exists: {duplicate.get('url') or duplicate.get('title')}")
            return 0

        completed = subprocess.run(
            command,
            check=False,
            text=True,
            cwd=self.repo_root,
            capture_output=True,
        )
        if completed.stdout:
            print(completed.stdout.strip())
        if completed.stderr:
            print(completed.stderr.strip())
        if completed.returncode == 0 and candidate.get("lifecycle_state") == "detected":
            issue_url = completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else None
            self._append_capacity_lifecycle(
                candidate,
                state="filed",
                detail="Created a branch-scoped GitHub issue.",
                issue_url=issue_url,
            )
        return completed.returncode

    def propose_fix(self, fingerprint: str, head_branch: str) -> Path:
        candidate = self.get(fingerprint)
        if (
            candidate.get("lifecycle_state") != "detected"
            or not candidate.get("scenario_id")
            or not candidate.get("scenario_fingerprint")
            or not candidate.get("run_id")
        ):
            raise ValueError("fix proposals require a capacity finding with branch authority")
        destination, base_branch, observed_ref = _capacity_target(candidate)
        if base_branch in _FORBIDDEN_BASE_BRANCHES:
            raise ValueError(f"unauthorized fix PR base: {base_branch}")
        allowed_prefix = f"fix/{fingerprint}"
        if head_branch in _FORBIDDEN_BASE_BRANCHES:
            raise ValueError("fix PR head cannot be dev or main")
        if head_branch != allowed_prefix and not head_branch.startswith(f"{allowed_prefix}-"):
            raise ValueError(f"fix PR head must begin with {allowed_prefix}")
        if head_branch == base_branch:
            raise ValueError("fix PR head and base must preserve inbound-only branch authority")
        proposal = {
            "schema_version": 1,
            "status": "proposal-only",
            "destination_repo": candidate["destination_repo"],
            "destination_repository": destination,
            "head_branch": head_branch,
            "base_branch": base_branch,
            "observed_ref": observed_ref,
            "scenario_id": candidate["scenario_id"],
            "scenario_fingerprint": candidate["scenario_fingerprint"],
            "run_id": candidate["run_id"],
            "fingerprint": fingerprint,
            "auto_merge": False,
        }
        path = self.run_dir / "issue-candidates" / f"{fingerprint}.fix-pr.json"
        path.write_text(json.dumps(proposal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        self._append_capacity_lifecycle(
            candidate,
            state="fix_in_progress",
            detail=f"Prepared a proposal-only child fix PR targeting {base_branch}.",
        )
        return path

    def transition(self, fingerprint: str, state: str, detail: str) -> None:
        candidate = self.get(fingerprint)
        if candidate.get("lifecycle_state") != "detected":
            raise ValueError("lifecycle transitions require a capacity or branch-scoped finding")
        finding = next(
            (
                item
                for item in _read_jsonl(self.run_dir / "capacity-findings.jsonl")
                if _capacity_fingerprint(item) == candidate["fingerprint"]
            ),
            None,
        )
        if finding is None:
            raise ValueError("capacity finding occurrence is missing")
        events = [
            item
            for item in _read_jsonl(self.run_dir / "issue-lifecycle.jsonl")
            if item.get("finding_id") == finding["finding_id"]
        ]
        current = str(events[-1]["state"]) if events else "detected"
        allowed = {
            "detected": {"triaged", "filed", "fix_in_progress"},
            "triaged": {"filed", "fix_in_progress"},
            "filed": {"updated", "reopened", "fix_in_progress"},
            "updated": {"updated", "fix_in_progress"},
            "reopened": {"updated", "fix_in_progress"},
            "fix_in_progress": {"fixed_unverified"},
            "fixed_unverified": {"verified"},
            "verified": {"closed"},
            "closed": {"reopened"},
        }
        if state not in allowed.get(current, set()):
            raise ValueError(f"invalid lifecycle transition: {current} -> {state}")
        from issue_discovery.capacity import append_lifecycle

        append_lifecycle(
            self.run_dir,
            finding=finding,
            state=state,
            detail=detail,
        )

    def _find_duplicate(self, candidate: dict[str, Any]) -> dict[str, Any] | bool | None:
        capacity_candidate = candidate.get("lifecycle_state") == "detected"
        command = [
            "gh",
            "issue",
            "list",
            "--state",
            "all" if capacity_candidate else "open",
            "--search",
            f"{candidate['fingerprint']} in:title",
            "--json",
            "number,title,state,url,body",
            "--limit",
            "10",
        ]
        destination = _candidate_repository(candidate)
        if destination is not None:
            command.extend(["--repo", destination])
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
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            if self._duplicate_matches(candidate, issue):
                return issue
        return False

    def _duplicate_matches(self, candidate: dict[str, Any], issue: dict[str, Any]) -> bool:
        working_branch = candidate.get("working_branch")
        destination_repo = candidate.get("destination_repo")
        scenario_id = candidate.get("scenario_id")
        scenario = candidate.get("scenario_fingerprint")
        if not working_branch:
            return True
        if str(candidate["fingerprint"]) not in str(issue.get("title", "")):
            return False
        marker = _context_marker(
            fingerprint=str(candidate["fingerprint"]),
            destination_repo=str(destination_repo) if destination_repo else None,
            working_branch=str(working_branch),
            scenario_id=str(scenario_id) if scenario_id else None,
            scenario_fingerprint=str(scenario) if scenario else None,
        )
        body = str(issue.get("body", ""))
        if marker in body:
            return True
        # Issues filed before the exact repository/scenario-id marker remain
        # eligible for one scoped update. The explicit --repo query supplies
        # repository authority; the new occurrence comment carries both new
        # machine-readable markers.
        legacy_marker = _legacy_context_marker(
            fingerprint=str(candidate["fingerprint"]),
            working_branch=str(working_branch),
            scenario_fingerprint=str(scenario) if scenario else None,
        )
        return legacy_marker in body

    def _branch_is_authorized(self, candidate: dict[str, Any]) -> bool:
        expected = candidate.get("working_branch")
        if not expected:
            return True
        try:
            destination, expected, observed_ref = _capacity_target(candidate)
        except ValueError as exc:
            print(str(exc))
            return False
        remote = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            check=False,
            text=True,
            cwd=self.repo_root,
            capture_output=True,
        )
        remote_identity = (
            _github_repository(remote.stdout) if remote.returncode == 0 else None
        )
        if remote_identity != destination:
            print(
                f"issue repository mismatch: expected {destination}, "
                f"found {remote_identity or 'unknown'}"
            )
            return False
        completed = subprocess.run(
            ["git", "branch", "--show-current"],
            check=False,
            text=True,
            cwd=self.repo_root,
            capture_output=True,
        )
        actual = completed.stdout.strip() if completed.returncode == 0 else ""
        if actual in _FORBIDDEN_BASE_BRANCHES:
            print(f"issue publication from default branch is forbidden: {actual}")
            return False
        if actual != expected:
            print(f"issue branch mismatch: expected {expected}, found {actual or 'unknown'}")
            return False
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            text=True,
            cwd=self.repo_root,
            capture_output=True,
        )
        actual_ref = head.stdout.strip() if head.returncode == 0 else ""
        if actual_ref != observed_ref:
            print(
                f"issue ref mismatch: expected {observed_ref}, "
                f"found {actual_ref or 'unknown'}"
            )
            return False
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            check=False,
            text=True,
            cwd=self.repo_root,
            capture_output=True,
        )
        if status.returncode != 0 or status.stdout.strip():
            print("issue publication requires the exact clean observed worktree")
            return False
        return True

    def _record_capacity_occurrence(
        self,
        candidate: dict[str, Any],
        issue: dict[str, Any],
        body_path: Path,
    ) -> int:
        number = issue.get("number")
        if not isinstance(number, int):
            print("duplicate capacity issue is missing its number")
            return 2
        state = str(issue.get("state", "")).upper()
        if state == "CLOSED":
            reopened = subprocess.run(
                [
                    "gh",
                    "issue",
                    "reopen",
                    str(number),
                    "--repo",
                    _candidate_repository(candidate, required=True),
                ],
                check=False,
                text=True,
                cwd=self.repo_root,
                capture_output=True,
            )
            if reopened.returncode != 0:
                print("failed to reopen matching capacity issue")
                return reopened.returncode
            lifecycle_state = "reopened"
            detail = "Reopened an exact branch-and-scenario capacity finding."
        else:
            lifecycle_state = "updated"
            detail = "Attached a new occurrence to an exact open branch-and-scenario issue."
        commented = subprocess.run(
            [
                "gh",
                "issue",
                "comment",
                str(number),
                "--body-file",
                str(body_path),
                "--repo",
                _candidate_repository(candidate, required=True),
            ],
            check=False,
            text=True,
            cwd=self.repo_root,
            capture_output=True,
        )
        if commented.returncode != 0:
            print("failed to attach the capacity occurrence")
            return commented.returncode
        self._append_capacity_lifecycle(
            candidate,
            state=lifecycle_state,
            detail=detail,
            issue_number=number,
            issue_url=str(issue.get("url")) if issue.get("url") else None,
        )
        print(f"capacity issue {lifecycle_state}: {issue.get('url') or number}")
        return 0

    def _append_capacity_lifecycle(
        self,
        candidate: dict[str, Any],
        *,
        state: str,
        detail: str,
        issue_number: int | None = None,
        issue_url: str | None = None,
    ) -> None:
        finding = next(
            (
                item
                for item in _read_jsonl(self.run_dir / "capacity-findings.jsonl")
                if _capacity_fingerprint(item) == candidate["fingerprint"]
            ),
            None,
        )
        if finding is None:
            return
        from issue_discovery.capacity import append_lifecycle

        append_lifecycle(
            self.run_dir,
            finding=finding,
            state=state,
            detail=detail,
            issue_number=issue_number,
            issue_url=issue_url,
        )

    def _body_is_redacted(self, body_path: Path) -> bool:
        redactions_path = self.policy_root / "tools" / "issue-discovery" / "config" / "redactions.yaml"
        if not redactions_path.is_file():
            print("SCM redaction policy is unavailable; refusing to create issue")
            return False
        body = body_path.read_text(encoding="utf-8")
        if Redactor.from_file(redactions_path).redact(body) == body:
            return True
        print("issue body still contains unredacted data; refusing to create issue")
        return False


def _render_capacity_body(*, finding: dict[str, Any], fingerprint: str) -> str:
    observed = finding["observed"]
    readiness = finding["filing_readiness"]
    marker = _context_marker(
        fingerprint=fingerprint,
        destination_repo=finding["destination_repo"],
        working_branch=observed["working_branch"],
        scenario_id=finding["scenario_id"],
        scenario_fingerprint=finding["scenario_fingerprint"],
    )
    occurrence_marker = _occurrence_marker(
        destination_repo=finding["destination_repo"],
        working_branch=observed["working_branch"],
        observed_ref=observed["observed_ref"],
        scenario_id=finding["scenario_id"],
        scenario_fingerprint=finding["scenario_fingerprint"],
        run_id=observed["run_id"],
        stage=observed["stage"],
    )
    lines = [
        f"# {finding['summary']}",
        "",
        marker,
        occurrence_marker,
        "",
        "## Filing Readiness",
        f"- State: `{readiness['state']}`",
        f"- Confidence: `{readiness['confidence']}`",
        f"- Reason: {readiness['reason']}",
        "",
        "## Capacity Context",
        f"- Frontier: `{finding['frontier']}`",
        f"- Scenario: `{finding['scenario_id']}`",
        f"- Scenario fingerprint: `{finding['scenario_fingerprint']}`",
        f"- Run id: `{observed['run_id']}`",
        f"- Stage: `{observed['stage']}`",
        "",
        "## Expected",
        finding["expected"],
        "",
        "## Actual",
        finding["actual"],
        "",
        "## Evidence",
    ]
    lines.extend(f"- `{item}`" for item in finding["evidence"])
    lines.extend(
        [
            "",
            "## Branch Authority",
            f"- Working branch: `{observed['working_branch']}`",
            f"- Observed ref: `{observed['observed_ref']}`",
            f"- Destination repository: `{finding['destination_repo']}`",
            "- Any fix PR must use an issue-specific child branch and target the working branch above.",
            "- This finding does not authorize promotion to `dev` or `main`.",
            "",
        ]
    )
    return "\n".join(lines)


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
    working_branch = manifest.get("working_branch")
    observed_ref = manifest.get("observed_ref")
    lines = [
        f"# {_title_for_phase(phase, fingerprint)}",
        "",
        _context_marker(
            fingerprint=fingerprint,
            destination_repo="simple-compute-market",
            working_branch=str(working_branch) if working_branch else None,
            scenario_id=None,
            scenario_fingerprint=None,
        ),
        _occurrence_marker(
            destination_repo="simple-compute-market",
            working_branch=str(working_branch) if working_branch else None,
            observed_ref=str(observed_ref) if observed_ref else None,
            scenario_id=None,
            scenario_fingerprint=None,
            run_id=str(manifest.get("run_id")) if manifest.get("run_id") else None,
            stage=str(phase.get("id")) if phase.get("id") else None,
        ),
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
            f"- Working branch: `{working_branch}`",
            f"- Observed ref: `{observed_ref}`",
            "",
        ]
    )
    return "\n".join(lines)


def _capacity_fingerprint(finding: dict[str, Any]) -> str:
    # The producer-supplied value identifies the defect. Repository, branch,
    # and scenario are occurrence context: issue lookup scopes the GitHub query
    # to the authorized destination repository and checks the exact context
    # marker in the issue body instead of mutating the defect identity.
    return str(finding["fingerprint"])


def _context_marker(
    *,
    fingerprint: str,
    destination_repo: str | None,
    working_branch: str | None,
    scenario_id: str | None,
    scenario_fingerprint: str | None,
) -> str:
    return _machine_marker(
        "scope",
        {
            "fingerprint": fingerprint,
            "repository": _repository_name(destination_repo),
            "working_branch": working_branch or "unknown",
            "scenario_id": scenario_id or "none",
            "scenario_fingerprint": scenario_fingerprint or "none",
        },
    )


def _occurrence_marker(
    *,
    destination_repo: str | None,
    working_branch: str | None,
    observed_ref: str | None,
    scenario_id: str | None,
    scenario_fingerprint: str | None,
    run_id: str | None,
    stage: str | None,
) -> str:
    return _machine_marker(
        "occurrence",
        {
            "repository": _repository_name(destination_repo),
            "working_branch": working_branch or "unknown",
            "observed_ref": observed_ref or "unknown",
            "scenario_id": scenario_id or "none",
            "scenario_fingerprint": scenario_fingerprint or "none",
            "run_id": run_id or "unknown",
            "stage": stage or "unknown",
        },
    )


def _machine_marker(kind: str, payload: dict[str, str]) -> str:
    serialized = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    # Keep even adversarial free-text metadata inside one HTML comment while
    # preserving its exact JSON value when decoded.
    serialized = serialized.replace("--", "\\u002d\\u002d")
    return f"<!-- scm-issue-discovery-{kind} {serialized} -->"


def _legacy_context_marker(
    *,
    fingerprint: str,
    working_branch: str,
    scenario_fingerprint: str | None,
) -> str:
    scenario = scenario_fingerprint or "none"
    return (
        "<!-- scm-issue-discovery "
        f"fingerprint={fingerprint} branch={working_branch} scenario={scenario} -->"
    )


def _repository_name(destination_repo: str | None) -> str:
    target = _CAPACITY_REPOSITORIES.get(str(destination_repo))
    return target[0] if target is not None else "unknown"


def _capacity_target(candidate: dict[str, Any]) -> tuple[str, str, str]:
    destination_repo = str(candidate.get("destination_repo") or "")
    target = _CAPACITY_REPOSITORIES.get(destination_repo)
    if target is None:
        raise ValueError(
            f"candidate destination repository is not authorized: "
            f"{destination_repo or 'unknown'}"
        )
    destination, required_branch = target
    working_branch = str(candidate.get("working_branch") or "")
    if working_branch in _FORBIDDEN_BASE_BRANCHES:
        raise ValueError(f"candidate working branch is forbidden: {working_branch}")
    if working_branch != required_branch:
        raise ValueError(
            f"candidate working branch is not authorized for {destination}: "
            f"{working_branch or 'unknown'}"
        )
    observed_ref = str(candidate.get("observed_ref") or "")
    if len(observed_ref) != 40 or any(
        character not in "0123456789abcdef" for character in observed_ref
    ):
        raise ValueError("candidate observed ref must be an exact lowercase commit SHA")
    return destination, working_branch, observed_ref


def _candidate_repository(
    candidate: dict[str, Any], *, required: bool = False
) -> str | None:
    if not candidate.get("working_branch") and not required:
        return None
    try:
        destination, _, _ = _capacity_target(candidate)
    except ValueError:
        if required:
            raise
        return None
    return destination


def _github_repository(remote: str) -> str | None:
    value = remote.strip()
    if value.startswith("git@github.com:"):
        path = value.removeprefix("git@github.com:")
    else:
        parsed = urlparse(value)
        if parsed.hostname != "github.com":
            return None
        path = parsed.path.lstrip("/")
    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return f"github.com/{parts[0]}/{parts[1]}".lower()


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


def _merge_evidence(existing: tuple[str, ...], new: list[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys([*existing, *new]))


def _title_for_phase(phase: dict[str, Any], fingerprint: str) -> str:
    return f"{phase.get('name', phase['id'])} failed ({fingerprint})"


def _labels_for_phase(phase: dict[str, Any]) -> tuple[str, ...]:
    # Both campaign repositories currently have only the default GitHub labels.
    # Classification and capacity-frontier details remain structured in the
    # candidate/body instead of making live filing depend on undeclared labels.
    return ("bug",)


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
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def _shell_quote(value: str) -> str:
    if value.replace("-", "").replace("_", "").replace("/", "").replace(".", "").isalnum():
        return value
    return "'" + value.replace("'", "'\"'\"'") + "'"
