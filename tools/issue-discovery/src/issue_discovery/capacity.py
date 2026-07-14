from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema


SCM_BRANCH = "feat/issue-discovery-harness"
INFRA_BRANCH = "tools/agent-orchestration-scratch"


class CapacityValidationError(RuntimeError):
    pass


def _schema_path(repo_root: Path, name: str) -> Path:
    return repo_root / "tools" / "issue-discovery" / "schemas" / name


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise CapacityValidationError(f"expected a JSON object: {path}")
    return value


def _schema_errors(value: dict[str, Any], schema_path: Path) -> list[str]:
    schema = _read_object(schema_path)
    validator = jsonschema.Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path)):
        location = ".".join(str(item) for item in error.absolute_path) or "$"
        errors.append(f"{location}: {error.message}")
    return errors


def validate_scenario(scenario: dict[str, Any], repo_root: Path) -> None:
    errors = _schema_errors(scenario, _schema_path(repo_root, "capacity-scenario.schema.json"))
    if not errors:
        wave = scenario["wave"]
        listing = scenario["listing"]
        distribution = listing["seller_distribution"]
        if wave["requests"] != wave["expected_successes"] + wave["expected_scarcity"]:
            errors.append("wave.requests must equal expected_successes plus expected_scarcity")
        if wave["requests"] > wave["buyers"]:
            errors.append("one-request-per-buyer waves cannot exceed buyer count")
        if wave["expected_successes"] > listing["count"]:
            errors.append("expected successes cannot exceed the frozen listing count")
        if wave["requests"] and wave["sellers"] < 1:
            errors.append("a request wave requires at least one seller")
        if len(distribution) != wave["sellers"]:
            errors.append("listing.seller_distribution must have one entry per seller")
        if sum(distribution) != listing["count"]:
            errors.append("listing.seller_distribution must sum to listing.count")
    if errors:
        raise CapacityValidationError("scenario validation failed:\n- " + "\n- ".join(errors))


def validate_finding(finding: dict[str, Any], repo_root: Path) -> None:
    errors = _schema_errors(finding, _schema_path(repo_root, "capacity-finding.schema.json"))
    if not errors:
        branch = finding["observed"]["working_branch"]
        classification = finding["classification"]
        destination = finding["destination_repo"]
        if classification in {"public-product", "public-harness"}:
            if destination != "simple-compute-market" or branch != SCM_BRANCH:
                errors.append("public findings must target the SCM working branch")
        if classification == "private-infra":
            if destination != "compute-market-internal-infra" or branch != INFRA_BRANCH:
                errors.append("private findings must target the infra working branch")
        for item in finding["evidence"]:
            path = Path(item)
            if path.is_absolute() or ".." in path.parts:
                errors.append("evidence references must be relative and cannot traverse parents")
    if errors:
        raise CapacityValidationError("finding validation failed:\n- " + "\n- ".join(errors))


def validate_scenario_file(path: Path, repo_root: Path) -> dict[str, Any]:
    scenario = _read_object(path)
    validate_scenario(scenario, repo_root)
    return scenario


def scenario_sha256(scenario: dict[str, Any]) -> str:
    """Return the SHA-256 of the scenario's canonical JSON representation."""
    canonical = (
        json.dumps(scenario, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def validate_finding_file(path: Path, repo_root: Path) -> dict[str, Any]:
    finding = _read_object(path)
    validate_finding(finding, repo_root)
    return finding


def ingest_finding(run_dir: Path, finding_path: Path, repo_root: Path) -> dict[str, Any]:
    finding = validate_finding_file(finding_path, repo_root)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    observed = finding["observed"]
    if manifest_path.exists():
        manifest = _read_object(manifest_path)
        for key, expected in (
            ("run_id", observed["run_id"]),
            ("working_branch", observed["working_branch"]),
            ("observed_ref", observed["observed_ref"]),
        ):
            if manifest.get(key) != expected:
                raise CapacityValidationError(
                    f"capacity finding {key} does not match the existing run manifest"
                )
    else:
        manifest = {
            "schema_version": 1,
            "campaign": "capacity",
            "run_id": observed["run_id"],
            "mode": "capacity-finding-ingest",
            "status": "finding_detected",
            "repo_root": str(repo_root.resolve()),
            "working_branch": observed["working_branch"],
            "observed_ref": observed["observed_ref"],
            "started_at": None,
            "completed_at": None,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    findings_path = run_dir / "capacity-findings.jsonl"
    existing = [
        json.loads(line)
        for line in findings_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ] if findings_path.exists() else []
    matches = [item for item in existing if item.get("finding_id") == finding["finding_id"]]
    if matches:
        if matches[0] != finding:
            raise CapacityValidationError("finding_id already exists with different content")
        return finding
    with findings_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(finding, sort_keys=True) + "\n")
    append_lifecycle(
        run_dir,
        finding=finding,
        state="detected",
        detail="Validated immutable capacity finding occurrence.",
    )
    from issue_discovery.issues import IssuePacketGenerator

    IssuePacketGenerator(run_dir, repo_root=repo_root).generate()
    return finding


def append_lifecycle(
    run_dir: Path,
    *,
    finding: dict[str, Any],
    state: str,
    detail: str,
    issue_number: int | None = None,
    issue_url: str | None = None,
) -> None:
    event = {
        "schema_version": 1,
        "finding_id": finding["finding_id"],
        "fingerprint": finding["fingerprint"],
        "destination_repo": finding["destination_repo"],
        "scenario_id": finding["scenario_id"],
        "scenario_fingerprint": finding["scenario_fingerprint"],
        "run_id": finding["observed"]["run_id"],
        "stage": finding["observed"]["stage"],
        "working_branch": finding["observed"]["working_branch"],
        "observed_ref": finding["observed"]["observed_ref"],
        "state": state,
        "detail": detail,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "issue_number": issue_number,
        "issue_url": issue_url,
    }
    with (run_dir / "issue-lifecycle.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
