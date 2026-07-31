from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any

from jsonschema import Draft202012Validator
import pytest

from issue_discovery.capacity import (
    CapacityValidationError,
    canonical_json_bytes,
    canonical_sha256,
)
from issue_discovery.capacity_findings import (
    CAPACITY_FINDING_FINGERPRINT_DOMAIN,
    CAPACITY_FINDING_INGEST_LOCK_NAME,
    CAPACITY_FINDING_INDEX_NAME,
    CAPACITY_FINDING_LIFECYCLE_NAME,
    CAPACITY_FINDING_MANIFEST_NAME,
    CAPACITY_FINDING_SOURCE_NAME,
    _write_new_private_file,
    capacity_finding_fingerprint_input,
    capacity_finding_ingest_lock,
    capacity_finding_index_record,
    derive_capacity_finding_fingerprint,
    ingest_capacity_finding,
    load_capacity_finding_index_artifacts,
    read_capacity_finding_private_file,
    render_finding_occurrence,
    replace_capacity_finding_private_file,
    require_validated_capacity_finding,
    validate_capacity_finding,
    validate_capacity_finding_index_record,
)
from issue_discovery.capacity_outcomes import (
    ValidatedCapacityResult,
    _VALIDATED_CAPACITY_RESULT_TOKEN,
)
from issue_discovery.issues import IssuePacketGenerator
from issue_discovery.publication import (
    FINDING_V2_CONSUMED_REF,
    ValidatedPublicationPreview,
    load_issue_publication_preview,
    observe_git_publication_authority,
    select_issue_publication_action,
    validate_publication_observation,
)
from issue_discovery.runner import DiscoveryRunner


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _git(path: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=path,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_with_input(path: Path, content: str, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=path,
        check=True,
        capture_output=True,
        input=content,
        text=True,
    )
    return completed.stdout.strip()


def _commit_tree(
    repository: Path,
    tree: str,
    *parents: str,
    message: str,
) -> str:
    arguments = ["commit-tree", tree]
    for parent in parents:
        arguments.extend(["-p", parent])
    return _git_with_input(repository, f"{message}\n", *arguments)


@pytest.fixture
def finding_authority(tmp_path: Path) -> dict[str, Any]:
    authority = tmp_path / "authority"
    authority.mkdir()
    _git(authority, "init")
    _git(authority, "config", "user.name", "Capacity Test")
    _git(authority, "config", "user.email", "capacity@example.invalid")
    _git(
        authority,
        "remote",
        "add",
        "origin",
        "https://github.com/arkhai-io/simple-compute-market",
    )
    schema_destination = (
        authority
        / "tools"
        / "issue-discovery"
        / "schemas"
        / "capacity-finding.schema.json"
    )
    schema_destination.parent.mkdir(parents=True)
    shutil.copyfile(
        repo_root()
        / "tools"
        / "issue-discovery"
        / "schemas"
        / "capacity-finding.schema.json",
        schema_destination,
    )
    for publication_schema in (
        "finding-publication-action.schema.json",
        "finding-publication-authority.schema.json",
        "finding-publication-git-observation.schema.json",
        "finding-publication-observation.schema.json",
        "finding-publication-preview.schema.json",
    ):
        shutil.copyfile(
            repo_root() / "tools" / "issue-discovery" / "schemas" / publication_schema,
            schema_destination.parent / publication_schema,
        )
    redaction_destination = (
        authority / "tools" / "issue-discovery" / "config" / "redactions.yaml"
    )
    redaction_destination.parent.mkdir(parents=True)
    shutil.copyfile(
        repo_root() / "tools" / "issue-discovery" / "config" / "redactions.yaml",
        redaction_destination,
    )
    (authority / "base.txt").write_text("base\n", encoding="utf-8")
    _git(authority, "add", ".")
    _git(authority, "commit", "-m", "base")
    base_ref = _git(authority, "rev-parse", "HEAD")

    _git(authority, "checkout", "-b", "dev")
    (authority / "upstream.txt").write_text("upstream\n", encoding="utf-8")
    _git(authority, "add", "upstream.txt")
    _git(authority, "commit", "-m", "upstream")
    upstream_ref = _git(authority, "rev-parse", "HEAD")

    _git(
        authority,
        "checkout",
        "-b",
        "feat/issue-discovery-harness",
        base_ref,
    )
    (authority / "working.txt").write_text("working\n", encoding="utf-8")
    _git(authority, "add", "working.txt")
    _git(authority, "commit", "-m", "working")
    _git(authority, "merge", "--no-ff", "dev", "-m", "merge dev")
    inbound_merge_ref = _git(authority, "rev-parse", "HEAD")
    (authority / "contract.txt").write_text("contract\n", encoding="utf-8")
    _git(authority, "add", "contract.txt")
    _git(authority, "commit", "-m", "contract")
    working_ref = _git(authority, "rev-parse", "HEAD")

    run_dir = tmp_path / "run"
    evidence_dir = run_dir / "evidence"
    evidence_dir.mkdir(parents=True)
    run_dir.chmod(0o700)
    evidence_path = evidence_dir / "observer.json"
    evidence_path.write_text(
        '{"diagnostic_code":"seller-provisioning-error","phase":"provisioning"}\n',
        encoding="utf-8",
    )
    return {
        "repo": authority,
        "run_dir": run_dir,
        "evidence_path": evidence_path,
        "upstream_ref": upstream_ref,
        "inbound_merge_ref": inbound_merge_ref,
        "working_ref": working_ref,
    }


@pytest.fixture
def private_authority(tmp_path: Path) -> dict[str, str | Path]:
    repository = tmp_path / "private-authority"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.name", "Capacity Test")
    _git(repository, "config", "user.email", "capacity@example.invalid")
    _git(
        repository,
        "remote",
        "add",
        "origin",
        "https://github.com/arkhai-io/compute-market-internal-infra",
    )
    (repository / "base.txt").write_text("base\n", encoding="utf-8")
    _git(repository, "add", "base.txt")
    _git(repository, "commit", "-m", "base")
    base_ref = _git(repository, "rev-parse", "HEAD")

    _git(repository, "checkout", "-b", "main")
    (repository / "upstream.txt").write_text("upstream\n", encoding="utf-8")
    _git(repository, "add", "upstream.txt")
    _git(repository, "commit", "-m", "upstream")
    upstream_ref = _git(repository, "rev-parse", "HEAD")

    _git(
        repository,
        "checkout",
        "-b",
        "tools/agent-orchestration-scratch",
        base_ref,
    )
    (repository / "working.txt").write_text("working\n", encoding="utf-8")
    _git(repository, "add", "working.txt")
    _git(repository, "commit", "-m", "working")
    _git(repository, "merge", "--no-ff", "main", "-m", "merge main")
    inbound_merge_ref = _git(repository, "rev-parse", "HEAD")
    (repository / "contract.txt").write_text("contract\n", encoding="utf-8")
    _git(repository, "add", "contract.txt")
    _git(repository, "commit", "-m", "contract")
    working_ref = _git(repository, "rev-parse", "HEAD")
    return {
        "repo": repository,
        "upstream_ref": upstream_ref,
        "inbound_merge_ref": inbound_merge_ref,
        "working_ref": working_ref,
    }


def _fault_outcome() -> dict[str, Any]:
    return {
        "request_id": "request-1",
        "outcome_kind": "fault",
        "deal_reference": {
            "request_id": "request-1",
            "seller_slot": "seller-1",
            "listing_slot": "listing-1",
        },
        "capacity_reservation_id": None,
        "fulfillment_id": None,
        "settlement_record": None,
        "provisioned_resource_id": None,
        "allocation_id": None,
        "provisioning_job_id": None,
        "commercial_resolution": {
            "deal_state": "failed-terminal",
            "zero_active_claims": True,
            "zero_active_locks": True,
        },
        "request_cleanup": {
            "teardown_complete": True,
            "zero_active_residue": True,
        },
        "failure_category": "provisioning-error",
        "fault_observation": {
            "phase": "provisioning",
            "timed_out": False,
            "diagnostic_code": "seller-provisioning-error",
        },
    }


def _clean_cleanup() -> dict[str, Any]:
    return {
        "terminal_correlations_complete": True,
        "teardown_complete": True,
        "residue_counts": {
            "capacity_reservations": 0,
            "vms": 0,
            "gpu_assignments": 0,
            "active_claims": 0,
            "active_locks": 0,
        },
        "reversible_components": [{"component": "vms", "exactly_equal": True}],
        "accounting_deltas": [
            {
                "category": "wallet-accounting",
                "reconciled": True,
                "active_lock": False,
                "unexplained_value": False,
            }
        ],
        "ready_for_next_stage": True,
    }


def _validated_result(
    authority: dict[str, Any],
    *,
    outcomes: list[dict[str, Any]] | None = None,
    expected: dict[str, int] | None = None,
    observed: dict[str, int] | None = None,
    cleanup: dict[str, Any] | None = None,
    cleanup_passed: bool = True,
    derived_faults: tuple[str, ...] = (),
) -> ValidatedCapacityResult:
    request_outcomes = outcomes or [_fault_outcome()]
    expected_counts = expected or {
        "vm-succeeded": 1,
        "capacity-refused": 0,
        "fault": 0,
    }
    observed_counts = observed or {
        "vm-succeeded": 0,
        "capacity-refused": 0,
        "fault": 1,
    }
    cleanup_value = cleanup or _clean_cleanup()
    result_value = {
        "schema_version": 2,
        "result_id": "q0-b1-s1-g1-measured-result",
        "scm_ref": authority["working_ref"],
        "profile_stage_id": "q0-b1-s1-g1-measured",
        "profile_stage_sha256": "2" * 64,
        "scenario_id": "b1-s1-g1",
        "scenario_sha256": "1" * 64,
        "expected_outcomes": expected_counts,
        "observed_outcomes": observed_counts,
        "request_outcomes": request_outcomes,
        "cleanup": cleanup_value,
        "stage_assessment": {
            "cleanup_passed": cleanup_passed,
            "derived_faults": list(derived_faults),
        },
    }
    canonical_bytes = canonical_json_bytes(result_value)
    return ValidatedCapacityResult(
        result_id="q0-b1-s1-g1-measured-result",
        scm_ref=authority["working_ref"],
        profile_stage_id="q0-b1-s1-g1-measured",
        profile_stage_sha256="2" * 64,
        scenario_id="b1-s1-g1",
        scenario_sha256="1" * 64,
        execution_boundary="real-measured",
        actor_trigger="agent-triggered",
        canonical_sha256=hashlib.sha256(canonical_bytes).hexdigest(),
        started_at=datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        terminal_observed_at=datetime(2026, 7, 30, 10, 0, 10, tzinfo=UTC),
        cleanup_completed_at=datetime(2026, 7, 30, 10, 0, 11, tzinfo=UTC),
        progression_ready_at=datetime(2026, 7, 30, 10, 0, 12, tzinfo=UTC),
        request_processing_passed=True,
        simultaneous_fulfillment_count=0,
        provisioning_passed=False,
        correctness_passed=False,
        load_generator_passed=True,
        cleanup_passed=cleanup_passed,
        stage_passed=False,
        agent_capacity_evidence=True,
        eligible_for_capacity_frontier=True,
        derived_faults=derived_faults,
        outcome_kinds=tuple(
            str(outcome["outcome_kind"]) for outcome in request_outcomes
        ),
        admitted_seller_identities=None,
        admitted_service_instances=None,
        repo_root=authority["repo"],
        _canonical_bytes=canonical_bytes,
        _validation_token=_VALIDATED_CAPACITY_RESULT_TOKEN,
    )


def _correlation(outcome: dict[str, Any]) -> dict[str, Any]:
    settlement = outcome["settlement_record"]
    return {
        "request_id": outcome["request_id"],
        "outcome_kind": outcome["outcome_kind"],
        "deal_reference_sha256": canonical_sha256(outcome["deal_reference"]),
        "capacity_reservation_id": outcome["capacity_reservation_id"],
        "fulfillment_id": outcome["fulfillment_id"],
        "settlement_record_sha256": (
            canonical_sha256(settlement) if settlement is not None else None
        ),
        "provisioned_resource_id": outcome["provisioned_resource_id"],
        "allocation_id": outcome["allocation_id"],
        "provisioning_job_id": outcome["provisioning_job_id"],
        "commercial_resolution_sha256": canonical_sha256(
            outcome["commercial_resolution"]
        ),
        "request_cleanup_sha256": canonical_sha256(outcome["request_cleanup"]),
    }


def _finding(
    authority: dict[str, Any],
    result: ValidatedCapacityResult,
) -> dict[str, Any]:
    outcome = result.result["request_outcomes"][0]
    evidence_path = authority["evidence_path"]
    return {
        "schema_version": 2,
        "finding_id": "capacity-occurrence-001",
        "destination_repo": "simple-compute-market",
        "classification": "public-product",
        "frontier": "provisioning",
        "scenario_id": result.scenario_id,
        "scenario_sha256": result.scenario_sha256,
        "profile_stage_id": result.profile_stage_id,
        "profile_stage_sha256": result.profile_stage_sha256,
        "result_id": result.result_id,
        "result_sha256": result.canonical_sha256,
        "scm_contract_ref": result.scm_ref,
        "defect_semantics": {
            "expected_outcome_kind": "vm-succeeded",
            "actual_fault_category": "provisioning-error",
            "failure_code": "seller-provisioning-error",
            "stable_signature": "seller provisioning terminated before vm output",
            "lifecycle_phase": "provisioning",
        },
        "summary": "Seller provisioning terminated before VM output",
        "expected": "One real KVM/Ansible whole-GPU VM reaches guest output.",
        "actual": "Provisioning terminated before VM output.",
        "observed_outcome": {
            "request_ids": ["request-1"],
            "outcome_kind": "fault",
            "diagnostic_code": "seller-provisioning-error",
        },
        "durable_correlations": [_correlation(outcome)],
        "observed_authority": {
            "run_id": "capacity-run-001",
            "stage_id": result.profile_stage_id,
            "working_branch": "feat/issue-discovery-harness",
            "working_ref": authority["working_ref"],
            "upstream_branch": "dev",
            "upstream_ref": authority["upstream_ref"],
            "inbound_merge_ref": authority["inbound_merge_ref"],
            "reconciliation_epoch_id": "dev-reconciliation-20260730",
            "observed_at": "2026-07-30T10:00:13.000000Z",
        },
        "evidence": [
            {
                "path": evidence_path.relative_to(authority["run_dir"]).as_posix(),
                "sha256": hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            }
        ],
        "filing_readiness": {
            "terminal_correlations_complete": True,
            "teardown_complete": True,
            "zero_active_residue": True,
            "baseline_equivalent": True,
            "ready_to_file": True,
        },
    }


def test_current_schema_is_closed_v2() -> None:
    schema = json.loads(
        (
            repo_root()
            / "tools"
            / "issue-discovery"
            / "schemas"
            / "capacity-finding.schema.json"
        ).read_text(encoding="utf-8")
    )

    Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema_version"] == {"const": 2}
    assert "fingerprint" not in schema["properties"]
    assert schema["additionalProperties"] is False
    assert set(schema["$defs"]["evidence"]["required"]) == {
        "path",
        "sha256",
    }


def test_all_four_classifications_have_closed_destination_fixtures() -> None:
    schema = json.loads(
        (
            repo_root()
            / "tools"
            / "issue-discovery"
            / "schemas"
            / "capacity-finding.schema.json"
        ).read_text(encoding="utf-8")
    )
    fixtures = json.loads(
        (
            Path(__file__).parent
            / "fixtures"
            / "capacity"
            / "v2"
            / "findings"
            / "classification-findings.json"
        ).read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)

    assert {item["classification"] for item in fixtures} == {
        "public-product",
        "public-harness",
        "private-orchestration",
        "environment-provider",
    }
    for finding in fixtures:
        assert list(validator.iter_errors(finding)) == []


def test_fingerprint_uses_only_normalized_defect_identity(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    original = _finding(finding_authority, result)
    occurrence = deepcopy(original)
    occurrence["finding_id"] = "capacity-occurrence-002"
    occurrence["profile_stage_id"] = "different-profile-stage"
    occurrence["profile_stage_sha256"] = "a" * 64
    occurrence["result_id"] = "different-result"
    occurrence["result_sha256"] = "b" * 64
    occurrence["scm_contract_ref"] = "c" * 40
    occurrence["observed_authority"]["run_id"] = "different-run"
    occurrence["observed_authority"]["working_ref"] = "d" * 40
    occurrence["evidence"][0]["path"] = "evidence/other.json"
    occurrence["evidence"][0]["sha256"] = "e" * 64
    occurrence["durable_correlations"][0]["fulfillment_id"] = "different-id"

    identity = capacity_finding_fingerprint_input(original)
    assert set(identity) == {
        "destination_repo",
        "classification",
        "scenario_id",
        "scenario_sha256",
        "frontier",
        "failure_code",
        "stable_signature",
        "expected_outcome_kind",
        "actual_fault_category",
        "lifecycle_phase",
    }
    expected = (
        "capacity-"
        + hashlib.sha256(
            CAPACITY_FINDING_FINGERPRINT_DOMAIN + canonical_json_bytes(identity)
        ).hexdigest()
    )
    assert (
        expected
        == "capacity-2a624ff7300b1b85aa063d7902b786845f4fd29735a3eb636ac4bf33c843339d"
    )
    assert derive_capacity_finding_fingerprint(original) == expected
    assert derive_capacity_finding_fingerprint(occurrence) == expected

    changed_scenario = deepcopy(original)
    changed_scenario["scenario_id"] = "b2-s1-g1"
    assert derive_capacity_finding_fingerprint(changed_scenario) != expected
    included_mutations = {
        "destination_repo": "compute-market-internal-infra",
        "classification": "public-harness",
        "scenario_id": "b2-s1-g1",
        "scenario_sha256": "9" * 64,
        "frontier": "request-processing",
        "failure_code": "different-failure",
        "stable_signature": "different canonical signature",
        "expected_outcome_kind": "capacity-refused",
        "actual_fault_category": "policy-denial",
        "lifecycle_phase": "reservation",
    }
    for field_name, replacement in included_mutations.items():
        changed = deepcopy(original)
        if field_name in changed:
            changed[field_name] = replacement
        else:
            changed["defect_semantics"][field_name] = replacement
        assert derive_capacity_finding_fingerprint(changed) != expected, field_name


def test_stable_signature_must_already_be_normalized(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["defect_semantics"]["stable_signature"] = (
        "  Seller  Provisioning TERMINATED Before VM Output "
    )

    with pytest.raises(CapacityValidationError, match="NFKC-normalized"):
        capacity_finding_fingerprint_input(value)
    with pytest.raises(CapacityValidationError, match="NFKC-normalized"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_stable_signature_rejects_unicode_normalization_case_and_space_drift(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["defect_semantics"]["stable_signature"] = (
        "  Cafe\u0301\u2003SELLER\tPROVISIONING  "
    )

    with pytest.raises(CapacityValidationError, match="NFKC-normalized"):
        capacity_finding_fingerprint_input(value)

    value["defect_semantics"]["stable_signature"] = "café seller provisioning"
    assert capacity_finding_fingerprint_input(value)["stable_signature"] == (
        "café seller provisioning"
    )


def test_fingerprint_primitive_and_replay_reject_fault_expected_kind(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )
    record = capacity_finding_index_record(validated)

    noncanonical = deepcopy(value)
    noncanonical["defect_semantics"]["stable_signature"] = "  NOT Normalized "
    with pytest.raises(CapacityValidationError, match="NFKC-normalized"):
        validate_capacity_finding_index_record(
            record,
            noncanonical,
            repo_root=finding_authority["repo"],
        )

    fault_expected = deepcopy(value)
    fault_expected["defect_semantics"]["expected_outcome_kind"] = "fault"
    with pytest.raises(CapacityValidationError, match="expected_outcome_kind"):
        capacity_finding_fingerprint_input(fault_expected)
    with pytest.raises(CapacityValidationError):
        validate_capacity_finding_index_record(
            record,
            fault_expected,
            repo_root=finding_authority["repo"],
        )


def test_valid_finding_binds_result_git_evidence_and_readiness(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)

    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )

    assert validated.finding == value
    assert validated.result_sha256 == result.canonical_sha256
    assert validated.ready_to_file is True
    assert validated.fingerprint.startswith("capacity-")
    assert require_validated_capacity_finding(validated) == value


@pytest.mark.parametrize(
    ("field_name", "changed"),
    [
        ("scenario_id", "b2-s1-g1"),
        ("scenario_sha256", "a" * 64),
        ("profile_stage_id", "q0-b2-s1-g1-measured"),
        ("profile_stage_sha256", "b" * 64),
        ("result_id", "q0-b2-s1-g1-measured-result"),
        ("result_sha256", "c" * 64),
        ("scm_contract_ref", "d" * 40),
    ],
)
def test_exact_result_authority_cannot_drift(
    finding_authority: dict[str, Any],
    field_name: str,
    changed: str,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value[field_name] = changed

    with pytest.raises(CapacityValidationError):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_producer_fingerprint_is_rejected_by_closed_schema(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["fingerprint"] = "capacity-" + "f" * 64

    with pytest.raises(CapacityValidationError, match="fingerprint"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_branch_mapping_and_inbound_merge_are_exact(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["observed_authority"]["inbound_merge_ref"] = None

    with pytest.raises(CapacityValidationError, match="first-parent"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )

    value = _finding(finding_authority, result)
    value["observed_authority"]["working_branch"] = "tools/agent-orchestration-scratch"
    with pytest.raises(CapacityValidationError, match="working_branch"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_inbound_merge_requires_exact_second_parent(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["observed_authority"]["inbound_merge_ref"] = authority_ref = _git(
        finding_authority["repo"],
        "rev-parse",
        f"{finding_authority['inbound_merge_ref']}^1",
    )
    assert authority_ref != finding_authority["inbound_merge_ref"]

    with pytest.raises(CapacityValidationError, match="two-parent merge"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_null_inbound_accepts_exact_upstream_on_working_first_parent(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["observed_authority"]["upstream_ref"] = finding_authority["inbound_merge_ref"]
    value["observed_authority"]["inbound_merge_ref"] = None

    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )

    assert validated.finding["observed_authority"]["inbound_merge_ref"] is None


@pytest.mark.parametrize(
    ("graph_kind", "message"),
    [
        ("wrong-second-parent", "second parent"),
        ("off-first-parent", "working first-parent chain"),
        ("octopus", "two-parent merge"),
    ],
)
def test_recorded_inbound_rejects_invalid_raw_parent_topology(
    finding_authority: dict[str, Any],
    graph_kind: str,
    message: str,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    repository = finding_authority["repo"]
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    contract_ref = finding_authority["working_ref"]
    upstream_ref = finding_authority["upstream_ref"]
    base_ref = _git(repository, "rev-parse", f"{contract_ref}^1^1^1")

    if graph_kind == "wrong-second-parent":
        inbound_ref = _commit_tree(
            repository,
            tree,
            contract_ref,
            base_ref,
            message="wrong second parent",
        )
        working_ref = inbound_ref
    elif graph_kind == "off-first-parent":
        inbound_ref = _commit_tree(
            repository,
            tree,
            contract_ref,
            upstream_ref,
            message="valid merge on side branch",
        )
        working_ref = _commit_tree(
            repository,
            tree,
            contract_ref,
            inbound_ref,
            message="side-parent working merge",
        )
    else:
        inbound_ref = _commit_tree(
            repository,
            tree,
            contract_ref,
            upstream_ref,
            base_ref,
            message="octopus merge",
        )
        working_ref = inbound_ref

    value["observed_authority"]["working_ref"] = working_ref
    value["observed_authority"]["inbound_merge_ref"] = inbound_ref
    with pytest.raises(CapacityValidationError, match=message):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=repository,
            evidence_root=finding_authority["run_dir"],
        )


def test_public_contract_ref_on_only_a_side_parent_is_rejected(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    repository = finding_authority["repo"]
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    upstream_ref = finding_authority["upstream_ref"]
    mainline_ref = _commit_tree(
        repository,
        tree,
        upstream_ref,
        message="mainline without public contract",
    )
    working_ref = _commit_tree(
        repository,
        tree,
        mainline_ref,
        finding_authority["working_ref"],
        message="contract only on side parent",
    )
    value["observed_authority"]["working_ref"] = working_ref
    value["observed_authority"]["inbound_merge_ref"] = None

    with pytest.raises(CapacityValidationError, match="scm_contract_ref"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=repository,
            evidence_root=finding_authority["run_dir"],
        )


@pytest.mark.parametrize(
    "classification",
    ["private-orchestration", "environment-provider"],
)
def test_private_destination_uses_internal_git_authority_without_cross_repo_ancestry(
    finding_authority: dict[str, Any],
    private_authority: dict[str, str | Path],
    classification: str,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["destination_repo"] = "compute-market-internal-infra"
    value["classification"] = classification
    value["observed_authority"].update(
        {
            "working_branch": "tools/agent-orchestration-scratch",
            "working_ref": private_authority["working_ref"],
            "upstream_branch": "main",
            "upstream_ref": private_authority["upstream_ref"],
            "inbound_merge_ref": private_authority["inbound_merge_ref"],
        }
    )

    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=Path(private_authority["repo"]),
        evidence_root=finding_authority["run_dir"],
    )

    assert validated.destination_repo == "compute-market-internal-infra"
    assert (
        result.scm_ref
        not in _git(
            Path(private_authority["repo"]),
            "rev-list",
            "--all",
        ).splitlines()
    )


def test_private_destination_rejects_origin_and_branch_drift(
    finding_authority: dict[str, Any],
    private_authority: dict[str, str | Path],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["destination_repo"] = "compute-market-internal-infra"
    value["classification"] = "private-orchestration"
    value["observed_authority"].update(
        {
            "working_branch": "wrong-scratch",
            "working_ref": private_authority["working_ref"],
            "upstream_branch": "main",
            "upstream_ref": private_authority["upstream_ref"],
            "inbound_merge_ref": private_authority["inbound_merge_ref"],
        }
    )
    with pytest.raises(CapacityValidationError, match="working_branch"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=Path(private_authority["repo"]),
            evidence_root=finding_authority["run_dir"],
        )

    value["observed_authority"]["working_branch"] = "tools/agent-orchestration-scratch"
    _git(
        Path(private_authority["repo"]),
        "remote",
        "set-url",
        "origin",
        "https://github.com/arkhai-io/simple-compute-market",
    )
    with pytest.raises(CapacityValidationError, match="repository"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=Path(private_authority["repo"]),
            evidence_root=finding_authority["run_dir"],
        )


def test_git_replace_refs_cannot_forge_first_parent_or_merge_authority(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    repository = finding_authority["repo"]
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    base = _git(repository, "rev-parse", f"{finding_authority['working_ref']}^")
    forged_inbound = _git_with_input(
        repository,
        "forged inbound\n",
        "commit-tree",
        tree,
        "-p",
        base,
    )
    replacement_merge = _git_with_input(
        repository,
        "replacement merge\n",
        "commit-tree",
        tree,
        "-p",
        base,
        "-p",
        finding_authority["upstream_ref"],
    )
    replacement_working = _git_with_input(
        repository,
        "replacement working\n",
        "commit-tree",
        tree,
        "-p",
        forged_inbound,
    )
    _git(repository, "replace", forged_inbound, replacement_merge)
    _git(
        repository,
        "replace",
        finding_authority["working_ref"],
        replacement_working,
    )
    value["observed_authority"]["inbound_merge_ref"] = forged_inbound

    # Ordinary Git is fooled by the local replacement namespace.
    assert (
        forged_inbound
        in _git(
            repository,
            "rev-list",
            "--first-parent",
            finding_authority["working_ref"],
        ).splitlines()
    )
    assert (
        len(_git(repository, "show", "-s", "--format=%P", forged_inbound).split()) == 2
    )

    with pytest.raises(CapacityValidationError, match="replace refs"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=repository,
            evidence_root=finding_authority["run_dir"],
        )


def test_private_destination_revalidates_public_contract_git_authority(
    finding_authority: dict[str, Any],
    private_authority: dict[str, str | Path],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["destination_repo"] = "compute-market-internal-infra"
    value["classification"] = "private-orchestration"
    value["observed_authority"].update(
        {
            "working_branch": "tools/agent-orchestration-scratch",
            "working_ref": private_authority["working_ref"],
            "upstream_branch": "main",
            "upstream_ref": private_authority["upstream_ref"],
            "inbound_merge_ref": private_authority["inbound_merge_ref"],
        }
    )
    _git(
        finding_authority["repo"],
        "replace",
        finding_authority["working_ref"],
        finding_authority["upstream_ref"],
    )

    with pytest.raises(CapacityValidationError, match="replace refs"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=Path(private_authority["repo"]),
            evidence_root=finding_authority["run_dir"],
        )


def test_git_grafts_cannot_forge_first_parent_or_merge_authority(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    repository = finding_authority["repo"]
    tree = _git(repository, "rev-parse", "HEAD^{tree}")
    base = _git(repository, "rev-parse", f"{finding_authority['working_ref']}^")
    forged_inbound = _git_with_input(
        repository,
        "forged graft inbound\n",
        "commit-tree",
        tree,
        "-p",
        base,
    )
    common_dir = Path(_git(repository, "rev-parse", "--git-common-dir"))
    if not common_dir.is_absolute():
        common_dir = repository / common_dir
    grafts_path = common_dir / "info" / "grafts"
    grafts_path.write_text(
        (
            f"{finding_authority['working_ref']} {forged_inbound}\n"
            f"{forged_inbound} {base} {finding_authority['upstream_ref']}\n"
        ),
        encoding="ascii",
    )
    value["observed_authority"]["inbound_merge_ref"] = forged_inbound

    # Ordinary Git follows the forged local topology.
    assert (
        forged_inbound
        in _git(
            repository,
            "rev-list",
            "--first-parent",
            finding_authority["working_ref"],
        ).splitlines()
    )
    assert (
        len(_git(repository, "show", "-s", "--format=%P", forged_inbound).split()) == 2
    )

    with pytest.raises(CapacityValidationError, match="graft authority"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=repository,
            evidence_root=finding_authority["run_dir"],
        )


def test_durable_correlations_are_exact_result_projections(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["durable_correlations"][0]["deal_reference_sha256"] = "f" * 64

    with pytest.raises(CapacityValidationError, match="durable_correlations"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_evidence_mutation_is_rejected_before_and_after_validation(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )
    finding_authority["evidence_path"].write_text(
        '{"diagnostic_code":"changed"}\n',
        encoding="utf-8",
    )

    with pytest.raises(CapacityValidationError, match="does not match"):
        require_validated_capacity_finding(validated)
    with pytest.raises(CapacityValidationError, match="does not match"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_evidence_artifact_accepts_one_mib_and_rejects_one_mib_plus_one(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    evidence_path = finding_authority["evidence_path"]
    one_mib = 1024 * 1024
    evidence_path.write_bytes(b"x" * one_mib)
    value["evidence"][0]["sha256"] = hashlib.sha256(
        evidence_path.read_bytes()
    ).hexdigest()

    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )
    assert validated.finding["evidence"] == value["evidence"]

    evidence_path.write_bytes(b"x" * (one_mib + 1))
    value["evidence"][0]["sha256"] = hashlib.sha256(
        evidence_path.read_bytes()
    ).hexdigest()
    with pytest.raises(CapacityValidationError, match="evidence file exceeds 1048576"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_evidence_aggregate_accepts_four_mib_and_rejects_four_mib_plus_one(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    evidence_directory = finding_authority["run_dir"] / "evidence"
    one_mib_content = b"x" * (1024 * 1024)
    one_mib_sha256 = hashlib.sha256(one_mib_content).hexdigest()
    aggregate_evidence: list[dict[str, str]] = []
    for index in range(4):
        path = evidence_directory / f"aggregate-{index}.txt"
        path.write_bytes(one_mib_content)
        aggregate_evidence.append(
            {
                "path": path.relative_to(finding_authority["run_dir"]).as_posix(),
                "sha256": one_mib_sha256,
            }
        )
    value["evidence"] = aggregate_evidence

    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )
    assert validated.finding["evidence"] == aggregate_evidence
    assert (
        sum(
            (finding_authority["run_dir"] / evidence["path"]).stat().st_size
            for evidence in aggregate_evidence
        )
        == 4 * 1024 * 1024
    )

    one_byte_path = evidence_directory / "aggregate-overflow.txt"
    one_byte_path.write_bytes(b"x")
    value["evidence"].append(
        {
            "path": one_byte_path.relative_to(finding_authority["run_dir"]).as_posix(),
            "sha256": hashlib.sha256(b"x").hexdigest(),
        }
    )
    with pytest.raises(
        CapacityValidationError,
        match="total evidence exceeds 4194304 bytes",
    ):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_symlink_and_escaping_evidence_paths_are_rejected(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    link = finding_authority["run_dir"] / "evidence" / "linked.json"
    link.symlink_to(finding_authority["evidence_path"])
    value["evidence"][0] = {
        "path": "evidence/linked.json",
        "sha256": hashlib.sha256(
            finding_authority["evidence_path"].read_bytes()
        ).hexdigest(),
    }

    with pytest.raises(CapacityValidationError, match="evidence path"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )

    value["evidence"][0]["path"] = "../observer.json"
    with pytest.raises(CapacityValidationError, match="schema"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_configured_private_values_are_rejected_not_redacted(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    evidence = finding_authority["evidence_path"]
    evidence.write_text(
        "Authorization: Bearer private-token\n",
        encoding="utf-8",
    )
    value = _finding(finding_authority, result)

    with pytest.raises(CapacityValidationError, match="privacy"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_unresolved_finding_and_evidence_sentinels_are_rejected(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    sentinels = (
        "TODO",
        "XXX",
        "YOUR_PROJECT",
        "{{ secret }}",
        "${PROJECT_ID}",
        "<placeholder-value>",
        "example_ref",
        "REPLACE_ME",
    )
    for sentinel in sentinels:
        value = _finding(finding_authority, result)
        value["actual"] = f"Observed terminal fault {sentinel}"
        with pytest.raises(CapacityValidationError, match="placeholder"):
            validate_capacity_finding(
                value,
                result,
                authority_repo_root=finding_authority["repo"],
                evidence_root=finding_authority["run_dir"],
            )

    evidence = finding_authority["evidence_path"]
    for sentinel in sentinels:
        evidence.write_text(f"raw evidence {sentinel}\n", encoding="utf-8")
        value = _finding(finding_authority, result)
        with pytest.raises(CapacityValidationError, match="placeholder"):
            validate_capacity_finding(
                value,
                result,
                authority_repo_root=finding_authority["repo"],
                evidence_root=finding_authority["run_dir"],
            )


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "capacity-findings/finding.json",
        "capacity-finding-bodies/finding.md",
        "issue-candidates/finding.md",
        "manifest.json",
        "other/evidence.json",
    ],
)
def test_evidence_is_confined_to_immutable_namespace(
    finding_authority: dict[str, Any],
    unsafe_path: str,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["evidence"][0]["path"] = unsafe_path

    with pytest.raises(CapacityValidationError, match="schema"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def _successful_outcome(
    request_id: str,
    *,
    start: int,
    end: int,
) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "outcome_kind": "vm-succeeded",
        "deal_reference": {
            "request_id": request_id,
            "seller_slot": "seller-1",
            "listing_slot": "listing-1",
        },
        "capacity_reservation_id": f"{request_id}-reservation",
        "fulfillment_id": f"{request_id}-fulfillment",
        "settlement_record": {
            "capacity_reservation_id": f"{request_id}-reservation",
            "fulfillment_id": f"{request_id}-fulfillment",
            "state": "torn_down",
        },
        "provisioned_resource_id": f"{request_id}-vm",
        "allocation_id": f"{request_id}-allocation",
        "provisioning_job_id": f"{request_id}-provisioning",
        "commercial_resolution": {
            "deal_state": "fulfilled-terminal",
            "zero_active_claims": True,
            "zero_active_locks": True,
        },
        "request_cleanup": {
            "teardown_complete": True,
            "zero_active_residue": True,
        },
        "failure_category": None,
        "success_observation": {
            "active_interval": {
                "start_offset_ns": start,
                "end_offset_ns": end,
                "interval_semantics": "half-open",
            }
        },
    }


def _refused_outcome(request_id: str) -> dict[str, Any]:
    return {
        "request_id": request_id,
        "outcome_kind": "capacity-refused",
        "deal_reference": {
            "request_id": request_id,
            "seller_slot": "seller-1",
            "listing_slot": "listing-1",
        },
        "capacity_reservation_id": None,
        "fulfillment_id": None,
        "settlement_record": None,
        "provisioned_resource_id": None,
        "allocation_id": None,
        "provisioning_job_id": None,
        "commercial_resolution": {
            "deal_state": "refused-terminal",
            "zero_active_claims": True,
            "zero_active_locks": True,
        },
        "request_cleanup": {
            "teardown_complete": True,
            "zero_active_residue": True,
        },
        "failure_category": None,
        "refusal_observation": {
            "final_escrow_scoped_call": True,
            "aggregate_reservation_id": None,
        },
    }


def test_expected_clean_capacity_refusal_is_not_a_finding(
    finding_authority: dict[str, Any],
) -> None:
    refusal = _refused_outcome("request-1")
    result = _validated_result(
        finding_authority,
        outcomes=[refusal],
        expected={"vm-succeeded": 0, "capacity-refused": 1, "fault": 0},
        observed={"vm-succeeded": 0, "capacity-refused": 1, "fault": 0},
    )
    value = _finding(finding_authority, result)
    value["frontier"] = "correctness"
    value["defect_semantics"] = {
        "expected_outcome_kind": "vm-succeeded",
        "actual_fault_category": "unexpected-outcome",
        "failure_code": "unexpected-capacity-refused",
        "stable_signature": "unexpected complete capacity refusal",
        "lifecycle_phase": "reservation",
    }
    value["observed_outcome"] = {
        "request_ids": ["request-1"],
        "outcome_kind": "capacity-refused",
        "diagnostic_code": None,
    }
    value["durable_correlations"] = [_correlation(refusal)]

    with pytest.raises(CapacityValidationError, match="exceeds"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_frontier_stop_is_not_an_actionable_finding_category(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["defect_semantics"]["actual_fault_category"] = "frontier-stop"

    with pytest.raises(CapacityValidationError, match="capacity finding schema"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_duplicate_evidence_path_is_rejected_even_with_a_different_digest(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    duplicate = dict(value["evidence"][0])
    duplicate["sha256"] = "0" * 64
    value["evidence"].append(duplicate)

    with pytest.raises(
        CapacityValidationError, match="evidence paths must be distinct"
    ):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_duplicate_correlation_request_is_rejected_even_when_contents_differ(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    duplicate = dict(value["durable_correlations"][0])
    duplicate["allocation_id"] = "different-allocation"
    value["durable_correlations"].append(duplicate)

    with pytest.raises(CapacityValidationError, match="exactly project"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_cleanup_incomplete_finding_is_retained_but_not_ready(
    finding_authority: dict[str, Any],
) -> None:
    fault = _fault_outcome()
    fault["failure_category"] = "cleanup-incomplete"
    fault["fault_observation"]["phase"] = "cleanup"
    fault["fault_observation"]["diagnostic_code"] = "cleanup-incomplete"
    fault["request_cleanup"] = {
        "teardown_complete": False,
        "zero_active_residue": False,
    }
    cleanup = _clean_cleanup()
    cleanup["teardown_complete"] = False
    cleanup["residue_counts"]["vms"] = 1
    cleanup["reversible_components"][0]["exactly_equal"] = False
    cleanup["ready_for_next_stage"] = False
    result = _validated_result(
        finding_authority,
        outcomes=[fault],
        cleanup=cleanup,
        cleanup_passed=False,
    )
    value = _finding(finding_authority, result)
    value["frontier"] = "cleanup"
    value["defect_semantics"] = {
        "expected_outcome_kind": "vm-succeeded",
        "actual_fault_category": "cleanup-incomplete",
        "failure_code": "cleanup-incomplete",
        "stable_signature": "vm teardown left active residue",
        "lifecycle_phase": "cleanup",
    }
    value["observed_outcome"]["diagnostic_code"] = "cleanup-incomplete"
    value["durable_correlations"] = [_correlation(fault)]
    value["filing_readiness"] = {
        "terminal_correlations_complete": True,
        "teardown_complete": False,
        "zero_active_residue": False,
        "baseline_equivalent": False,
        "ready_to_file": False,
    }

    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )
    assert validated.ready_to_file is False


@pytest.mark.parametrize(
    ("category", "phase"),
    [
        ("generic-failure", "negotiation"),
        ("provisioning-error", "provisioning"),
        ("policy-denial", "reservation"),
        ("unknown-reason", "settlement"),
        ("uncompensated", "settlement"),
        ("atomic-refusal-incomplete", "reservation"),
        ("timeout", "provisioning"),
        ("missing-durable-correlation", "settlement"),
        ("cleanup-incomplete", "cleanup"),
        ("generator-failure", "pre-emission"),
    ],
)
def test_all_ten_request_fault_categories_bind_exact_result_semantics(
    finding_authority: dict[str, Any],
    category: str,
    phase: str,
) -> None:
    fault = _fault_outcome()
    diagnostic_code = f"diagnostic-{category}"
    fault["failure_category"] = category
    fault["fault_observation"]["phase"] = phase
    fault["fault_observation"]["diagnostic_code"] = diagnostic_code
    result = _validated_result(finding_authority, outcomes=[fault])
    value = _finding(finding_authority, result)
    value["defect_semantics"] = {
        "expected_outcome_kind": "vm-succeeded",
        "actual_fault_category": category,
        "failure_code": diagnostic_code,
        "stable_signature": f"stable {category} request fault",
        "lifecycle_phase": phase,
    }
    value["observed_outcome"]["diagnostic_code"] = diagnostic_code
    value["durable_correlations"] = [_correlation(fault)]

    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )
    assert validated.finding["defect_semantics"]["actual_fault_category"] == category

    value["defect_semantics"]["lifecycle_phase"] = "teardown"
    if phase == "teardown":
        value["defect_semantics"]["lifecycle_phase"] = "negotiation"
    with pytest.raises(CapacityValidationError, match="fault phase"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_double_allocation_uses_deterministic_overlap_witness(
    finding_authority: dict[str, Any],
) -> None:
    outcomes = [
        _successful_outcome("request-2", start=20, end=50),
        _successful_outcome("request-1", start=10, end=40),
    ]
    result = _validated_result(
        finding_authority,
        outcomes=outcomes,
        expected={"vm-succeeded": 2, "capacity-refused": 0, "fault": 0},
        observed={"vm-succeeded": 2, "capacity-refused": 0, "fault": 0},
        derived_faults=("double-allocation",),
    )
    value = _finding(finding_authority, result)
    value["frontier"] = "simultaneous-fulfillment"
    value["defect_semantics"] = {
        "expected_outcome_kind": "vm-succeeded",
        "actual_fault_category": "double-allocation",
        "failure_code": "double-allocation",
        "stable_signature": "whole gpu vm intervals overlap beyond authority",
        "lifecycle_phase": "provisioning",
    }
    value["observed_outcome"] = {
        "request_ids": ["request-1", "request-2"],
        "outcome_kind": "vm-succeeded",
        "diagnostic_code": None,
    }
    by_id = {outcome["request_id"]: outcome for outcome in outcomes}
    value["durable_correlations"] = [
        _correlation(by_id["request-1"]),
        _correlation(by_id["request-2"]),
    ]

    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )
    assert validated.frontier == "simultaneous-fulfillment"

    crossed_variant = deepcopy(value)
    crossed_variant["defect_semantics"]["actual_fault_category"] = "unexpected-outcome"
    with pytest.raises(CapacityValidationError, match="exceeds"):
        validate_capacity_finding(
            crossed_variant,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )

    value["observed_outcome"]["request_ids"].reverse()
    with pytest.raises(CapacityValidationError, match="lexicographic"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


@pytest.mark.parametrize(
    ("outcome_kind", "expected_kind", "phase"),
    [
        ("vm-succeeded", "capacity-refused", "guest-verification"),
        ("capacity-refused", "vm-succeeded", "reservation"),
    ],
)
def test_unexpected_outcome_binds_full_surplus_kind_set(
    finding_authority: dict[str, Any],
    outcome_kind: str,
    expected_kind: str,
    phase: str,
) -> None:
    if outcome_kind == "vm-succeeded":
        outcomes = [
            _successful_outcome("request-2", start=30, end=40),
            _successful_outcome("request-1", start=10, end=20),
        ]
        expected = {"vm-succeeded": 1, "capacity-refused": 1, "fault": 0}
        observed = {"vm-succeeded": 2, "capacity-refused": 0, "fault": 0}
    else:
        outcomes = [
            _refused_outcome("request-2"),
            _refused_outcome("request-1"),
        ]
        expected = {"vm-succeeded": 1, "capacity-refused": 1, "fault": 0}
        observed = {"vm-succeeded": 0, "capacity-refused": 2, "fault": 0}
    result = _validated_result(
        finding_authority,
        outcomes=outcomes,
        expected=expected,
        observed=observed,
    )
    value = _finding(finding_authority, result)
    value["frontier"] = "correctness"
    value["defect_semantics"] = {
        "expected_outcome_kind": expected_kind,
        "actual_fault_category": "unexpected-outcome",
        "failure_code": f"unexpected-{outcome_kind}",
        "stable_signature": f"surplus {outcome_kind} terminal outcomes",
        "lifecycle_phase": phase,
    }
    value["observed_outcome"] = {
        "request_ids": ["request-1", "request-2"],
        "outcome_kind": outcome_kind,
        "diagnostic_code": None,
    }
    by_id = {outcome["request_id"]: outcome for outcome in outcomes}
    value["durable_correlations"] = [
        _correlation(by_id["request-1"]),
        _correlation(by_id["request-2"]),
    ]

    validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )

    crossed_variant = deepcopy(value)
    crossed_variant["frontier"] = "simultaneous-fulfillment"
    crossed_variant["defect_semantics"].update(
        {
            "actual_fault_category": "double-allocation",
            "failure_code": "double-allocation",
            "lifecycle_phase": "provisioning",
        }
    )
    with pytest.raises(CapacityValidationError, match="derived result fault"):
        validate_capacity_finding(
            crossed_variant,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )

    value["observed_outcome"]["request_ids"] = ["request-1"]
    value["durable_correlations"] = [_correlation(by_id["request-1"])]
    with pytest.raises(CapacityValidationError, match="full set"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_render_and_index_are_marker_free_and_source_verifiable(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )

    body = render_finding_occurrence(validated)
    assert validated.finding_id in body
    assert validated.fingerprint in body
    assert result.canonical_sha256 in body
    assert finding_authority["inbound_merge_ref"] in body
    assert "does not authorize branch promotion" in body
    assert "scm.finding-publication." not in body

    record = capacity_finding_index_record(validated)
    assert record["candidate_kind"] == "capacity-finding-v2"
    assert record["publication_capability"] == "guard-issue-fix-publication"
    assert record["lifecycle"] == {
        "state": "detected",
        "detected_at": value["observed_authority"]["observed_at"],
    }
    assert record["occurrence_body"] == body
    assert record["occurrence_body_path"] == (
        "capacity-finding-bodies/capacity-occurrence-001.md"
    )
    assert (
        record["occurrence_body_sha256"]
        == hashlib.sha256(body.encode("utf-8")).hexdigest()
    )
    assert (
        validate_capacity_finding_index_record(
            record,
            value,
            repo_root=finding_authority["repo"],
        )
        == record
    )


def test_agent_prose_is_rendered_only_as_indented_commonmark_literals(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["summary"] = (
        "# forged-summary-heading - forged-summary-list "
        "``` <details><summary>forged-summary-html</summary></details>"
    )
    value["defect_semantics"]["stable_signature"] = (
        "# forged-stable-heading - forged-stable-list "
        "``` <details>forged-stable-html</details>"
    )
    value["expected"] = "\n".join(
        (
            "# forged-expected-heading",
            "- forged-expected-list",
            "```forged-expected-fence",
            "<details>",
            "<summary>forged-expected-html</summary>",
            "</details>",
        )
    )
    value["actual"] = "\n".join(
        (
            "## forged-actual-heading",
            "1. forged-actual-list",
            "~~~forged-actual-fence",
            "<details open>",
            "<summary>forged-actual-html</summary>",
            "</details>",
        )
    )

    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )
    body_lines = render_finding_occurrence(validated).splitlines()
    controlled_lines = (
        value["summary"],
        value["defect_semantics"]["stable_signature"],
        *value["expected"].splitlines(),
        *value["actual"].splitlines(),
    )

    for controlled_line in controlled_lines:
        assert f"    {controlled_line}" in body_lines
        assert controlled_line not in body_lines


def test_index_builder_rejects_a_rendered_only_pinned_redaction_match(
    finding_authority: dict[str, Any],
) -> None:
    redactions_path = (
        finding_authority["repo"]
        / "tools"
        / "issue-discovery"
        / "config"
        / "redactions.yaml"
    )
    with redactions_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n"
            "  - id: rendered_only_heading\n"
            '    regex: "Preparatory VM capacity finding"\n'
            '    replacement: "<redacted-rendered-heading>"\n'
        )
    _git(finding_authority["repo"], "add", redactions_path)
    _git(
        finding_authority["repo"],
        "commit",
        "-m",
        "add rendered-only redaction rule",
    )
    finding_authority["working_ref"] = _git(
        finding_authority["repo"],
        "rev-parse",
        "HEAD",
    )
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )

    with pytest.raises(CapacityValidationError, match="rendered_only_heading"):
        capacity_finding_index_record(validated)


def test_changed_pinned_redaction_regex_cannot_reuse_stale_fast_path_triggers(
    finding_authority: dict[str, Any],
) -> None:
    redactions_path = (
        finding_authority["repo"]
        / "tools"
        / "issue-discovery"
        / "config"
        / "redactions.yaml"
    )
    original_rule = r"    regex: '(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b'"
    changed_rule = r"    regex: '(?i)\bpinned-policy-match\b'"
    policy = redactions_path.read_text(encoding="utf-8")
    assert original_rule in policy
    redactions_path.write_text(
        policy.replace(original_rule, changed_rule),
        encoding="utf-8",
    )
    _git(finding_authority["repo"], "add", redactions_path)
    _git(
        finding_authority["repo"],
        "commit",
        "-m",
        "change existing pinned redaction regex",
    )
    finding_authority["working_ref"] = _git(
        finding_authority["repo"],
        "rev-parse",
        "HEAD",
    )
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    evidence_path = finding_authority["evidence_path"]
    evidence_path.write_text("pinned-policy-match\n", encoding="utf-8")
    value["evidence"][0]["sha256"] = hashlib.sha256(
        evidence_path.read_bytes()
    ).hexdigest()

    with pytest.raises(CapacityValidationError, match="email_account_identity"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_index_verifier_rejects_mutable_body_or_lifecycle(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    validated = validate_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )
    record = capacity_finding_index_record(validated)
    changed = deepcopy(record)
    changed["occurrence_body"] += "changed\n"
    with pytest.raises(CapacityValidationError, match="does not exactly match"):
        validate_capacity_finding_index_record(
            changed,
            value,
            repo_root=finding_authority["repo"],
        )

    changed = deepcopy(record)
    changed["lifecycle"]["state"] = "verified"
    with pytest.raises(CapacityValidationError, match="does not exactly match"):
        validate_capacity_finding_index_record(
            changed,
            value,
            repo_root=finding_authority["repo"],
        )


def test_ingest_is_create_once_private_and_idempotent(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)

    first = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    second = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    assert first.appended_source is True
    assert first.appended_index is True
    assert second.appended_source is False
    assert second.appended_index is False
    assert first.source_path.read_bytes() == canonical_json_bytes(value)
    assert first.index_path.read_bytes() == canonical_json_bytes(first.index_record)
    body_path = (
        finding_authority["run_dir"] / first.index_record["occurrence_body_path"]
    )
    assert (
        body_path.read_text(encoding="utf-8") == (first.index_record["occurrence_body"])
    )
    for directory in (
        first.source_path.parent,
        first.index_path.parent,
        body_path.parent,
    ):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for path in (
        first.source_path,
        first.index_path,
        body_path,
        finding_authority["run_dir"] / CAPACITY_FINDING_SOURCE_NAME,
        finding_authority["run_dir"] / CAPACITY_FINDING_INDEX_NAME,
        finding_authority["run_dir"] / CAPACITY_FINDING_MANIFEST_NAME,
        finding_authority["run_dir"] / CAPACITY_FINDING_LIFECYCLE_NAME,
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        assert path.stat().st_uid == os.geteuid()
        assert path.stat().st_nlink == 1

    source_lines = (
        (finding_authority["run_dir"] / CAPACITY_FINDING_SOURCE_NAME)
        .read_text(encoding="utf-8")
        .splitlines()
    )
    index_lines = (
        (finding_authority["run_dir"] / CAPACITY_FINDING_INDEX_NAME)
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(source_lines) == 1
    assert len(index_lines) == 1
    assert json.loads(source_lines[0]) == value
    assert json.loads(index_lines[0]) == first.index_record
    manifest = json.loads(
        (finding_authority["run_dir"] / CAPACITY_FINDING_MANIFEST_NAME).read_text(
            encoding="utf-8"
        )
    )
    assert manifest["run_id"] == value["observed_authority"]["run_id"]
    assert manifest["capacity_finding_authority"] == {
        key: value["observed_authority"][key]
        for key in (
            "run_id",
            "working_branch",
            "working_ref",
            "upstream_branch",
            "upstream_ref",
            "inbound_merge_ref",
            "reconciliation_epoch_id",
        )
    }
    assert [item["finding_id"] for item in manifest["capacity_findings"]] == [
        value["finding_id"]
    ]
    lifecycle = (
        (finding_authority["run_dir"] / CAPACITY_FINDING_LIFECYCLE_NAME)
        .read_text(encoding="utf-8")
        .splitlines()
    )
    assert len(lifecycle) == 1
    event = json.loads(lifecycle[0])
    assert event["state"] == "detected"
    assert event["recorded_at"] == value["observed_authority"]["observed_at"]
    assert event["observed_authority"] == value["observed_authority"]

    assert (
        load_capacity_finding_index_artifacts(
            first.source_path,
            first.index_path,
            body_path,
            repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )
        == first.index_record
    )


def test_ingest_creates_exact_private_modes_under_a_restrictive_umask(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    previous_umask = os.umask(0o777)
    try:
        first = ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=finding_authority["run_dir"],
        )
        second = ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=finding_authority["run_dir"],
        )
    finally:
        os.umask(previous_umask)

    assert first.appended_source is True
    assert second.appended_source is False
    body_path = (
        finding_authority["run_dir"] / first.index_record["occurrence_body_path"]
    )
    for directory in (
        first.source_path.parent,
        first.index_path.parent,
        body_path.parent,
    ):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    for path in (
        finding_authority["run_dir"] / CAPACITY_FINDING_INGEST_LOCK_NAME,
        first.source_path,
        first.index_path,
        body_path,
        finding_authority["run_dir"] / CAPACITY_FINDING_SOURCE_NAME,
        finding_authority["run_dir"] / CAPACITY_FINDING_INDEX_NAME,
        finding_authority["run_dir"] / CAPACITY_FINDING_MANIFEST_NAME,
        finding_authority["run_dir"] / CAPACITY_FINDING_LIFECYCLE_NAME,
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_packet_generation_replays_real_ingested_finding(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingested = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    candidates = IssuePacketGenerator(
        finding_authority["run_dir"],
        repo_root=finding_authority["repo"],
    ).generate()

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.candidate_id == value["finding_id"]
    assert candidate.finding_sha256 == ingested.index_record["finding_sha256"]
    assert candidate.fingerprint == ingested.index_record["fingerprint"]
    assert candidate.body_file.read_bytes() == ingested.index_record[
        "occurrence_body"
    ].encode("utf-8")


def test_publication_preview_replays_real_ingested_finding_and_rejects_tamper(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingested = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    authenticated_preview = load_issue_publication_preview(
        finding_authority["run_dir"],
        value["finding_id"],
        private_authorization_sha256="d" * 64,
        repo_root=finding_authority["repo"],
    )
    preview = authenticated_preview.value

    assert isinstance(authenticated_preview, ValidatedPublicationPreview)
    assert preview["authority"]["finding_id"] == value["finding_id"]
    assert (
        preview["authority"]["finding_sha256"]
        == ingested.index_record["finding_sha256"]
    )
    assert preview["occurrence_comment"].endswith(
        ingested.index_record["occurrence_body"]
    )
    assert (
        preview["authority"]["occurrence_comment_sha256"]
        == preview["occurrence_comment_sha256"]
    )

    def guarded_git_read(
        command: list[str],
        **kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        arguments = tuple(command[1:])
        if arguments == (
            "ls-remote",
            "--exit-code",
            "https://github.com/arkhai-io/simple-compute-market.git",
            "refs/heads/feat/issue-discovery-harness",
        ):
            output = (
                f"{finding_authority['working_ref']}\t"
                "refs/heads/feat/issue-discovery-harness\n"
            )
            return subprocess.CompletedProcess(command, 0, output, "")
        if arguments == (
            "ls-remote",
            "--exit-code",
            "https://github.com/arkhai-io/simple-compute-market.git",
            "refs/heads/dev",
        ):
            output = f"{finding_authority['upstream_ref']}\trefs/heads/dev\n"
            return subprocess.CompletedProcess(command, 0, output, "")
        if arguments == (
            "ls-remote",
            "--symref",
            "https://github.com/arkhai-io/simple-compute-market.git",
            "HEAD",
        ):
            output = (
                "ref: refs/heads/main\tHEAD\n"
                f"{finding_authority['upstream_ref']}\tHEAD\n"
            )
            return subprocess.CompletedProcess(command, 0, output, "")
        if arguments[:2] == ("merge-base", "--is-ancestor") and (
            FINDING_V2_CONSUMED_REF in arguments
        ):
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.run(command, **kwargs)

    git_authority = observe_git_publication_authority(
        authenticated_preview,
        finding_authority["repo"],
        repo_root=finding_authority["repo"],
        git_runner=guarded_git_read,
        remote_git_runner=guarded_git_read,
    )
    empty_observation = json.loads(
        (
            repo_root()
            / "tools/issue-discovery/tests/fixtures/publication/empty-observation.json"
        ).read_text(encoding="utf-8")
    )
    observed = validate_publication_observation(
        empty_observation,
        repo_root=finding_authority["repo"],
    )
    action = select_issue_publication_action(
        authenticated_preview,
        observed,
        git_authority,
        repo_root=finding_authority["repo"],
    ).value

    assert action["action_kind"] == "create"
    assert action["authority"]["finding_id"] == value["finding_id"]

    body_path = (
        finding_authority["run_dir"] / ingested.index_record["occurrence_body_path"]
    )
    body_path.write_text("tampered after authenticated ingest\n", encoding="utf-8")

    with pytest.raises(CapacityValidationError):
        load_issue_publication_preview(
            finding_authority["run_dir"],
            value["finding_id"],
            private_authorization_sha256="d" * 64,
            repo_root=finding_authority["repo"],
        )


def test_runner_issue_surfaces_preserve_symlinked_run_root_identity(
    finding_authority: dict[str, Any],
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    alias = finding_authority["run_dir"].with_name("run-alias")
    alias.symlink_to(finding_authority["run_dir"], target_is_directory=True)
    runner = DiscoveryRunner(repo_root=finding_authority["repo"])

    assert runner.issue_list(alias) == 2
    assert "non-symlink run root" in capsys.readouterr().out
    assert runner.issue_show(alias, value["finding_id"]) == 2
    assert "non-symlink run root" in capsys.readouterr().out
    assert runner.issue_create(alias, value["finding_id"], dry_run=True) == 2
    assert "non-symlink run root" in capsys.readouterr().out
    assert runner.issue_propose_fix(alias, value["finding_id"], "fix/example") == 2
    assert "non-symlink run root" in capsys.readouterr().out
    assert (
        runner.issue_transition(
            alias,
            value["finding_id"],
            "triaged",
            "must not mutate",
        )
        == 2
    )
    assert "non-symlink run root" in capsys.readouterr().out
    assert not (finding_authority["run_dir"] / "issue-candidates").exists()


def test_packet_replay_rejects_evidence_mutated_after_ingest(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    finding_authority["evidence_path"].write_text(
        '{"diagnostic_code":"different","phase":"provisioning"}\n',
        encoding="utf-8",
    )

    with pytest.raises(CapacityValidationError, match="raw evidence bytes"):
        IssuePacketGenerator(
            finding_authority["run_dir"],
            repo_root=finding_authority["repo"],
        ).generate()
    assert not (finding_authority["run_dir"] / "issue-candidates").exists()


def test_shared_ingest_lock_rejects_a_symlinked_run_root(
    finding_authority: dict[str, Any],
) -> None:
    alias = finding_authority["run_dir"].with_name("run-alias")
    alias.symlink_to(finding_authority["run_dir"], target_is_directory=True)

    with pytest.raises(CapacityValidationError, match="non-symlink directory"):
        with capacity_finding_ingest_lock(alias):
            pytest.fail("symlinked run root acquired finding lock")


def test_packet_replay_uses_source_pinned_contract_after_head_policy_drift(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingested = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    redactions_path = (
        finding_authority["repo"]
        / "tools"
        / "issue-discovery"
        / "config"
        / "redactions.yaml"
    )
    with redactions_path.open("a", encoding="utf-8") as handle:
        handle.write(
            "\n"
            "  - id: later_policy_only\n"
            '    regex: "Validated provisioning fault"\n'
            '    replacement: "<redacted-later-policy>"\n'
        )
    _git(finding_authority["repo"], "add", redactions_path)
    _git(finding_authority["repo"], "commit", "-m", "later policy")

    candidates = IssuePacketGenerator(
        finding_authority["run_dir"],
        repo_root=finding_authority["repo"],
    ).generate()

    assert [candidate.candidate_id for candidate in candidates] == [value["finding_id"]]
    assert candidates[0].finding_sha256 == ingested.index_record["finding_sha256"]


def test_ingest_recovers_from_source_only_prefix_crash(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    source_directory = finding_authority["run_dir"] / "capacity-findings"
    source_directory.mkdir(mode=0o700)
    source_path = source_directory / f"{value['finding_id']}.json"
    source_path.write_bytes(canonical_json_bytes(value))
    source_path.chmod(0o600)

    recovered = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    assert recovered.appended_source is False
    assert recovered.appended_index is True
    assert recovered.index_path.exists()
    assert (
        finding_authority["run_dir"] / recovered.index_record["occurrence_body_path"]
    ).exists()


def test_ingest_preserves_unrelated_manifest_fields_and_checks_authority(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    manifest_path = finding_authority["run_dir"] / CAPACITY_FINDING_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": value["observed_authority"]["run_id"],
                "mode": "capacity-preparation",
                "status": "running",
                "working_branch": value["observed_authority"]["working_branch"],
                "observed_ref": value["observed_authority"]["working_ref"],
                "campaign_field": {"preserve": True},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)

    ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["mode"] == "capacity-preparation"
    assert manifest["status"] == "running"
    assert manifest["campaign_field"] == {"preserve": True}
    assert manifest["capacity_finding_authority"]["upstream_branch"] == "dev"
    assert manifest["capacity_findings"][0]["finding_id"] == value["finding_id"]


def test_manifest_authority_collision_fails_before_occurrence_files(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    manifest_path = finding_authority["run_dir"] / CAPACITY_FINDING_MANIFEST_NAME
    manifest_path.write_text(
        json.dumps({"schema_version": 2, "run_id": "different-run"}) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)

    with pytest.raises(CapacityValidationError, match="run_id conflicts"):
        ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=finding_authority["run_dir"],
        )
    assert not (finding_authority["run_dir"] / "capacity-findings").exists()
    assert not (finding_authority["run_dir"] / CAPACITY_FINDING_LIFECYCLE_NAME).exists()


def test_private_artifact_hardlinks_and_directory_modes_are_rejected(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingested = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    body_path = (
        finding_authority["run_dir"] / ingested.index_record["occurrence_body_path"]
    )
    hardlink = finding_authority["run_dir"] / "body-hardlink.md"
    os.link(body_path, hardlink)
    with pytest.raises(CapacityValidationError, match="hard link"):
        load_capacity_finding_index_artifacts(
            ingested.source_path,
            ingested.index_path,
            body_path,
            repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )
    hardlink.unlink()

    ingested.source_path.parent.chmod(0o755)
    with pytest.raises(CapacityValidationError, match="mode 0700"):
        ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=finding_authority["run_dir"],
        )


def test_ingest_rejects_same_id_changed_bytes(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    changed = deepcopy(value)
    changed["summary"] = "Same identity with changed immutable bytes"

    with pytest.raises(CapacityValidationError, match="collision"):
        ingest_capacity_finding(
            changed,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=finding_authority["run_dir"],
        )


def test_same_defect_new_finding_id_creates_new_occurrence(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    first_value = _finding(finding_authority, result)
    second_value = deepcopy(first_value)
    second_value["finding_id"] = "capacity-occurrence-002"
    first = ingest_capacity_finding(
        first_value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    second = ingest_capacity_finding(
        second_value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    assert first.finding.fingerprint == second.finding.fingerprint
    assert first.finding.finding_id != second.finding.finding_id
    assert first.source_path != second.source_path
    assert (
        len(
            (finding_authority["run_dir"] / CAPACITY_FINDING_SOURCE_NAME)
            .read_text(encoding="utf-8")
            .splitlines()
        )
        == 2
    )


def _occurrence_artifacts(
    authority: dict[str, Any],
    finding_id: str,
) -> dict[str, Path]:
    run_dir = authority["run_dir"]
    return {
        "source_file": run_dir / "capacity-findings" / f"{finding_id}.json",
        "index_file": run_dir / "capacity-finding-index" / f"{finding_id}.json",
        "body_file": run_dir / "capacity-finding-bodies" / f"{finding_id}.md",
        "source_ledger": run_dir / CAPACITY_FINDING_SOURCE_NAME,
        "index_ledger": run_dir / CAPACITY_FINDING_INDEX_NAME,
        "manifest": run_dir / CAPACITY_FINDING_MANIFEST_NAME,
        "lifecycle": run_dir / CAPACITY_FINDING_LIFECYCLE_NAME,
    }


def _file_identity(path: Path) -> tuple[int, int, int, int, bytes]:
    path_stat = path.stat()
    return (
        path_stat.st_dev,
        path_stat.st_ino,
        path_stat.st_mtime_ns,
        path_stat.st_size,
        path.read_bytes(),
    )


def test_identical_reingest_is_a_true_byte_and_inode_noop(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    artifacts = _occurrence_artifacts(finding_authority, value["finding_id"])
    before = {name: _file_identity(path) for name, path in artifacts.items()}

    replay = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    assert replay.appended_source is False
    assert replay.appended_index is False
    assert {name: _file_identity(path) for name, path in artifacts.items()} == before


def test_identical_reingest_rejects_post_preflight_artifact_mutation(
    finding_authority: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    artifacts = _occurrence_artifacts(finding_authority, value["finding_id"])
    before = {
        name: _file_identity(path)
        for name, path in artifacts.items()
        if name != "source_file"
    }
    from issue_discovery import capacity_findings

    original_preflight = capacity_findings._preflight_ingest
    mutated = False

    def preflight_then_mutate(*args: object, **kwargs: object) -> object:
        nonlocal mutated
        preflight = original_preflight(*args, **kwargs)
        if not mutated:
            mutated = True
            changed = json.loads(
                artifacts["source_file"].read_text(encoding="utf-8")
            )
            changed["summary"] = "Changed after the read-only preflight"
            artifacts["source_file"].write_bytes(canonical_json_bytes(changed))
        return preflight

    monkeypatch.setattr(
        capacity_findings,
        "_preflight_ingest",
        preflight_then_mutate,
    )

    with pytest.raises(CapacityValidationError, match="collision"):
        ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=finding_authority["run_dir"],
        )

    assert mutated is True
    assert {
        name: _file_identity(artifacts[name])
        for name in before
    } == before
    assert (
        json.loads(artifacts["source_file"].read_text(encoding="utf-8"))[
            "summary"
        ]
        == "Changed after the read-only preflight"
    )


def test_ingest_rejects_artifact_directory_appearing_after_absent_preflight(
    finding_authority: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    run_dir = finding_authority["run_dir"]
    source_directory = run_dir / "capacity-findings"
    from issue_discovery import capacity_findings

    original_preflight = capacity_findings._preflight_ingest
    appeared = False

    def preflight_then_create_directory(
        *args: object,
        **kwargs: object,
    ) -> object:
        nonlocal appeared
        preflight = original_preflight(*args, **kwargs)
        if not appeared:
            appeared = True
            source_directory.mkdir(mode=0o700)
        return preflight

    monkeypatch.setattr(
        capacity_findings,
        "_preflight_ingest",
        preflight_then_create_directory,
    )

    with pytest.raises(
        CapacityValidationError,
        match="appeared after absent preflight",
    ):
        ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=run_dir,
        )

    assert source_directory.is_dir()
    assert not any(source_directory.iterdir())
    assert not (run_dir / "capacity-finding-index").exists()
    assert not (run_dir / "capacity-finding-bodies").exists()
    assert not (run_dir / CAPACITY_FINDING_SOURCE_NAME).exists()


def test_ingest_rejects_new_artifact_directory_swap_before_open(
    finding_authority: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    run_dir = finding_authority["run_dir"]
    source_directory = run_dir / "capacity-findings"
    held_directory = run_dir / "capacity-findings-held"
    original_open = os.open
    swapped = False

    def open_after_directory_swap(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if (
            not swapped
            and path == "capacity-findings"
            and dir_fd is not None
            and flags & os.O_DIRECTORY
            and source_directory.is_dir()
        ):
            swapped = True
            source_directory.rename(held_directory)
            source_directory.mkdir(mode=0o700)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", open_after_directory_swap)

    with pytest.raises(
        CapacityValidationError,
        match=r"(?:stable .* identity|identity changed during creation)",
    ):
        ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=run_dir,
        )

    assert swapped is True
    assert source_directory.is_dir()
    assert held_directory.is_dir()
    assert not any(source_directory.iterdir())
    assert not any(held_directory.iterdir())
    assert not (run_dir / CAPACITY_FINDING_SOURCE_NAME).exists()


@pytest.mark.parametrize(
    "durable_prefix_length",
    range(1, 8),
    ids=(
        "source-file-only",
        "through-index-file",
        "through-body-file",
        "through-source-ledger",
        "through-index-ledger",
        "through-manifest",
        "through-detected-lifecycle",
    ),
)
def test_ingest_recovers_every_exact_durable_component_prefix(
    finding_authority: dict[str, Any],
    durable_prefix_length: int,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    artifacts = _occurrence_artifacts(finding_authority, value["finding_id"])
    ordered_names = tuple(artifacts)
    retained_names = ordered_names[:durable_prefix_length]
    retained = {name: _file_identity(artifacts[name]) for name in retained_names}
    for name in ordered_names[durable_prefix_length:]:
        artifacts[name].unlink()

    recovered = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    assert all(path.is_file() for path in artifacts.values())
    assert {
        name: _file_identity(artifacts[name]) for name in retained_names
    } == retained
    assert recovered.appended_source is (
        durable_prefix_length < ordered_names.index("source_file") + 1
    )
    assert recovered.appended_index is (
        durable_prefix_length < ordered_names.index("index_ledger") + 1
    )


@pytest.mark.parametrize(
    "missing_component",
    (
        "source_file",
        "index_file",
        "body_file",
        "source_ledger",
        "index_ledger",
        "manifest",
    ),
)
def test_ingest_rejects_a_hole_in_the_current_durable_component_prefix(
    finding_authority: dict[str, Any],
    missing_component: str,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    artifacts = _occurrence_artifacts(finding_authority, value["finding_id"])
    artifacts[missing_component].unlink()
    retained = {
        name: _file_identity(path)
        for name, path in artifacts.items()
        if name != missing_component
    }

    with pytest.raises(
        CapacityValidationError,
        match="not a valid durable publication prefix",
    ):
        ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=finding_authority["run_dir"],
        )

    assert not artifacts[missing_component].exists()
    assert {
        name: _file_identity(artifacts[name])
        for name in retained
    } == retained


@pytest.mark.parametrize(
    "corruption",
    (
        "duplicate-source-ledger-id",
        "changed-unrelated-index-ledger",
        "open-manifest-projection",
        "null-manifest-authority",
        "null-manifest-occurrences",
        "lifecycle-suffix-before-detected",
        "duplicate-detected-event",
    ),
)
def test_read_only_preflight_rejects_corrupt_unrelated_history_before_mutation(
    finding_authority: dict[str, Any],
    corruption: str,
) -> None:
    result = _validated_result(finding_authority)
    first_value = _finding(finding_authority, result)
    first = ingest_capacity_finding(
        first_value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    run_dir = finding_authority["run_dir"]
    if corruption == "duplicate-source-ledger-id":
        path = run_dir / CAPACITY_FINDING_SOURCE_NAME
        path.write_bytes(path.read_bytes() * 2)
    elif corruption == "changed-unrelated-index-ledger":
        path = run_dir / CAPACITY_FINDING_INDEX_NAME
        record = json.loads(path.read_text(encoding="utf-8"))
        record["occurrence_body_sha256"] = "0" * 64
        path.write_bytes(canonical_json_bytes(record))
    elif corruption == "open-manifest-projection":
        path = run_dir / CAPACITY_FINDING_MANIFEST_NAME
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["capacity_findings"][0]["unexpected"] = True
        path.write_bytes(canonical_json_bytes(manifest))
    elif corruption in {"null-manifest-authority", "null-manifest-occurrences"}:
        path = run_dir / CAPACITY_FINDING_MANIFEST_NAME
        manifest = json.loads(path.read_text(encoding="utf-8"))
        field = (
            "capacity_finding_authority"
            if corruption == "null-manifest-authority"
            else "capacity_findings"
        )
        manifest[field] = None
        path.write_bytes(canonical_json_bytes(manifest))
    else:
        path = run_dir / CAPACITY_FINDING_LIFECYCLE_NAME
        detected = json.loads(path.read_text(encoding="utf-8"))
        if corruption == "lifecycle-suffix-before-detected":
            suffix = deepcopy(detected)
            suffix["state"] = "filed"
            path.write_bytes(
                canonical_json_bytes(suffix) + canonical_json_bytes(detected)
            )
        else:
            path.write_bytes(
                canonical_json_bytes(detected) + canonical_json_bytes(detected)
            )
    corrupt_identity = _file_identity(path)
    manifest_path = run_dir / CAPACITY_FINDING_MANIFEST_NAME
    manifest_identity = _file_identity(manifest_path)
    second_value = deepcopy(first_value)
    second_value["finding_id"] = "capacity-occurrence-002"

    with pytest.raises(CapacityValidationError):
        ingest_capacity_finding(
            second_value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=run_dir,
        )

    assert _file_identity(path) == corrupt_identity
    if path != manifest_path:
        assert _file_identity(manifest_path) == manifest_identity
    second_artifacts = _occurrence_artifacts(
        finding_authority,
        second_value["finding_id"],
    )
    assert not second_artifacts["source_file"].exists()
    assert not second_artifacts["index_file"].exists()
    assert not second_artifacts["body_file"].exists()
    assert (
        second_value["finding_id"].encode()
        not in (run_dir / CAPACITY_FINDING_SOURCE_NAME).read_bytes()
    )
    assert first.source_path.is_file()


def _manifest_projection_from_index(index: dict[str, Any]) -> dict[str, Any]:
    authority = index["observed_authority"]
    return {
        key: index[key]
        for key in (
            "finding_id",
            "finding_sha256",
            "fingerprint",
            "destination_repo",
            "classification",
            "scenario_id",
            "scenario_sha256",
            "profile_stage_id",
            "profile_stage_sha256",
            "result_id",
            "result_sha256",
        )
    } | {
        "stage_id": authority["stage_id"],
        "observed_at": authority["observed_at"],
    }


def _detected_event_from_index(index: dict[str, Any]) -> dict[str, Any]:
    authority = index["observed_authority"]
    return {
        "schema_version": 2,
        "candidate_kind": "capacity-finding-v2",
        "finding_id": index["finding_id"],
        "finding_sha256": index["finding_sha256"],
        "fingerprint": index["fingerprint"],
        "state": "detected",
        "recorded_at": authority["observed_at"],
        "destination_repo": index["destination_repo"],
        "classification": index["classification"],
        "frontier": index["frontier"],
        "scenario_id": index["scenario_id"],
        "scenario_sha256": index["scenario_sha256"],
        "profile_stage_id": index["profile_stage_id"],
        "profile_stage_sha256": index["profile_stage_sha256"],
        "result_id": index["result_id"],
        "result_sha256": index["result_sha256"],
        "scm_contract_ref": index["scm_contract_ref"],
        "observed_authority": authority,
        "filing_readiness": index["filing_readiness"],
    }


def test_preflight_rejects_complete_unrelated_occurrence_with_mixed_authority(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    first_value = _finding(finding_authority, result)
    ingest_capacity_finding(
        first_value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    mixed_value = deepcopy(first_value)
    mixed_value["finding_id"] = "capacity-occurrence-002"
    mixed_value["observed_authority"]["run_id"] = "different-capacity-run"
    mixed = validate_capacity_finding(
        mixed_value,
        result,
        authority_repo_root=finding_authority["repo"],
        evidence_root=finding_authority["run_dir"],
    )
    mixed_index = capacity_finding_index_record(mixed)
    run_dir = finding_authority["run_dir"]
    (run_dir / "capacity-findings" / f"{mixed.finding_id}.json").write_bytes(
        canonical_json_bytes(mixed_value)
    )
    (run_dir / "capacity-finding-index" / f"{mixed.finding_id}.json").write_bytes(
        canonical_json_bytes(mixed_index)
    )
    (run_dir / "capacity-finding-bodies" / f"{mixed.finding_id}.md").write_text(
        mixed_index["occurrence_body"], encoding="utf-8"
    )
    for path in (
        run_dir / "capacity-findings" / f"{mixed.finding_id}.json",
        run_dir / "capacity-finding-index" / f"{mixed.finding_id}.json",
        run_dir / "capacity-finding-bodies" / f"{mixed.finding_id}.md",
    ):
        path.chmod(0o600)
    source_ledger = run_dir / CAPACITY_FINDING_SOURCE_NAME
    source_ledger.write_bytes(
        source_ledger.read_bytes() + canonical_json_bytes(mixed_value)
    )
    index_ledger = run_dir / CAPACITY_FINDING_INDEX_NAME
    index_ledger.write_bytes(
        index_ledger.read_bytes() + canonical_json_bytes(mixed_index)
    )
    manifest_path = run_dir / CAPACITY_FINDING_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["capacity_findings"].append(_manifest_projection_from_index(mixed_index))
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    lifecycle_path = run_dir / CAPACITY_FINDING_LIFECYCLE_NAME
    lifecycle_path.write_bytes(
        lifecycle_path.read_bytes()
        + canonical_json_bytes(_detected_event_from_index(mixed_index))
    )
    before = {
        name: _file_identity(path)
        for name, path in _occurrence_artifacts(
            finding_authority,
            first_value["finding_id"],
        ).items()
    }

    with pytest.raises(CapacityValidationError, match="mixed run/branch/ref"):
        ingest_capacity_finding(
            first_value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=run_dir,
        )

    assert {
        name: _file_identity(path)
        for name, path in _occurrence_artifacts(
            finding_authority,
            first_value["finding_id"],
        ).items()
    } == before


@pytest.mark.parametrize(
    ("evidence_text", "message"),
    (
        (
            '{"safe":true}\n{"seed phrase":"words that cannot be public"}\n',
            "forbidden private field",
        ),
        (
            '{"sshPrivateKey":"not-public"}\n{"safe":true}\n',
            "forbidden private field",
        ),
        (
            '{"wallet-address":"not-public"}\n{"safe":true}\n',
            "forbidden private field",
        ),
        ("wallet_address: solana-address\n", "forbidden private field"),
        ("{wallet_address: personal-wallet-name}\n", "forbidden private field"),
        ('"api\\u005fkey": live-api-key-value\n', "forbidden private field"),
        ("account id = private-account\n", "forbidden private field"),
        (
            'prefix with truncated JSON {"gpu-id":"private-device"\n',
            "forbidden private field",
        ),
        ('safe: "TO\\u0044O"\n', "placeholder"),
        ('endpoint: "192.\\u003168.1.2"\n', "private IPv4 endpoint"),
        ('contact: "alice\\u0040private.com"\n', "email_account_identity"),
        (
            "note: '\"192\\u002e168\\u002e1\\u002e1\"'\n",
            "private IPv4 endpoint",
        ),
        ("note: '\"TO\\u0044O\"'\n", "placeholder"),
        (
            "note: '\"alice\\u0040private\\u002ecom\"'\n",
            "email_account_identity",
        ),
        ("note: '\"ok\\u200b\"'\n", "default-ignorable"),
        ("note: '\"ok\\u0000\"'\n", "disallowed Unicode control"),
        ('"\\ud800"\n', "invalid Unicode surrogate"),
        ('"\\udfff"\n', "invalid Unicode surrogate"),
        (
            'note: "projects\\u002fprivate-project"\n',
            "gcp_project_resource",
        ),
        (
            "name: &key !!str wallet_address\nleak: {*key: personal-wallet-name}\n",
            "forbidden private field",
        ),
        ('? "api\\\n  _key"\n: live-key-value\n', "forbidden private field"),
        ('contact: "alice\\\n  @example.com"\n', "email_account_identity"),
        ('contact: "alice@\\\n  private.com"\n', "email_account_identity"),
        ('? "api\n  key"\n: live-key-value\n', "forbidden private field"),
        ('? "wallet_\n  address"\n: personal\n', "forbidden private field"),
        ("? api\n  key\n: live-key-value\n", "forbidden private field"),
        ("{? wallet_address: personal}\n", "forbidden private field"),
        ("safe: {? wallet_address: personal}\n", "forbidden private field"),
        ("{wallet_address}\n", "forbidden private field"),
        ("safe: {wallet_address}\n", "forbidden private field"),
        ('{"api\\u005fkey"}\n', "forbidden private field"),
        ("!!str wallet_address: personal\n", "forbidden private field"),
        (
            "!<tag:yaml.org,2002:str> wallet_address: personal\n",
            "forbidden private field",
        ),
        ("&key wallet_address: personal\n", "forbidden private field"),
        ("safe: {&key wallet_address: personal}\n", "forbidden private field"),
        ("[wallet_address: personal]\n", "forbidden private field"),
        ("safe: [wallet_address: personal]\n", "forbidden private field"),
        ("[? wallet_address: personal]\n", "forbidden private field"),
        ("\ufeffwallet_address: personal\n", "forbidden private field"),
        ("- ! wallet_address: personal\n", "forbidden private field"),
        ("[&key wallet_address: personal]\n", "forbidden private field"),
        ("_wallet_address: personal\n", "forbidden private field"),
        (".wallet_address: personal\n", "forbidden private field"),
        ("wallet/address: personal\n", "forbidden private field"),
        ("wallet$address: personal\n", "forbidden private field"),
        ("wallet\u200baddress: personal\n", "forbidden private field"),
        ("wallet\u2010address: personal\n", "forbidden private field"),
        ("api:key: personal\n", "forbidden private field"),
        ("{api:key: personal}\n", "forbidden private field"),
        ("[api:key: personal]\n", "forbidden private field"),
        ("_" * 81 + "wallet_address: personal\n", "forbidden private field"),
        (
            "wallet" + "_" * 81 + "address: personal\n",
            "forbidden private field",
        ),
        ('[? "api\n   key": personal]\n', "forbidden private field"),
        ("[? 'api\n   key': personal]\n", "forbidden private field"),
        ("[? api\n   key: personal]\n", "forbidden private field"),
        ('{? "api\n   key": personal}\n', "forbidden private field"),
        ("safe: ok\rwallet_address: personal\r", "forbidden private field"),
        ("safe: ok\u0085wallet_address: personal\u0085", "forbidden private field"),
        ("safe: ok\u2028wallet_address: personal\u2028", "forbidden private field"),
        ("safe: ok\u2029wallet_address: personal\u2029", "forbidden private field"),
        ("safe: ok\r? wallet_address\r: personal\r", "forbidden private field"),
        (
            "safe: ok\u0085? wallet_address\u0085: personal\u0085",
            "forbidden private field",
        ),
        (
            "safe: ok\u2028? wallet_address\u2028: personal\u2028",
            "forbidden private field",
        ),
        (
            "safe: ok\u2029? wallet_address\u2029: personal\u2029",
            "forbidden private field",
        ),
        (
            "plain prose\nname: &key wallet_address\nleak: {*key: personal}\n",
            "forbidden private field",
        ),
        ('@ invalid prefix\n? "api\n  key"\n: personal\n', "forbidden private field"),
        (
            'plain prose\nsafe: [? "api\n  key": personal]\n',
            "forbidden private field",
        ),
        ("plain prose\napi:key: personal\n", "forbidden private field"),
        ("@ invalid\napi:key: personal\n", "forbidden private field"),
        ('{"ａｐｉ＿ｋｅｙ":"personal"}\n', "forbidden private field"),
        ("ｐａｓｓｗｏｒｄ: personal\n", "forbidden private field"),
        ("ＡＰＩ＿ＫＥＹ: personal\n", "forbidden private field"),
        ("contact: alice@pri\u200bvate.com\n", "Unicode format"),
        ("contact: alice@pri\u200cvate.com\n", "Unicode format"),
        ("contact: alice@pri\u00advate.com\n", "Unicode format"),
        ("contact: alice@pri\u034fvate.com\n", "default-ignorable"),
        ("contact: alice@pri\ufe0fvate.com\n", "default-ignorable"),
        ("contact: alice@pri\u180bvate.com\n", "default-ignorable"),
        ("contact: alice@pri\U000e0100vate.com\n", "default-ignorable"),
        ("contact: alice@pri\u115fvate.com\n", "default-ignorable"),
        ("contact: alice@pri\u3164vate.com\n", "default-ignorable"),
        ("contact: alice@pri\u2065vate.com\n", "default-ignorable"),
        ("contact: alice@pri\ufff0vate.com\n", "default-ignorable"),
        ("contact: alice@pri\u0301vate.com\n", "email_account_identity"),
        ("contact: alice＠private．com\n", "email_account_identity"),
        ("endpoint: 192.\u200b168.1.2\n", "Unicode format"),
        ('contact: "alice@\\\r  private.com"\r', "email_account_identity"),
        ("diagnostic host localhost\n", "localhost identity"),
        ("diagnostic endpoint ::1\n", "private IPv6 endpoint"),
        ("diagnostic endpoint fe80::1234\n", "private IPv6 endpoint"),
        ("diagnostic endpoint fd12:3456::1\n", "private IPv6 endpoint"),
    ),
)
def test_evidence_privacy_catches_multidocument_fields_and_private_endpoints(
    finding_authority: dict[str, Any],
    evidence_text: str,
    message: str,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    evidence_path = finding_authority["evidence_path"]
    evidence_path.write_text(evidence_text, encoding="utf-8")
    value["evidence"][0]["sha256"] = hashlib.sha256(
        evidence_path.read_bytes()
    ).hexdigest()

    with pytest.raises(CapacityValidationError, match=message):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


@pytest.mark.parametrize(
    "unsafe_actual",
    (
        "{wallet_address: personal-wallet-name}",
        '"api\\u005fkey": live-api-key-value',
        'contact: "alice\\u0040private.com"',
        '{"ｐｒｏｊｅｃｔ＿ｉｄ":"personal"}',
        "alice&#64;private.com",
        "alice&#x40;private.com",
        r"alice\@private.com",
        r"alice@private\.com",
        '"\\"192\\\\u002e168\\\\u002e1\\\\u002e1\\""',
        '"\\"TO\\\\u0044O\\""',
        '"\\"alice\\\\u0040private\\\\u002ecom\\""',
        "alice&" + "amp;" * 7 + "#x40;private.com",
        "alice&" + "amp;" * 9 + "#x40;private.com",
        "ok&#x200b;",
        "alice&#8203;@private.com",
        "alice＠private．com",
    ),
)
def test_finding_prose_semantically_rejects_encoded_private_fields_and_values(
    finding_authority: dict[str, Any],
    unsafe_actual: str,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    value["actual"] = unsafe_actual

    with pytest.raises(CapacityValidationError, match="privacy"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_evidence_read_rejects_pathname_swap_even_with_identical_bytes(
    finding_authority: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    evidence_path = finding_authority["evidence_path"]
    evidence_identity = (
        evidence_path.stat().st_dev,
        evidence_path.stat().st_ino,
    )
    original_read = os.read
    swapped = False

    def read_and_swap(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        content = original_read(descriptor, count)
        descriptor_stat = os.fstat(descriptor)
        if (
            content
            and not swapped
            and (descriptor_stat.st_dev, descriptor_stat.st_ino) == evidence_identity
        ):
            swapped = True
            prior_path = evidence_path.with_name("observer-prior.json")
            evidence_path.rename(prior_path)
            evidence_path.write_bytes(prior_path.read_bytes())
        return content

    monkeypatch.setattr(os, "read", read_and_swap)
    with pytest.raises(
        CapacityValidationError,
        match=r"(?:file changed while it was read|pathname identity changed)",
    ):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_evidence_read_rejects_ancestor_swap_to_symlink(
    finding_authority: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    evidence_path = finding_authority["evidence_path"]
    evidence_directory = evidence_path.parent
    outside_directory = evidence_directory.parent.parent / "moved-evidence"
    evidence_identity = (
        evidence_path.stat().st_dev,
        evidence_path.stat().st_ino,
    )
    original_read = os.read
    swapped = False

    def read_and_swap(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        content = original_read(descriptor, count)
        descriptor_stat = os.fstat(descriptor)
        if (
            content
            and not swapped
            and (descriptor_stat.st_dev, descriptor_stat.st_ino) == evidence_identity
        ):
            swapped = True
            evidence_directory.rename(outside_directory)
            evidence_directory.symlink_to(
                outside_directory,
                target_is_directory=True,
            )
        return content

    monkeypatch.setattr(os, "read", read_and_swap)
    with pytest.raises(
        CapacityValidationError,
        match=r"(?:ancestor identity changed|ancestor changed)",
    ):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


def test_packet_replay_validates_all_private_parent_directories(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    ingested = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )
    body_path = (
        finding_authority["run_dir"] / ingested.index_record["occurrence_body_path"]
    )
    ingested.index_path.parent.chmod(0o755)

    with pytest.raises(CapacityValidationError, match="mode 0700"):
        load_capacity_finding_index_artifacts(
            ingested.source_path,
            ingested.index_path,
            body_path,
            repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


@pytest.mark.parametrize("failure_kind", ("write", "fsync"))
def test_create_once_write_or_fsync_error_removes_private_temporary_peer(
    finding_authority: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    failure_kind: str,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)

    def fail_write(_descriptor: int, _content: bytes) -> int:
        raise OSError("injected create-once write failure")

    if failure_kind == "write":
        monkeypatch.setattr(os, "write", fail_write)
    else:
        original_open = os.open
        original_fsync = os.fsync
        temporary_descriptors: set[int] = set()

        def track_temporary_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            mode: int = 0o777,
            *,
            dir_fd: int | None = None,
        ) -> int:
            descriptor = original_open(path, flags, mode, dir_fd=dir_fd)
            if str(path).endswith(".tmp"):
                temporary_descriptors.add(descriptor)
            return descriptor

        def fail_temporary_fsync(descriptor: int) -> None:
            if descriptor in temporary_descriptors:
                raise OSError("injected create-once fsync failure")
            original_fsync(descriptor)

        monkeypatch.setattr(os, "open", track_temporary_open)
        monkeypatch.setattr(os, "fsync", fail_temporary_fsync)
    with pytest.raises(CapacityValidationError, match="cannot write private"):
        ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=finding_authority["run_dir"],
        )

    assert not list(finding_authority["run_dir"].rglob(".*.tmp"))


def test_replace_error_removes_private_temporary_peer(
    finding_authority: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = finding_authority["run_dir"] / "managed-state.json"
    destination.write_bytes(b"original")
    destination.chmod(0o600)

    def fail_exchange(
        _directory_descriptor: int,
        _source: str,
        _destination: str,
        *,
        flags: int,
    ) -> None:
        del flags
        raise OSError("injected ledger exchange failure")

    monkeypatch.setattr(
        "issue_discovery.capacity_findings._renameat2",
        fail_exchange,
    )
    with pytest.raises(CapacityValidationError, match="cannot publish finding ledger"):
        replace_capacity_finding_private_file(
            destination,
            b"replacement",
            root=finding_authority["run_dir"],
        )

    assert destination.read_bytes() == b"original"
    assert not list(finding_authority["run_dir"].rglob(".*.tmp"))


def test_ingest_recovers_authenticated_unlinked_temporary_peer(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    temporary_path = (
        finding_authority["run_dir"]
        / f".{CAPACITY_FINDING_SOURCE_NAME}.123.{'1' * 24}.tmp"
    )
    temporary_path.write_bytes(b"interrupted private write")
    temporary_path.chmod(0o600)

    ingested = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    assert not temporary_path.exists()
    assert ingested.appended_source is True
    assert ingested.source_path.exists()


def test_ingest_preserves_safe_shaped_unmanaged_temporary_peer(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    temporary_path = (
        finding_authority["run_dir"] / f".unrelated-notes.123.{'9' * 24}.tmp"
    )
    content = b"current-user notes outside harness authority"
    temporary_path.write_bytes(content)
    temporary_path.chmod(0o600)

    ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    assert temporary_path.read_bytes() == content
    assert temporary_path.stat().st_mode & 0o777 == 0o600


def test_ingest_recovers_post_link_create_once_temporary_peer(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    source_directory = finding_authority["run_dir"] / "capacity-findings"
    source_directory.mkdir(mode=0o700)
    source_path = source_directory / f"{value['finding_id']}.json"
    temporary_path = source_directory / (f".{source_path.name}.123.{'2' * 24}.tmp")
    temporary_path.write_bytes(canonical_json_bytes(value))
    temporary_path.chmod(0o600)
    os.link(temporary_path, source_path)
    assert temporary_path.stat().st_nlink == 2

    ingested = ingest_capacity_finding(
        value,
        result,
        authority_repo_root=finding_authority["repo"],
        run_dir=finding_authority["run_dir"],
    )

    assert not temporary_path.exists()
    assert ingested.appended_source is False
    assert source_path.read_bytes() == canonical_json_bytes(value)
    assert source_path.stat().st_nlink == 1


def test_temporary_recovery_rejects_artifact_directory_identity_swap(
    finding_authority: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    run_dir = finding_authority["run_dir"]
    source_directory = run_dir / "capacity-findings"
    source_directory.mkdir(mode=0o700)
    source_identity = (
        source_directory.stat().st_dev,
        source_directory.stat().st_ino,
    )
    original_temporary = source_directory / (
        f".{value['finding_id']}.json.123.{'2' * 24}.tmp"
    )
    original_temporary.write_bytes(b"interrupted private write")
    original_temporary.chmod(0o600)
    held_directory = run_dir / "capacity-findings-held"
    replacement_temporary = source_directory / (
        f".{value['finding_id']}.json.456.{'3' * 24}.tmp"
    )
    original_listdir = os.listdir
    swapped = False

    def listdir_and_swap(path: int) -> list[str]:
        nonlocal swapped
        descriptor_stat = os.fstat(path)
        if (
            not swapped
            and (descriptor_stat.st_dev, descriptor_stat.st_ino)
            == source_identity
        ):
            swapped = True
            source_directory.rename(held_directory)
            source_directory.mkdir(mode=0o700)
            replacement_temporary.write_bytes(b"replacement authority data")
            replacement_temporary.chmod(0o600)
        return original_listdir(path)

    monkeypatch.setattr(os, "listdir", listdir_and_swap)
    with pytest.raises(
        CapacityValidationError,
        match="directory must retain one stable",
    ):
        ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=run_dir,
        )

    assert swapped is True
    assert replacement_temporary.read_bytes() == b"replacement authority data"
    assert not (source_directory / f"{value['finding_id']}.json").exists()


@pytest.mark.parametrize(
    "unsafe_kind",
    ("symlink", "directory", "wrong-mode", "too-many-links"),
)
def test_ingest_rejects_unsafe_orphan_temporary_peer(
    finding_authority: dict[str, Any],
    unsafe_kind: str,
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    temporary_path = (
        finding_authority["run_dir"]
        / f".{CAPACITY_FINDING_SOURCE_NAME}.123.{'3' * 24}.tmp"
    )
    if unsafe_kind == "symlink":
        target = temporary_path.with_name("outside-temporary-target")
        target.write_bytes(b"outside")
        target.chmod(0o600)
        temporary_path.symlink_to(target)
    elif unsafe_kind == "directory":
        temporary_path.mkdir(mode=0o700)
    else:
        temporary_path.write_bytes(b"unsafe temporary")
        temporary_path.chmod(0o644 if unsafe_kind == "wrong-mode" else 0o600)
        if unsafe_kind == "too-many-links":
            os.link(temporary_path, temporary_path.with_name("first-extra-link"))
            os.link(temporary_path, temporary_path.with_name("second-extra-link"))

    with pytest.raises(
        CapacityValidationError,
        match="unsafe private temporary file requires operator review",
    ):
        ingest_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            run_dir=finding_authority["run_dir"],
        )

    assert temporary_path.exists() or temporary_path.is_symlink()
    assert not (finding_authority["run_dir"] / "capacity-findings").exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFOs")
def test_evidence_reader_rejects_fifo_without_blocking(
    finding_authority: dict[str, Any],
) -> None:
    result = _validated_result(finding_authority)
    value = _finding(finding_authority, result)
    evidence_path = finding_authority["evidence_path"]
    evidence_path.unlink()
    os.mkfifo(evidence_path, mode=0o600)

    with pytest.raises(CapacityValidationError, match="regular file"):
        validate_capacity_finding(
            value,
            result,
            authority_repo_root=finding_authority["repo"],
            evidence_root=finding_authority["run_dir"],
        )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFOs")
@pytest.mark.parametrize("surface", ("private-read", "replacement", "recovery"))
def test_private_surfaces_reject_fifo_without_blocking(
    finding_authority: dict[str, Any],
    surface: str,
) -> None:
    run_dir = finding_authority["run_dir"]
    if surface == "recovery":
        fifo_path = (
            run_dir
            / f".{CAPACITY_FINDING_SOURCE_NAME}.123.{'4' * 24}.tmp"
        )
    else:
        fifo_path = run_dir / "managed-state.json"
    os.mkfifo(fifo_path, mode=0o600)

    if surface == "private-read":
        with pytest.raises(CapacityValidationError, match="regular file"):
            read_capacity_finding_private_file(
                fifo_path,
                root=run_dir,
            )
    elif surface == "replacement":
        with pytest.raises(
            CapacityValidationError,
            match="unsafe existing private finding destination",
        ):
            replace_capacity_finding_private_file(
                fifo_path,
                b"replacement",
                root=run_dir,
            )
    else:
        result = _validated_result(finding_authority)
        value = _finding(finding_authority, result)
        with pytest.raises(
            CapacityValidationError,
            match="unsafe private temporary file requires operator review",
        ):
            ingest_capacity_finding(
                value,
                result,
                authority_repo_root=finding_authority["repo"],
                run_dir=run_dir,
            )

    assert stat.S_ISFIFO(fifo_path.lstat().st_mode)


@pytest.mark.parametrize(
    "destination_kind",
    ("symlink", "directory", "wrong-mode", "hard-linked"),
)
def test_private_replace_rejects_unsafe_existing_destination(
    finding_authority: dict[str, Any],
    destination_kind: str,
) -> None:
    run_dir = finding_authority["run_dir"]
    destination = run_dir / "managed-state.json"
    if destination_kind == "symlink":
        outside = run_dir.parent / "outside-managed-state.json"
        outside.write_bytes(b"outside")
        outside.chmod(0o600)
        destination.symlink_to(outside)
    elif destination_kind == "directory":
        destination.mkdir(mode=0o700)
    else:
        destination.write_bytes(b"original")
        destination.chmod(0o644 if destination_kind == "wrong-mode" else 0o600)
        if destination_kind == "hard-linked":
            os.link(destination, run_dir / "managed-state-hardlink.json")

    with pytest.raises(
        CapacityValidationError,
        match="unsafe existing private finding destination",
    ):
        replace_capacity_finding_private_file(
            destination,
            b"replacement",
            root=run_dir,
        )

    assert not list(run_dir.glob(f".{destination.name}.*.tmp"))
    if destination_kind == "symlink":
        assert outside.read_bytes() == b"outside"
    elif destination_kind != "directory":
        assert destination.read_bytes() == b"original"


def test_private_read_rejects_ancestor_swap_to_symlink(
    finding_authority: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = finding_authority["run_dir"]
    private_directory = run_dir / "private"
    private_directory.mkdir(mode=0o700)
    private_path = private_directory / "state.json"
    private_path.write_bytes(b'{"state":"detected"}\n')
    private_path.chmod(0o600)
    private_identity = (private_path.stat().st_dev, private_path.stat().st_ino)
    moved_directory = run_dir / "private-held"
    original_read = os.read
    swapped = False

    def read_and_swap(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        content = original_read(descriptor, count)
        descriptor_stat = os.fstat(descriptor)
        if (
            content
            and not swapped
            and (descriptor_stat.st_dev, descriptor_stat.st_ino) == private_identity
        ):
            swapped = True
            private_directory.rename(moved_directory)
            private_directory.symlink_to(moved_directory, target_is_directory=True)
        return content

    monkeypatch.setattr(os, "read", read_and_swap)
    with pytest.raises(
        CapacityValidationError,
        match=r"(?:ancestor identity changed|ancestor changed)",
    ):
        read_capacity_finding_private_file(
            private_path,
            root=run_dir,
        )


@pytest.mark.parametrize("swap_kind", ("parent", "root", "root-symlink"))
def test_managed_write_rejects_parent_or_root_identity_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    swap_kind: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    private_directory = run_dir / "private"
    private_directory.mkdir(mode=0o700)
    destination = private_directory / "state.json"
    destination.write_bytes(b"original")
    destination.chmod(0o600)
    original_write = os.write
    swapped = False
    moved = tmp_path / f"held-{swap_kind}"

    def write_and_swap(descriptor: int, content: bytes) -> int:
        nonlocal swapped
        written = original_write(descriptor, content)
        if not swapped:
            swapped = True
            if swap_kind == "parent":
                private_directory.rename(moved)
                private_directory.mkdir(mode=0o700)
                visible_destination = private_directory / destination.name
            elif swap_kind == "root":
                run_dir.rename(moved)
                run_dir.mkdir(mode=0o700)
                visible_parent = run_dir / private_directory.name
                visible_parent.mkdir(mode=0o700)
                visible_destination = visible_parent / destination.name
            else:
                run_dir.rename(moved)
                visible_root = tmp_path / "visible-root"
                visible_root.mkdir(mode=0o700)
                visible_parent = visible_root / private_directory.name
                visible_parent.mkdir(mode=0o700)
                visible_destination = visible_parent / destination.name
                run_dir.symlink_to(visible_root, target_is_directory=True)
            visible_destination.write_bytes(b"untrusted-visible-state")
            visible_destination.chmod(0o600)
        return written

    monkeypatch.setattr(os, "write", write_and_swap)
    with pytest.raises(CapacityValidationError, match="identity changed"):
        replace_capacity_finding_private_file(
            destination,
            b"replacement",
            root=run_dir,
        )

    if swap_kind == "parent":
        assert (moved / destination.name).read_bytes() == b"original"
        visible_destination = private_directory / destination.name
    else:
        assert (
            moved / private_directory.name / destination.name
        ).read_bytes() == b"original"
        visible_destination = run_dir / private_directory.name / destination.name
    assert visible_destination.read_bytes() == b"untrusted-visible-state"
    assert not list(tmp_path.rglob(f".{destination.name}.*.tmp"))


@pytest.mark.parametrize("operation", ("create-once", "replace"))
def test_managed_write_rejects_temporary_pathname_swap_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    destination = run_dir / "managed-state.json"
    if operation == "replace":
        destination.write_bytes(b"original")
        destination.chmod(0o600)
    swapped = False

    def swap_temporary(source: str, directory_descriptor: int) -> None:
        nonlocal swapped
        if swapped:
            return
        swapped = True
        os.rename(
            source,
            f"{source}.held",
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        replacement_descriptor = os.open(
            source,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=directory_descriptor,
        )
        try:
            os.write(replacement_descriptor, b"untrusted replacement")
            os.fsync(replacement_descriptor)
        finally:
            os.close(replacement_descriptor)

    if operation == "create-once":
        original_link = os.link

        def publish_swapped_temporary(
            source: str,
            target: str,
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
            follow_symlinks: bool = True,
        ) -> None:
            assert src_dir_fd is not None
            assert dst_dir_fd == src_dir_fd
            swap_temporary(source, src_dir_fd)
            original_link(
                source,
                target,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
                follow_symlinks=follow_symlinks,
            )

        monkeypatch.setattr(os, "link", publish_swapped_temporary)
    else:
        from issue_discovery import capacity_findings

        original_exchange = capacity_findings._renameat2

        def exchange_swapped_temporary(
            directory_descriptor: int,
            source: str,
            target: str,
            *,
            flags: int,
        ) -> None:
            swap_temporary(source, directory_descriptor)
            original_exchange(
                directory_descriptor,
                source,
                target,
                flags=flags,
            )

        monkeypatch.setattr(capacity_findings, "_renameat2", exchange_swapped_temporary)
    with pytest.raises(CapacityValidationError, match="identity"):
        if operation == "create-once":
            _write_new_private_file(
                destination,
                b"trusted publication",
                root=run_dir,
            )
        else:
            replace_capacity_finding_private_file(
                destination,
                b"trusted publication",
                root=run_dir,
            )

    assert swapped is True
    assert destination.read_bytes() == b"untrusted replacement"
    assert b"trusted publication" not in destination.read_bytes()


@pytest.mark.parametrize("operation", ("create-once", "replace"))
def test_managed_write_rejects_temporary_content_mutation_during_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    destination = run_dir / "managed-state.json"
    if operation == "replace":
        destination.write_bytes(b"original")
        destination.chmod(0o600)
    untrusted = b"mutated through the held temporary inode"
    mutated = False

    def mutate_temporary(source: str, directory_descriptor: int) -> None:
        nonlocal mutated
        if mutated:
            return
        mutated = True
        descriptor = os.open(
            source,
            os.O_WRONLY | os.O_NOFOLLOW,
            dir_fd=directory_descriptor,
        )
        try:
            os.ftruncate(descriptor, 0)
            os.write(descriptor, untrusted)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    if operation == "create-once":
        original_link = os.link

        def link_after_content_mutation(
            source: str,
            target: str,
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
            follow_symlinks: bool = True,
        ) -> None:
            assert src_dir_fd is not None
            assert dst_dir_fd == src_dir_fd
            mutate_temporary(source, src_dir_fd)
            original_link(
                source,
                target,
                src_dir_fd=src_dir_fd,
                dst_dir_fd=dst_dir_fd,
                follow_symlinks=follow_symlinks,
            )

        monkeypatch.setattr(os, "link", link_after_content_mutation)
    else:
        from issue_discovery import capacity_findings

        original_exchange = capacity_findings._renameat2

        def exchange_after_content_mutation(
            directory_descriptor: int,
            source: str,
            target: str,
            *,
            flags: int,
        ) -> None:
            mutate_temporary(source, directory_descriptor)
            original_exchange(
                directory_descriptor,
                source,
                target,
                flags=flags,
            )

        monkeypatch.setattr(
            capacity_findings,
            "_renameat2",
            exchange_after_content_mutation,
        )

    with pytest.raises(
        CapacityValidationError,
        match="bytes or descriptor authority changed",
    ):
        if operation == "create-once":
            _write_new_private_file(
                destination,
                b"trusted publication",
                root=run_dir,
            )
        else:
            replace_capacity_finding_private_file(
                destination,
                b"trusted publication",
                root=run_dir,
            )

    assert mutated is True
    assert destination.read_bytes() == untrusted


def test_private_replace_rolls_back_destination_swap_during_exchange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    destination = run_dir / "managed-state.json"
    destination.write_bytes(b"original")
    destination.chmod(0o600)
    held_destination = run_dir / "managed-state-held.json"
    substitute = b"same-user substitute"
    from issue_discovery import capacity_findings

    original_exchange = capacity_findings._renameat2
    swapped = False

    def exchange_after_destination_swap(
        directory_descriptor: int,
        source: str,
        target: str,
        *,
        flags: int,
    ) -> None:
        nonlocal swapped
        if not swapped:
            swapped = True
            os.rename(
                target,
                held_destination.name,
                src_dir_fd=directory_descriptor,
                dst_dir_fd=directory_descriptor,
            )
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_descriptor,
            )
            try:
                os.write(descriptor, substitute)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        original_exchange(
            directory_descriptor,
            source,
            target,
            flags=flags,
        )

    monkeypatch.setattr(
        capacity_findings,
        "_renameat2",
        exchange_after_destination_swap,
    )

    with pytest.raises(
        CapacityValidationError,
        match="destination identity or bytes changed during publication",
    ):
        replace_capacity_finding_private_file(
            destination,
            b"trusted publication",
            root=run_dir,
        )

    assert swapped is True
    assert destination.read_bytes() == substitute
    assert held_destination.read_bytes() == b"original"
    assert not list(run_dir.glob(f".{destination.name}.*.tmp"))


def test_private_replace_rolls_back_same_size_destination_mutation_during_exchange(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    destination = run_dir / "managed-state.json"
    destination.write_bytes(b"original")
    destination.chmod(0o600)
    original_times = destination.stat()
    from issue_discovery import capacity_findings

    original_exchange = capacity_findings._renameat2
    mutated = False

    def exchange_after_in_place_mutation(
        directory_descriptor: int,
        source: str,
        target: str,
        *,
        flags: int,
    ) -> None:
        nonlocal mutated
        if not mutated:
            mutated = True
            descriptor = os.open(
                target,
                os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW,
                dir_fd=directory_descriptor,
            )
            try:
                os.write(descriptor, b"modified")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.utime(
                target,
                ns=(
                    original_times.st_atime_ns,
                    original_times.st_mtime_ns,
                ),
                dir_fd=directory_descriptor,
                follow_symlinks=False,
            )
        original_exchange(
            directory_descriptor,
            source,
            target,
            flags=flags,
        )

    monkeypatch.setattr(
        capacity_findings,
        "_renameat2",
        exchange_after_in_place_mutation,
    )

    with pytest.raises(
        CapacityValidationError,
        match="destination identity or bytes changed during publication",
    ):
        replace_capacity_finding_private_file(
            destination,
            b"trusted publication",
            root=run_dir,
        )

    assert mutated is True
    assert destination.read_bytes() == b"modified"
    assert not list(run_dir.glob(f".{destination.name}.*.tmp"))


@pytest.mark.parametrize("operation", ("create-once", "replace"))
def test_managed_write_rejects_destination_swap_during_directory_fsync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir(mode=0o700)
    destination = run_dir / "managed-state.json"
    if operation == "replace":
        destination.write_bytes(b"original")
        destination.chmod(0o600)
    original_fsync = os.fsync
    swapped = False

    def fsync_and_swap(descriptor: int) -> None:
        nonlocal swapped
        descriptor_stat = os.fstat(descriptor)
        if stat.S_ISDIR(descriptor_stat.st_mode) and not swapped:
            swapped = True
            destination.rename(run_dir / "published-held.json")
            destination.write_bytes(b"untrusted replacement")
            destination.chmod(0o600)
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fsync_and_swap)
    with pytest.raises(CapacityValidationError, match="identity is invalid"):
        if operation == "create-once":
            _write_new_private_file(
                destination,
                b"trusted publication",
                root=run_dir,
            )
        else:
            replace_capacity_finding_private_file(
                destination,
                b"trusted publication",
                root=run_dir,
            )

    assert swapped is True
    assert destination.read_bytes() == b"untrusted replacement"
    assert (run_dir / "published-held.json").read_bytes() == b"trusted publication"


def test_ingest_lock_rejects_lock_path_identity_replacement(
    finding_authority: dict[str, Any],
) -> None:
    run_dir = finding_authority["run_dir"]
    lock_path = run_dir / CAPACITY_FINDING_INGEST_LOCK_NAME

    with pytest.raises(CapacityValidationError, match="lock must retain"):
        with capacity_finding_ingest_lock(run_dir):
            replacement = run_dir / "replacement-lock"
            replacement.write_bytes(b"")
            replacement.chmod(0o600)
            os.replace(replacement, lock_path)


def test_replaced_lock_path_does_not_admit_a_second_compliant_writer(
    finding_authority: dict[str, Any],
) -> None:
    run_dir = finding_authority["run_dir"]
    lock_path = run_dir / CAPACITY_FINDING_INGEST_LOCK_NAME
    process: subprocess.Popen[str] | None = None
    script = """
import sys
from pathlib import Path
from issue_discovery.capacity_findings import capacity_finding_ingest_lock

print("ready", flush=True)
with capacity_finding_ingest_lock(Path(sys.argv[1])):
    print("acquired", flush=True)
"""

    try:
        with pytest.raises(CapacityValidationError, match="lock must retain"):
            with capacity_finding_ingest_lock(run_dir):
                replacement = run_dir / "replacement-lock"
                replacement.write_bytes(b"")
                replacement.chmod(0o600)
                os.replace(replacement, lock_path)
                process = subprocess.Popen(
                    [sys.executable, "-c", script, str(run_dir)],
                    cwd=repo_root(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                assert process.stdout is not None
                assert process.stdout.readline().strip() == "ready"
                with pytest.raises(subprocess.TimeoutExpired):
                    process.wait(timeout=0.5)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
