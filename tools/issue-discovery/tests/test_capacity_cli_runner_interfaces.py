from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from issue_discovery import capacity_outcomes, capacity_roles
from issue_discovery.capacity import CapacityValidationError
from issue_discovery.cli import main
from issue_discovery.runner import (
    DiscoveryRunner,
    _ValidatedActionContext,
    _ValidatedCapacityResultContext,
    _ValidatedEvidenceBundle,
    _capacity_result_context_paths,
    _validated_capacity_result_context,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def capacity_result_context_value(
    **updates: object,
) -> dict[str, object]:
    value: dict[str, object] = {
        "capacity_result": "private/result.json",
        "oracle_authority": "private/oracle.json",
        "reference_policy": None,
        "observer_plan": None,
        "actor_set": "private/actor-set.json",
        "concurrency_policy": "private/concurrency-policy.json",
        "role_plans": ["private/plan.json"],
        "role_receipts": ["private/receipt.json"],
        "frozen_actions": ["private/action.json"],
        "payloads": ["private/payload.json"],
        "action_results": ["private/action-result.json"],
    }
    value.update(updates)
    return value


@pytest.mark.parametrize(
    ("command", "arguments", "method_name", "operation"),
    [
        (
            "evaluation-policy-validate",
            [
                "evaluation-policy.json",
                "--expected-scm-ref",
                "b" * 40,
            ],
            "capacity_evaluation_policy",
            "validate",
        ),
        (
            "evaluation-policy-sha256",
            [
                "evaluation-policy.json",
                "--expected-scm-ref",
                "b" * 40,
            ],
            "capacity_evaluation_policy",
            "sha256",
        ),
        (
            "reference-policy-validate",
            [
                "reference-policy.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--observer-plan",
                "observer-plan.json",
                "--host-plan",
                "host-plan.json",
                "--expected-scm-ref",
                "b" * 40,
            ],
            "capacity_reference_policy",
            "validate",
        ),
        (
            "reference-policy-sha256",
            [
                "reference-policy.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--observer-plan",
                "observer-plan.json",
                "--host-plan",
                "host-plan.json",
                "--expected-scm-ref",
                "b" * 40,
            ],
            "capacity_reference_policy",
            "sha256",
        ),
        (
            "capacity-result-validate",
            [
                "result-context.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--expected-scm-ref",
                "b" * 40,
            ],
            "capacity_result",
            "validate",
        ),
        (
            "capacity-result-sha256",
            [
                "result-context.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--predecessor-context",
                "predecessor-context.json",
                "--reuse-baseline-context",
                "reuse-baseline-context.json",
                "--buyer-frontier",
                "buyer-frontier.json",
                "--buyer-result-context",
                "b1-context.json",
                "--buyer-result-context",
                "b2-context.json",
                "--prior-seller-context",
                "prior-seller-context.json",
                "--expected-scm-ref",
                "b" * 40,
            ],
            "capacity_result",
            "sha256",
        ),
        (
            "serialized-reuse-validate",
            [
                "reuse-a-context.json",
                "reuse-b-context.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--expected-scm-ref",
                "b" * 40,
            ],
            "capacity_serialized_reuse",
            "validate",
        ),
        (
            "serialized-reuse-sha256",
            [
                "reuse-a-context.json",
                "reuse-b-context.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--buyer-frontier",
                "buyer-frontier.json",
                "--buyer-result-context",
                "b1-context.json",
                "--buyer-result-context",
                "b2-context.json",
                "--expected-scm-ref",
                "b" * 40,
            ],
            "capacity_serialized_reuse",
            "sha256",
        ),
        (
            "buyer-frontier-validate",
            [
                "buyer-frontier.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--result-context",
                "b1-context.json",
                "--result-context",
                "b2-context.json",
                "--expected-scm-ref",
                "b" * 40,
            ],
            "capacity_buyer_frontier",
            "validate",
        ),
        (
            "buyer-frontier-sha256",
            [
                "buyer-frontier.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--result-context",
                "b1-context.json",
                "--result-context",
                "b2-context.json",
                "--expected-scm-ref",
                "b" * 40,
            ],
            "capacity_buyer_frontier",
            "sha256",
        ),
        (
            "role-plan-validate",
            ["plan.json"],
            "capacity_role_plan",
            "validate",
        ),
        (
            "role-plan-sha256",
            ["plan.json"],
            "capacity_role_plan",
            "sha256",
        ),
        (
            "role-receipt-validate",
            ["receipt.json", "--role-plan", "plan.json"],
            "capacity_role_receipt",
            "validate",
        ),
        (
            "role-receipt-sha256",
            ["receipt.json", "--role-plan", "plan.json"],
            "capacity_role_receipt",
            "sha256",
        ),
        (
            "oracle-authority-validate",
            ["oracle.json"],
            "capacity_oracle_authority",
            "validate",
        ),
        (
            "oracle-authority-sha256",
            ["oracle.json"],
            "capacity_oracle_authority",
            "sha256",
        ),
        (
            "concurrency-policy-validate",
            ["policy.json", "--role-plan", "plan.json"],
            "capacity_concurrency_policy",
            "validate",
        ),
        (
            "concurrency-policy-sha256",
            ["policy.json", "--role-plan", "plan.json"],
            "capacity_concurrency_policy",
            "sha256",
        ),
        (
            "frozen-action-validate",
            [
                "action.json",
                "--role-plan",
                "plan.json",
                "--payload",
                "payload.json",
                "--oracle-authority",
                "oracle.json",
            ],
            "capacity_frozen_action",
            "validate",
        ),
        (
            "frozen-action-sha256",
            [
                "action.json",
                "--role-plan",
                "plan.json",
                "--payload",
                "payload.json",
                "--oracle-authority",
                "oracle.json",
            ],
            "capacity_frozen_action",
            "sha256",
        ),
        (
            "action-result-validate",
            [
                "result.json",
                "--frozen-action",
                "action.json",
                "--role-plan",
                "plan.json",
                "--payload",
                "payload.json",
                "--oracle-authority",
                "oracle.json",
            ],
            "capacity_action_result",
            "validate",
        ),
        (
            "action-result-sha256",
            [
                "result.json",
                "--frozen-action",
                "action.json",
                "--role-plan",
                "plan.json",
                "--payload",
                "payload.json",
                "--oracle-authority",
                "oracle.json",
            ],
            "capacity_action_result",
            "sha256",
        ),
        (
            "actor-set-validate",
            [
                "actor-set.json",
                "--concurrency-policy",
                "policy.json",
                "--role-plan",
                "plan.json",
                "--role-receipt",
                "receipt.json",
                "--frozen-action",
                "action.json",
                "--payload",
                "payload.json",
                "--oracle-authority",
                "oracle.json",
                "--action-result",
                "result.json",
            ],
            "capacity_actor_set",
            "validate",
        ),
        (
            "actor-set-sha256",
            [
                "actor-set.json",
                "--concurrency-policy",
                "policy.json",
                "--role-plan",
                "plan.json",
                "--role-receipt",
                "receipt.json",
                "--frozen-action",
                "action.json",
                "--payload",
                "payload.json",
                "--oracle-authority",
                "oracle.json",
                "--action-result",
                "result.json",
            ],
            "capacity_actor_set",
            "sha256",
        ),
        (
            "mock-capture-validate",
            [
                "capture.json",
                "--role-plan",
                "plan.json",
                "--role-receipt",
                "receipt.json",
                "--frozen-action",
                "action.json",
                "--payload",
                "payload.json",
                "--oracle-authority",
                "oracle.json",
                "--action-result",
                "result.json",
            ],
            "capacity_mock_capture",
            "validate",
        ),
        (
            "mock-capture-sha256",
            [
                "capture.json",
                "--role-plan",
                "plan.json",
                "--role-receipt",
                "receipt.json",
                "--frozen-action",
                "action.json",
                "--payload",
                "payload.json",
                "--oracle-authority",
                "oracle.json",
                "--action-result",
                "result.json",
            ],
            "capacity_mock_capture",
            "sha256",
        ),
    ],
)
def test_capacity_artifact_commands_use_explicit_paths_and_operation(
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    arguments: list[str],
    method_name: str,
    operation: str,
) -> None:
    root = repo_root()
    call: dict[str, object] = {}

    def fake(self, *args, **kwargs):
        call["repo_root"] = self.repo_root
        call["args"] = args
        call["kwargs"] = kwargs
        return 0

    monkeypatch.setattr(DiscoveryRunner, f"{method_name}_{operation}", fake)

    assert (
        main(
            [
                "--repo-root",
                str(root),
                "capacity",
                command,
                *arguments,
            ]
        )
        == 0
    )
    assert call["repo_root"] == root
    assert "operation" not in call["kwargs"]
    rendered = repr((call["args"], call["kwargs"]))
    for name in (
        "plan.json",
        "receipt.json",
        "oracle.json",
        "policy.json",
        "action.json",
        "payload.json",
        "result.json",
        "actor-set.json",
        "capture.json",
        "evaluation-policy.json",
        "reference-policy.json",
        "observer-plan.json",
        "host-plan.json",
        "result-context.json",
        "predecessor-context.json",
        "reuse-baseline-context.json",
        "prior-seller-context.json",
        "reuse-a-context.json",
        "reuse-b-context.json",
        "buyer-frontier.json",
        "b1-context.json",
        "b2-context.json",
    ):
        if name in arguments:
            assert str(root / name) in rendered


def test_capacity_result_cli_forwards_complete_progression_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repo_root()
    call: dict[str, object] = {}

    def fake(self, context_manifest, **kwargs):
        call.update(
            {
                "context_manifest": context_manifest,
                **kwargs,
            }
        )
        return 0

    monkeypatch.setattr(
        DiscoveryRunner,
        "capacity_result_validate",
        fake,
    )

    assert (
        main(
            [
                "--repo-root",
                str(root),
                "capacity",
                "capacity-result-validate",
                "seller-current.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--predecessor-context",
                "reuse-a.json",
                "--reuse-baseline-context",
                "reuse-b.json",
                "--buyer-frontier",
                "buyer-frontier.json",
                "--buyer-result-context",
                "b1.json",
                "--buyer-result-context",
                "b2.json",
                "--prior-seller-context",
                "seller-1.json",
                "--prior-seller-context",
                "seller-2.json",
                "--expected-scm-ref",
                "a" * 40,
            ]
        )
        == 0
    )
    assert call["context_manifest"] == root / "seller-current.json"
    assert call["predecessor_context"] == root / "reuse-a.json"
    assert call["reuse_baseline_context"] == root / "reuse-b.json"
    assert call["buyer_frontier"] == root / "buyer-frontier.json"
    assert call["buyer_result_contexts"] == (
        root / "b1.json",
        root / "b2.json",
    )
    assert call["prior_seller_contexts"] == (
        root / "seller-1.json",
        root / "seller-2.json",
    )


def test_serialized_reuse_cli_allows_qualification_without_frontier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repo_root()
    call: dict[str, object] = {}

    def fake(self, reuse_a_context, reuse_b_context, **kwargs):
        call.update(
            {
                "reuse_a_context": reuse_a_context,
                "reuse_b_context": reuse_b_context,
                **kwargs,
            }
        )
        return 0

    monkeypatch.setattr(
        DiscoveryRunner,
        "capacity_serialized_reuse_validate",
        fake,
    )

    assert (
        main(
            [
                "--repo-root",
                str(root),
                "capacity",
                "serialized-reuse-validate",
                "reuse-a.json",
                "reuse-b.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--expected-scm-ref",
                "a" * 40,
            ]
        )
        == 0
    )
    assert call["reuse_a_context"] == root / "reuse-a.json"
    assert call["reuse_b_context"] == root / "reuse-b.json"
    assert call["buyer_frontier"] is None
    assert call["buyer_result_contexts"] == ()


def test_serialized_reuse_cli_forwards_frontier_and_ordered_buyers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repo_root()
    call: dict[str, object] = {}

    def fake(self, reuse_a_context, reuse_b_context, **kwargs):
        call.update(
            {
                "reuse_a_context": reuse_a_context,
                "reuse_b_context": reuse_b_context,
                **kwargs,
            }
        )
        return 0

    monkeypatch.setattr(
        DiscoveryRunner,
        "capacity_serialized_reuse_validate",
        fake,
    )

    assert (
        main(
            [
                "--repo-root",
                str(root),
                "capacity",
                "serialized-reuse-validate",
                "reuse-a.json",
                "reuse-b.json",
                "--evaluation-policy",
                "evaluation-policy.json",
                "--buyer-frontier",
                "buyer-frontier.json",
                "--buyer-result-context",
                "b1.json",
                "--buyer-result-context",
                "b2.json",
                "--expected-scm-ref",
                "a" * 40,
            ]
        )
        == 0
    )
    assert call["reuse_a_context"] == root / "reuse-a.json"
    assert call["reuse_b_context"] == root / "reuse-b.json"
    assert call["buyer_frontier"] == root / "buyer-frontier.json"
    assert call["buyer_result_contexts"] == (
        root / "b1.json",
        root / "b2.json",
    )


@pytest.mark.parametrize(
    "arguments",
    [
        ["evaluation-policy-validate", "evaluation-policy.json"],
        [
            "reference-policy-validate",
            "reference-policy.json",
            "--evaluation-policy",
            "evaluation-policy.json",
            "--observer-plan",
            "observer-plan.json",
            "--host-plan",
            "host-plan.json",
        ],
        [
            "capacity-result-validate",
            "result-context.json",
            "--evaluation-policy",
            "evaluation-policy.json",
        ],
        [
            "serialized-reuse-validate",
            "reuse-a-context.json",
            "reuse-b-context.json",
            "--evaluation-policy",
            "evaluation-policy.json",
            "--buyer-frontier",
            "buyer-frontier.json",
            "--buyer-result-context",
            "b1-context.json",
        ],
        [
            "buyer-frontier-validate",
            "buyer-frontier.json",
            "--evaluation-policy",
            "evaluation-policy.json",
            "--result-context",
            "b1-context.json",
        ],
    ],
)
def test_outcome_commands_require_caller_selected_scm_ref(
    arguments: list[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["capacity", *arguments])

    assert exit_info.value.code == 2


def test_capacity_result_context_is_strict_path_only_and_repo_relative(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(capacity_result_context_value()),
        encoding="utf-8",
    )

    paths = _capacity_result_context_paths(manifest, root)

    assert paths.capacity_result == root / "private" / "result.json"
    assert paths.oracle_authority == root / "private" / "oracle.json"
    assert paths.reference_policy is None
    assert paths.observer_plan is None
    assert paths.actor_set == root / "private" / "actor-set.json"
    assert paths.role_plans == (root / "private" / "plan.json",)


@pytest.mark.parametrize(
    "value",
    [
        capacity_result_context_value(extra="not-allowed"),
        capacity_result_context_value(role_plans={"path": "plan.json"}),
        capacity_result_context_value(
            role_plans=["private/plan.json", "private/plan.json"],
        ),
        capacity_result_context_value(capacity_result={"embedded": "value"}),
    ],
)
def test_capacity_result_context_rejects_non_path_or_ambiguous_input(
    tmp_path: Path,
    value: dict[str, object],
) -> None:
    manifest = tmp_path / "context.json"
    manifest.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(CapacityValidationError):
        _capacity_result_context_paths(manifest, tmp_path)


def test_capacity_result_context_rejects_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    manifest = tmp_path / "context.json"
    manifest.write_text(
        '{"capacity_result":"a","capacity_result":"b"}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        CapacityValidationError,
        match="duplicate object key",
    ):
        _capacity_result_context_paths(manifest, tmp_path)


def test_agent_result_context_preserves_failed_actor_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "result.json").write_text(
        json.dumps({"execution_boundary": "real-measured"}),
        encoding="utf-8",
    )
    (private / "actor-set.json").write_text("{}\n", encoding="utf-8")
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(capacity_result_context_value()),
        encoding="utf-8",
    )
    oracle = SimpleNamespace(canonical_sha256="a" * 64)
    policy = object()
    evidence = (object(),)
    bundle = _ValidatedEvidenceBundle(
        evidence=evidence,
        concurrency_policy=policy,
        oracle_authorities=(oracle,),
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evidence_bundle",
        lambda **kwargs: bundle,
    )
    observation = SimpleNamespace(
        capacity_eligible=False,
        load_generator_passed=False,
        failure_reasons=("controller-throttle-observed",),
    )
    actor_call: dict[str, object] = {}

    def fake_actor_observation(value, selected_policy, selected_evidence):
        actor_call.update(
            {
                "value": value,
                "policy": selected_policy,
                "evidence": selected_evidence,
            }
        )
        return observation

    monkeypatch.setattr(
        capacity_roles,
        "validate_actor_set_observation",
        fake_actor_observation,
    )
    validated_result = object()
    result_call: dict[str, object] = {}

    def fake_result(value, root, **kwargs):
        result_call.update({"value": value, "root": root, **kwargs})
        return validated_result

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_capacity_result",
        fake_result,
    )
    evaluation_policy = object()

    context = _validated_capacity_result_context(
        manifest,
        tmp_path,
        evaluation_policy=evaluation_policy,
        expected_scm_ref="b" * 40,
    )

    assert context.result is validated_result
    assert context.actor_set is observation
    assert actor_call == {
        "value": {},
        "policy": policy,
        "evidence": evidence,
    }
    assert result_call["actor_set"] is observation
    assert result_call["role_evidence"] == evidence
    assert result_call["oracle_authority"] is oracle
    assert result_call["reference_policy"] is None
    assert result_call["evaluation_policy"] is evaluation_policy
    assert result_call["expected_scm_ref"] == "b" * 40


def test_reference_result_context_reconstructs_observer_host_and_oracle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "result.json").write_text(
        json.dumps({"execution_boundary": "real-reference"}),
        encoding="utf-8",
    )
    (private / "oracle.json").write_text("{}\n", encoding="utf-8")
    (private / "reference-policy.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    (private / "observer-receipt.json").write_text(
        json.dumps(
            {
                "receipt_id": "observer-receipt",
                "plan_id": "observer-plan",
            }
        ),
        encoding="utf-8",
    )
    (private / "host-receipt.json").write_text(
        json.dumps(
            {
                "receipt_id": "host-receipt",
                "plan_id": "host-plan",
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(
            capacity_result_context_value(
                reference_policy="private/reference-policy.json",
                observer_plan="private/observer-plan.json",
                actor_set=None,
                concurrency_policy=None,
                role_plans=["private/host-plan.json"],
                role_receipts=[
                    "private/observer-receipt.json",
                    "private/host-receipt.json",
                ],
                frozen_actions=[],
                payloads=[],
                action_results=[],
            )
        ),
        encoding="utf-8",
    )
    observer = SimpleNamespace(
        plan_id="observer-plan",
        role="observer",
    )
    host = SimpleNamespace(
        plan_id="host-plan",
        role="host-operator",
    )
    plan_calls: list[tuple[str, str]] = []

    def fake_observer_plan(path, root, *, expected_scm_ref):
        plan_calls.append((path.name, expected_scm_ref))
        return observer

    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plan",
        fake_observer_plan,
    )

    def fake_supporting_plans(paths, root, *, expected_scm_ref):
        plan_calls.extend((path.name, expected_scm_ref) for path in paths)
        return (host,)

    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plans",
        fake_supporting_plans,
    )
    receipts = {
        "observer-plan": SimpleNamespace(receipt_id="observer-receipt"),
        "host-plan": SimpleNamespace(receipt_id="host-receipt"),
    }
    receipt_calls: list[tuple[dict[str, object], object]] = []

    def fake_receipt(value, plan):
        receipt_calls.append((value, plan))
        return receipts[plan.plan_id]

    monkeypatch.setattr(
        capacity_roles,
        "validate_role_receipt",
        fake_receipt,
    )
    evidence_by_plan: dict[str, object] = {}

    def fake_evidence(plan, receipt, actions, results):
        evidence = SimpleNamespace(
            plan=plan,
            receipt=receipt,
            actions=actions,
            results=results,
        )
        evidence_by_plan[plan.plan_id] = evidence
        return evidence

    monkeypatch.setattr(
        capacity_roles,
        "validate_substantive_role_evidence",
        fake_evidence,
    )
    oracle = SimpleNamespace(
        scm_ref="b" * 40,
        canonical_sha256="c" * 64,
    )
    oracle_call: dict[str, object] = {}

    def fake_oracle(value, root, *, observer_plan):
        oracle_call.update(
            {
                "value": value,
                "root": root,
                "observer_plan": observer_plan,
            }
        )
        return oracle

    monkeypatch.setattr(
        capacity_roles,
        "validate_oracle_authority",
        fake_oracle,
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evidence_bundle",
        lambda **kwargs: pytest.fail("reference used agent evidence"),
    )
    reference_policy = object()
    policy_call: dict[str, object] = {}
    validation_events: list[str] = []

    def fake_reference_policy(value, root, **kwargs):
        validation_events.append("reference-policy")
        policy_call.update({"value": value, "root": root, **kwargs})
        return reference_policy

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_reference_policy",
        fake_reference_policy,
    )
    result_call: dict[str, object] = {}

    def fake_result(value, root, **kwargs):
        validation_events.append("capacity-result")
        result_call.update({"value": value, "root": root, **kwargs})
        return object()

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_capacity_result",
        fake_result,
    )
    evaluation_policy = object()

    context = _validated_capacity_result_context(
        manifest,
        tmp_path,
        evaluation_policy=evaluation_policy,
        expected_scm_ref="b" * 40,
    )

    assert context.actor_set is None
    assert context.role_evidence == (
        evidence_by_plan["observer-plan"],
        evidence_by_plan["host-plan"],
    )
    assert plan_calls == [
        ("observer-plan.json", "b" * 40),
        ("host-plan.json", "b" * 40),
    ]
    assert {(value["plan_id"], plan.plan_id) for value, plan in receipt_calls} == {
        ("observer-plan", "observer-plan"),
        ("host-plan", "host-plan"),
    }
    assert all(
        not evidence.actions and not evidence.results
        for evidence in context.role_evidence
    )
    assert oracle_call["observer_plan"] is observer
    assert validation_events == ["reference-policy", "capacity-result"]
    assert policy_call == {
        "value": {},
        "root": tmp_path,
        "evaluation_policy": evaluation_policy,
        "observer_plan": observer,
        "host_plan": host,
        "expected_scm_ref": "b" * 40,
    }
    assert result_call["actor_set"] is None
    assert result_call["role_evidence"] == context.role_evidence
    assert result_call["oracle_authority"] is oracle
    assert result_call["reference_policy"] is reference_policy


def test_reference_result_context_requires_reference_policy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "result.json").write_text(
        json.dumps({"execution_boundary": "real-reference"}),
        encoding="utf-8",
    )
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(
            capacity_result_context_value(
                observer_plan="private/observer-plan.json",
                actor_set=None,
                concurrency_policy=None,
                role_plans=["private/host-plan.json"],
                role_receipts=[],
                frozen_actions=[],
                payloads=[],
                action_results=[],
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plan",
        lambda *args, **kwargs: pytest.fail(
            "reference without policy reached role reconstruction"
        ),
    )

    with pytest.raises(
        CapacityValidationError,
        match="reference capacity-result context requires",
    ):
        _validated_capacity_result_context(
            manifest,
            tmp_path,
            evaluation_policy=object(),
            expected_scm_ref="b" * 40,
        )


def test_agent_result_context_rejects_reference_policy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "result.json").write_text(
        json.dumps({"execution_boundary": "real-measured"}),
        encoding="utf-8",
    )
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(
            capacity_result_context_value(
                reference_policy="private/reference-policy.json",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evidence_bundle",
        lambda **kwargs: pytest.fail(
            "wrong-boundary reference policy reached agent reconstruction"
        ),
    )

    with pytest.raises(
        CapacityValidationError,
        match="agent capacity-result context requires",
    ):
        _validated_capacity_result_context(
            manifest,
            tmp_path,
            evaluation_policy=object(),
            expected_scm_ref="b" * 40,
        )


def test_reference_result_context_rejects_stale_reference_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "result.json").write_text(
        json.dumps({"execution_boundary": "real-reference"}),
        encoding="utf-8",
    )
    (private / "oracle.json").write_text("{}\n", encoding="utf-8")
    (private / "reference-policy.json").write_text(
        "{}\n",
        encoding="utf-8",
    )
    for role in ("observer", "host"):
        (private / f"{role}-receipt.json").write_text(
            json.dumps(
                {
                    "receipt_id": f"{role}-receipt",
                    "plan_id": f"{role}-plan",
                }
            ),
            encoding="utf-8",
        )
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(
            capacity_result_context_value(
                reference_policy="private/reference-policy.json",
                observer_plan="private/observer-plan.json",
                actor_set=None,
                concurrency_policy=None,
                role_plans=["private/host-plan.json"],
                role_receipts=[
                    "private/observer-receipt.json",
                    "private/host-receipt.json",
                ],
                frozen_actions=[],
                payloads=[],
                action_results=[],
            )
        ),
        encoding="utf-8",
    )
    observer = SimpleNamespace(
        plan_id="observer-plan",
        role="observer",
    )
    host = SimpleNamespace(
        plan_id="host-plan",
        role="host-operator",
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plan",
        lambda *args, **kwargs: observer,
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plans",
        lambda *args, **kwargs: (host,),
    )
    monkeypatch.setattr(
        capacity_roles,
        "validate_role_receipt",
        lambda value, plan: SimpleNamespace(
            receipt_id=value["receipt_id"],
        ),
    )
    monkeypatch.setattr(
        capacity_roles,
        "validate_substantive_role_evidence",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        capacity_roles,
        "validate_oracle_authority",
        lambda *args, **kwargs: SimpleNamespace(scm_ref="b" * 40),
    )

    def reject_stale_policy(*args, **kwargs):
        raise CapacityValidationError(
            "reference policy does not bind the selected release"
        )

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_reference_policy",
        reject_stale_policy,
    )
    monkeypatch.setattr(
        capacity_outcomes,
        "validate_capacity_result",
        lambda *args, **kwargs: pytest.fail(
            "stale reference policy reached capacity-result validation"
        ),
    )

    with pytest.raises(
        CapacityValidationError,
        match="does not bind the selected release",
    ):
        _validated_capacity_result_context(
            manifest,
            tmp_path,
            evaluation_policy=object(),
            expected_scm_ref="b" * 40,
        )


def test_reference_result_context_rejects_missing_host_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "result.json").write_text(
        json.dumps({"execution_boundary": "real-reference"}),
        encoding="utf-8",
    )
    (private / "observer-receipt.json").write_text(
        json.dumps(
            {
                "receipt_id": "observer-receipt",
                "plan_id": "observer-plan",
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(
            capacity_result_context_value(
                reference_policy="private/reference-policy.json",
                observer_plan="private/observer-plan.json",
                actor_set=None,
                concurrency_policy=None,
                role_plans=["private/host-plan.json"],
                role_receipts=["private/observer-receipt.json"],
                frozen_actions=[],
                payloads=[],
                action_results=[],
            )
        ),
        encoding="utf-8",
    )
    observer = SimpleNamespace(
        plan_id="observer-plan",
        role="observer",
    )
    host = SimpleNamespace(
        plan_id="host-plan",
        role="host-operator",
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plan",
        lambda *args, **kwargs: observer,
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plans",
        lambda *args, **kwargs: (host,),
    )
    monkeypatch.setattr(
        capacity_roles,
        "validate_role_receipt",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        capacity_outcomes,
        "validate_capacity_result",
        lambda *args, **kwargs: pytest.fail(
            "missing host evidence reached result validation"
        ),
    )

    with pytest.raises(
        CapacityValidationError,
        match="receipts must cover the observer and host plans",
    ):
        _validated_capacity_result_context(
            manifest,
            tmp_path,
            evaluation_policy=object(),
            expected_scm_ref="b" * 40,
        )


def test_reference_result_context_rejects_stale_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "result.json").write_text(
        json.dumps({"execution_boundary": "real-reference"}),
        encoding="utf-8",
    )
    (private / "observer-receipt.json").write_text(
        json.dumps(
            {
                "receipt_id": "observer-receipt",
                "plan_id": "observer-plan",
            }
        ),
        encoding="utf-8",
    )
    (private / "host-receipt.json").write_text(
        json.dumps(
            {
                "receipt_id": "host-receipt",
                "plan_id": "host-plan",
            }
        ),
        encoding="utf-8",
    )
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(
            capacity_result_context_value(
                reference_policy="private/reference-policy.json",
                observer_plan="private/observer-plan.json",
                actor_set=None,
                concurrency_policy=None,
                role_plans=["private/host-plan.json"],
                role_receipts=[
                    "private/observer-receipt.json",
                    "private/host-receipt.json",
                ],
                frozen_actions=[],
                payloads=[],
                action_results=[],
            )
        ),
        encoding="utf-8",
    )
    observer = SimpleNamespace(
        plan_id="observer-plan",
        role="observer",
    )
    host = SimpleNamespace(
        plan_id="host-plan",
        role="host-operator",
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plan",
        lambda *args, **kwargs: observer,
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plans",
        lambda *args, **kwargs: (host,),
    )

    def reject_stale_receipt(value, plan):
        if plan is host:
            raise CapacityValidationError(
                "role receipt does not bind the exact validated role plan"
            )
        return object()

    monkeypatch.setattr(
        capacity_roles,
        "validate_role_receipt",
        reject_stale_receipt,
    )
    monkeypatch.setattr(
        capacity_outcomes,
        "validate_capacity_result",
        lambda *args, **kwargs: pytest.fail("stale receipt reached result validation"),
    )

    with pytest.raises(
        CapacityValidationError,
        match="does not bind the exact validated role plan",
    ):
        _validated_capacity_result_context(
            manifest,
            tmp_path,
            evaluation_policy=object(),
            expected_scm_ref="b" * 40,
        )


def test_reference_result_context_rejects_controller_authored_market_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private = tmp_path / "private"
    private.mkdir()
    (private / "result.json").write_text(
        json.dumps({"execution_boundary": "real-reference"}),
        encoding="utf-8",
    )
    manifest = tmp_path / "context.json"
    manifest.write_text(
        json.dumps(
            capacity_result_context_value(
                reference_policy="private/reference-policy.json",
                observer_plan="private/observer-plan.json",
                actor_set=None,
                concurrency_policy=None,
                role_plans=["private/host-plan.json"],
                role_receipts=[
                    "private/observer-receipt.json",
                    "private/host-receipt.json",
                ],
                frozen_actions=["private/controller-action.json"],
                payloads=[],
                action_results=[],
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plan",
        lambda *args, **kwargs: pytest.fail(
            "controller-authored evidence passed the reference context fence"
        ),
    )

    with pytest.raises(
        CapacityValidationError,
        match="without actor-set or market-action paths",
    ):
        _validated_capacity_result_context(
            manifest,
            tmp_path,
            evaluation_policy=object(),
            expected_scm_ref="b" * 40,
        )


def test_evaluation_policy_runner_emits_path_free_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hidden = tmp_path / "private" / "evaluation-policy.json"
    policy = SimpleNamespace(
        policy_id="evaluation-policy-1",
        profile_registry_sha256="d" * 64,
        scm_ref="b" * 40,
        canonical_sha256="e" * 64,
    )
    call: dict[str, object] = {}

    def fake(path, root, *, expected_scm_ref):
        call.update(
            {
                "path": path,
                "root": root,
                "expected_scm_ref": expected_scm_ref,
            }
        )
        return policy

    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        fake,
    )

    code = DiscoveryRunner(repo_root()).capacity_evaluation_policy(
        hidden,
        operation="sha256",
        expected_scm_ref="b" * 40,
    )

    assert code == 0
    assert call["expected_scm_ref"] == "b" * 40
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "artifact_kind": "evaluation-policy",
        "evaluation_policy_id": "evaluation-policy-1",
        "operation": "sha256",
        "profile_registry_sha256": "d" * 64,
        "scm_ref": "b" * 40,
        "sha256": "e" * 64,
        "status": "valid",
    }
    assert str(hidden) not in json.dumps(output)


def test_reference_policy_runner_reconstructs_authorities_in_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hidden = tmp_path / "private" / "reference-policy.json"
    hidden.parent.mkdir()
    hidden.write_text("{}\n", encoding="utf-8")
    campaign_policy = object()
    observer = SimpleNamespace(
        plan_id="observer-plan",
        role="observer",
    )
    host = SimpleNamespace(
        plan_id="host-plan",
        role="host-operator",
    )
    reference_policy = SimpleNamespace(
        canonical_sha256="e" * 64,
        policy_id="reference-policy-b1",
        profile_stage_id="b1-reference",
        release_id="release-b1",
        scm_ref="b" * 40,
    )
    events: list[str] = []
    evaluation_call: dict[str, object] = {}

    def fake_evaluation(path, root, *, expected_scm_ref):
        events.append("evaluation-policy")
        evaluation_call.update(
            {
                "path": path,
                "root": root,
                "expected_scm_ref": expected_scm_ref,
            }
        )
        return campaign_policy

    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        fake_evaluation,
    )
    plans = {
        tmp_path / "observer-plan.json": observer,
        tmp_path / "host-plan.json": host,
    }
    plan_calls: list[tuple[Path, str]] = []

    def fake_plan(path, root, *, expected_scm_ref):
        events.append(path.stem)
        plan_calls.append((path, expected_scm_ref))
        return plans[path]

    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plan",
        fake_plan,
    )
    reference_call: dict[str, object] = {}

    def fake_reference(value, root, **kwargs):
        events.append("reference-policy")
        reference_call.update({"value": value, "root": root, **kwargs})
        return reference_policy

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_reference_policy",
        fake_reference,
    )

    code = DiscoveryRunner(repo_root()).capacity_reference_policy(
        hidden,
        evaluation_policy=tmp_path / "evaluation-policy.json",
        observer_plan=tmp_path / "observer-plan.json",
        host_plan=tmp_path / "host-plan.json",
        operation="sha256",
        expected_scm_ref="b" * 40,
    )

    assert code == 0
    assert events == [
        "evaluation-policy",
        "observer-plan",
        "host-plan",
        "reference-policy",
    ]
    assert evaluation_call == {
        "path": tmp_path / "evaluation-policy.json",
        "root": repo_root(),
        "expected_scm_ref": "b" * 40,
    }
    assert plan_calls == [
        (tmp_path / "observer-plan.json", "b" * 40),
        (tmp_path / "host-plan.json", "b" * 40),
    ]
    assert reference_call == {
        "value": {},
        "root": repo_root(),
        "evaluation_policy": campaign_policy,
        "observer_plan": observer,
        "host_plan": host,
        "expected_scm_ref": "b" * 40,
    }
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "artifact_kind": "reference-policy",
        "operation": "sha256",
        "profile_stage_id": "b1-reference",
        "reference_policy_id": "reference-policy-b1",
        "release_id": "release-b1",
        "scm_ref": "b" * 40,
        "sha256": "e" * 64,
        "status": "valid",
    }
    assert str(hidden) not in json.dumps(output)


def test_reference_policy_runner_rejects_wrong_role_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hidden = tmp_path / "private" / "reference-policy.json"
    hidden.parent.mkdir()
    hidden.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        lambda *args, **kwargs: object(),
    )
    observer = SimpleNamespace(
        plan_id="observer-plan",
        role="observer",
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plan",
        lambda *args, **kwargs: observer,
    )
    validation_call: dict[str, object] = {}

    def reject_wrong_roles(value, root, **kwargs):
        validation_call.update({"value": value, "root": root, **kwargs})
        raise CapacityValidationError(
            "reference policy requires exactly one observer and one host-operator plan"
        )

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_reference_policy",
        reject_wrong_roles,
    )

    code = DiscoveryRunner(repo_root()).capacity_reference_policy(
        hidden,
        evaluation_policy=tmp_path / "evaluation-policy.json",
        observer_plan=tmp_path / "observer-plan.json",
        host_plan=tmp_path / "wrong-role-plan.json",
        operation="validate",
        expected_scm_ref="b" * 40,
    )

    assert code == 1
    assert validation_call["observer_plan"] is observer
    assert validation_call["host_plan"] is observer
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "reference-policy"
    assert output["status"] == "invalid"
    assert "one host-operator plan" in output["error"]
    assert "sha256" not in output
    assert str(hidden) not in json.dumps(output)


def test_result_runner_reconstructs_exact_progression_context_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = object()
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        lambda *args, **kwargs: policy,
    )
    buyer_paths = (
        tmp_path / "b1.json",
        tmp_path / "b2.json",
    )
    buyer_results = tuple(SimpleNamespace(result_id=path.stem) for path in buyer_paths)
    frontier = SimpleNamespace(
        canonical_sha256="f" * 64,
        frontier_receipt_id="buyer-frontier-1",
    )
    reuse_a = SimpleNamespace(canonical_sha256="a" * 64)
    reuse_b = SimpleNamespace(canonical_sha256="b" * 64)
    prior_seller_1 = SimpleNamespace(result_id="seller-1")
    prior_seller_2 = SimpleNamespace(result_id="seller-2")
    current = SimpleNamespace(
        actor_trigger="agent-triggered",
        canonical_sha256="c" * 64,
        execution_boundary="real-measured",
        profile_stage_id="b4-s4-g1-measured",
        result_id="seller-4-result",
        scenario_id="b4-s4-g1",
        scm_ref="d" * 40,
    )
    result_by_path = {
        buyer_paths[0]: buyer_results[0],
        buyer_paths[1]: buyer_results[1],
        tmp_path / "reuse-a.json": reuse_a,
        tmp_path / "reuse-b.json": reuse_b,
        tmp_path / "seller-1.json": prior_seller_1,
        tmp_path / "seller-2.json": prior_seller_2,
        tmp_path / "seller-current.json": current,
    }
    calls: list[dict[str, object]] = []
    events: list[str] = []

    def fake_context(
        path,
        root,
        *,
        evaluation_policy,
        expected_scm_ref,
        predecessor=None,
        buyer_frontier=None,
        reuse_baseline=None,
        prior_seller_results=(),
    ):
        events.append(path.name)
        calls.append(
            {
                "path": path,
                "predecessor": predecessor,
                "buyer_frontier": buyer_frontier,
                "reuse_baseline": reuse_baseline,
                "prior_seller_results": prior_seller_results,
                "expected_scm_ref": expected_scm_ref,
            }
        )
        return _ValidatedCapacityResultContext(
            result=result_by_path[path],
            evaluation_policy=evaluation_policy,
            oracle_authority=object(),
            actor_set=None,
            role_evidence=(),
        )

    monkeypatch.setattr(
        "issue_discovery.runner._validated_capacity_result_context",
        fake_context,
    )
    frontier_path = tmp_path / "frontier.json"
    frontier_path.write_text("{}\n", encoding="utf-8")
    frontier_call: dict[str, object] = {}

    def fake_frontier(value, root, **kwargs):
        events.append("frontier")
        frontier_call.update({"value": value, "root": root, **kwargs})
        return frontier

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_buyer_frontier_receipt",
        fake_frontier,
    )

    code = DiscoveryRunner(repo_root()).capacity_result(
        tmp_path / "seller-current.json",
        evaluation_policy=tmp_path / "evaluation-policy.json",
        predecessor_context=tmp_path / "reuse-a.json",
        reuse_baseline_context=tmp_path / "reuse-b.json",
        buyer_frontier=frontier_path,
        buyer_result_contexts=buyer_paths,
        prior_seller_contexts=(
            tmp_path / "seller-1.json",
            tmp_path / "seller-2.json",
        ),
        operation="validate",
        expected_scm_ref="d" * 40,
    )

    assert code == 0
    assert frontier_call["results"] == buyer_results
    assert events == [
        "b1.json",
        "b2.json",
        "frontier",
        "reuse-a.json",
        "reuse-b.json",
        "seller-1.json",
        "seller-2.json",
        "seller-current.json",
    ]
    assert [call["path"] for call in calls] == [
        buyer_paths[0],
        buyer_paths[1],
        tmp_path / "reuse-a.json",
        tmp_path / "reuse-b.json",
        tmp_path / "seller-1.json",
        tmp_path / "seller-2.json",
        tmp_path / "seller-current.json",
    ]
    assert calls[2]["buyer_frontier"] is frontier
    assert calls[3]["predecessor"] is reuse_a
    assert calls[4]["reuse_baseline"] is reuse_b
    assert calls[4]["prior_seller_results"] == ()
    assert calls[5]["reuse_baseline"] is reuse_b
    assert calls[5]["prior_seller_results"] == (prior_seller_1,)
    assert calls[6]["predecessor"] is None
    assert calls[6]["buyer_frontier"] is frontier
    assert calls[6]["reuse_baseline"] is reuse_b
    assert calls[6]["prior_seller_results"] == (
        prior_seller_1,
        prior_seller_2,
    )
    assert all(call["expected_scm_ref"] == "d" * 40 for call in calls)
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "capacity-result"
    assert output["sha256"] == current.canonical_sha256


def test_result_runner_allows_qualification_predecessor_without_frontier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = object()
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        lambda *args, **kwargs: policy,
    )
    reuse_a = SimpleNamespace(canonical_sha256="a" * 64)
    reuse_b = SimpleNamespace(
        actor_trigger="agent-triggered",
        canonical_sha256="b" * 64,
        execution_boundary="real-qualified",
        profile_stage_id="serialized-reuse-qualification-b",
        result_id="reuse-b-result",
        scenario_id="serialized-reuse-qualification",
        scm_ref="d" * 40,
    )
    result_by_path = {
        tmp_path / "reuse-a.json": reuse_a,
        tmp_path / "reuse-b.json": reuse_b,
    }
    calls: list[dict[str, object]] = []

    def fake_context(
        path,
        root,
        *,
        evaluation_policy,
        expected_scm_ref,
        predecessor=None,
        buyer_frontier=None,
        reuse_baseline=None,
        prior_seller_results=(),
    ):
        calls.append(
            {
                "path": path,
                "predecessor": predecessor,
                "buyer_frontier": buyer_frontier,
                "reuse_baseline": reuse_baseline,
                "prior_seller_results": prior_seller_results,
            }
        )
        return _ValidatedCapacityResultContext(
            result=result_by_path[path],
            evaluation_policy=evaluation_policy,
            oracle_authority=object(),
            actor_set=None,
            role_evidence=(),
        )

    monkeypatch.setattr(
        "issue_discovery.runner._validated_capacity_result_context",
        fake_context,
    )
    monkeypatch.setattr(
        capacity_outcomes,
        "validate_buyer_frontier_receipt",
        lambda *args, **kwargs: pytest.fail(
            "qualification predecessor unexpectedly required a frontier"
        ),
    )

    code = DiscoveryRunner(repo_root()).capacity_result(
        tmp_path / "reuse-b.json",
        evaluation_policy=tmp_path / "evaluation-policy.json",
        predecessor_context=tmp_path / "reuse-a.json",
        operation="validate",
        expected_scm_ref="d" * 40,
    )

    assert code == 0
    assert [call["path"] for call in calls] == [
        tmp_path / "reuse-a.json",
        tmp_path / "reuse-b.json",
    ]
    assert calls[0]["predecessor"] is None
    assert calls[0]["buyer_frontier"] is None
    assert calls[1]["predecessor"] is reuse_a
    assert calls[1]["buyer_frontier"] is None
    assert calls[1]["reuse_baseline"] is None
    assert calls[1]["prior_seller_results"] == ()
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "capacity-result"
    assert output["sha256"] == reuse_b.canonical_sha256


def test_result_runner_fails_closed_when_progression_lacks_frontier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        lambda *args, **kwargs: object(),
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_capacity_result_context",
        lambda *args, **kwargs: pytest.fail(
            "unfenced progression reached result reconstruction"
        ),
    )

    code = DiscoveryRunner(repo_root()).capacity_result(
        tmp_path / "seller-current.json",
        evaluation_policy=tmp_path / "evaluation-policy.json",
        reuse_baseline_context=tmp_path / "reuse-b.json",
        operation="validate",
        expected_scm_ref="d" * 40,
    )

    assert code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "capacity-result"
    assert output["status"] == "invalid"
    assert "require a buyer-frontier" in output["error"]


def test_measured_serialized_reuse_runner_uses_validated_b_chain_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = object()
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        lambda *args, **kwargs: policy,
    )
    buyer_paths = (
        tmp_path / "b1.json",
        tmp_path / "b2.json",
    )
    buyer_results = tuple(SimpleNamespace(result_id=path.stem) for path in buyer_paths)
    frontier = object()
    reuse_a = SimpleNamespace(
        canonical_sha256="a" * 64,
        result_id="reuse-a-result",
        scm_ref="c" * 40,
    )
    reuse_b = SimpleNamespace(
        canonical_sha256="b" * 64,
        result_id="reuse-b-result",
        scm_ref="c" * 40,
    )
    result_by_path = {
        buyer_paths[0]: buyer_results[0],
        buyer_paths[1]: buyer_results[1],
        tmp_path / "reuse-a.json": reuse_a,
        tmp_path / "reuse-b.json": reuse_b,
    }
    context_calls: list[dict[str, object]] = []
    events: list[str] = []

    def fake_context(
        path,
        root,
        *,
        evaluation_policy,
        expected_scm_ref,
        predecessor=None,
        buyer_frontier=None,
        reuse_baseline=None,
        prior_seller_results=(),
    ):
        events.append(path.name)
        context_calls.append(
            {
                "path": path,
                "predecessor": predecessor,
                "buyer_frontier": buyer_frontier,
            }
        )
        return _ValidatedCapacityResultContext(
            result=result_by_path[path],
            evaluation_policy=evaluation_policy,
            oracle_authority=object(),
            actor_set=None,
            role_evidence=(),
        )

    monkeypatch.setattr(
        "issue_discovery.runner._validated_capacity_result_context",
        fake_context,
    )
    frontier_path = tmp_path / "frontier.json"
    frontier_path.write_text("{}\n", encoding="utf-8")
    frontier_call: dict[str, object] = {}

    def fake_frontier(value, root, **kwargs):
        events.append("frontier")
        frontier_call.update({"value": value, "root": root, **kwargs})
        return frontier

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_buyer_frontier_receipt",
        fake_frontier,
    )
    pair_call: dict[str, object] = {}

    def fake_reuse(selected_a, selected_b):
        pair_call.update({"reuse_a": selected_a, "reuse_b": selected_b})

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_serialized_reuse",
        fake_reuse,
    )

    code = DiscoveryRunner(repo_root()).capacity_serialized_reuse(
        tmp_path / "reuse-a.json",
        tmp_path / "reuse-b.json",
        evaluation_policy=tmp_path / "evaluation-policy.json",
        buyer_frontier=frontier_path,
        buyer_result_contexts=buyer_paths,
        operation="sha256",
        expected_scm_ref="c" * 40,
    )

    assert code == 0
    assert frontier_call["results"] == buyer_results
    assert events == [
        "b1.json",
        "b2.json",
        "frontier",
        "reuse-a.json",
        "reuse-b.json",
    ]
    assert [call["path"] for call in context_calls] == [
        buyer_paths[0],
        buyer_paths[1],
        tmp_path / "reuse-a.json",
        tmp_path / "reuse-b.json",
    ]
    assert context_calls[2]["buyer_frontier"] is frontier
    assert context_calls[2]["predecessor"] is None
    assert context_calls[3]["buyer_frontier"] is None
    assert context_calls[3]["predecessor"] is reuse_a
    assert pair_call == {"reuse_a": reuse_a, "reuse_b": reuse_b}
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "serialized-reuse"
    assert output["operation"] == "sha256"
    assert output["sha256"] == reuse_b.canonical_sha256
    assert output["reuse_a_sha256"] == reuse_a.canonical_sha256


def test_serialized_reuse_runner_allows_qualification_without_frontier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = object()
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        lambda *args, **kwargs: policy,
    )
    reuse_a = SimpleNamespace(
        canonical_sha256="a" * 64,
        result_id="reuse-a-result",
        scm_ref="c" * 40,
    )
    reuse_b = SimpleNamespace(
        canonical_sha256="b" * 64,
        result_id="reuse-b-result",
        scm_ref="c" * 40,
    )
    result_by_path = {
        tmp_path / "reuse-a.json": reuse_a,
        tmp_path / "reuse-b.json": reuse_b,
    }
    context_calls: list[dict[str, object]] = []

    def fake_context(
        path,
        root,
        *,
        evaluation_policy,
        expected_scm_ref,
        predecessor=None,
        buyer_frontier=None,
        reuse_baseline=None,
        prior_seller_results=(),
    ):
        context_calls.append(
            {
                "path": path,
                "predecessor": predecessor,
                "buyer_frontier": buyer_frontier,
            }
        )
        return _ValidatedCapacityResultContext(
            result=result_by_path[path],
            evaluation_policy=evaluation_policy,
            oracle_authority=object(),
            actor_set=None,
            role_evidence=(),
        )

    monkeypatch.setattr(
        "issue_discovery.runner._validated_capacity_result_context",
        fake_context,
    )
    monkeypatch.setattr(
        capacity_outcomes,
        "validate_buyer_frontier_receipt",
        lambda *args, **kwargs: pytest.fail(
            "qualification reuse unexpectedly required a frontier"
        ),
    )
    pair_call: dict[str, object] = {}

    def fake_reuse(selected_a, selected_b):
        pair_call.update({"reuse_a": selected_a, "reuse_b": selected_b})

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_serialized_reuse",
        fake_reuse,
    )

    code = DiscoveryRunner(repo_root()).capacity_serialized_reuse(
        tmp_path / "reuse-a.json",
        tmp_path / "reuse-b.json",
        evaluation_policy=tmp_path / "evaluation-policy.json",
        operation="validate",
        expected_scm_ref="c" * 40,
    )

    assert code == 0
    assert [call["path"] for call in context_calls] == [
        tmp_path / "reuse-a.json",
        tmp_path / "reuse-b.json",
    ]
    assert context_calls[0]["buyer_frontier"] is None
    assert context_calls[0]["predecessor"] is None
    assert context_calls[1]["buyer_frontier"] is None
    assert context_calls[1]["predecessor"] is reuse_a
    assert pair_call == {"reuse_a": reuse_a, "reuse_b": reuse_b}
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "serialized-reuse"
    assert output["operation"] == "validate"
    assert output["sha256"] == reuse_b.canonical_sha256


def test_serialized_reuse_runner_fails_closed_before_reuse_on_bad_frontier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = object()
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        lambda *args, **kwargs: policy,
    )
    buyer_paths = (
        tmp_path / "b1.json",
        tmp_path / "b2.json",
    )
    calls: list[Path] = []

    def fake_context(path, root, **kwargs):
        calls.append(path)
        if path not in buyer_paths:
            pytest.fail("invalid buyer frontier authorized reuse")
        return _ValidatedCapacityResultContext(
            result=SimpleNamespace(result_id=path.stem),
            evaluation_policy=kwargs["evaluation_policy"],
            oracle_authority=object(),
            actor_set=None,
            role_evidence=(),
        )

    monkeypatch.setattr(
        "issue_discovery.runner._validated_capacity_result_context",
        fake_context,
    )
    frontier_path = tmp_path / "frontier.json"
    frontier_path.write_text("{}\n", encoding="utf-8")

    def reject_frontier(*args, **kwargs):
        raise CapacityValidationError("buyer frontier is stale")

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_buyer_frontier_receipt",
        reject_frontier,
    )
    monkeypatch.setattr(
        capacity_outcomes,
        "validate_serialized_reuse",
        lambda *args, **kwargs: pytest.fail(
            "invalid buyer frontier reached reuse validation"
        ),
    )

    code = DiscoveryRunner(repo_root()).capacity_serialized_reuse(
        tmp_path / "reuse-a.json",
        tmp_path / "reuse-b.json",
        evaluation_policy=tmp_path / "evaluation-policy.json",
        buyer_frontier=frontier_path,
        buyer_result_contexts=buyer_paths,
        operation="validate",
        expected_scm_ref="c" * 40,
    )

    assert code == 1
    assert calls == list(buyer_paths)
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "serialized-reuse"
    assert output["status"] == "invalid"
    assert "buyer frontier is stale" in output["error"]


def test_buyer_frontier_runner_preserves_result_context_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    policy = object()
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        lambda *args, **kwargs: policy,
    )
    context_paths = tuple(
        tmp_path / name for name in ("b1.json", "b2.json", "b4.json", "b8.json")
    )
    results = {path: SimpleNamespace(result_id=path.stem) for path in context_paths}

    def fake_context(path, root, **kwargs):
        return _ValidatedCapacityResultContext(
            result=results[path],
            evaluation_policy=kwargs["evaluation_policy"],
            oracle_authority=object(),
            actor_set=None,
            role_evidence=(),
        )

    monkeypatch.setattr(
        "issue_discovery.runner._validated_capacity_result_context",
        fake_context,
    )
    frontier_path = tmp_path / "frontier.json"
    frontier_path.write_text("{}\n", encoding="utf-8")
    call: dict[str, object] = {}

    def fake_frontier(value, root, **kwargs):
        call.update({"value": value, "root": root, **kwargs})
        return SimpleNamespace(
            canonical_sha256="f" * 64,
            classification="lower-bound",
            frontier_receipt_id="buyer-frontier-1",
            largest_clean_buyer_count=8,
            scm_ref="c" * 40,
        )

    monkeypatch.setattr(
        capacity_outcomes,
        "validate_buyer_frontier_receipt",
        fake_frontier,
    )

    code = DiscoveryRunner(repo_root()).capacity_buyer_frontier(
        frontier_path,
        evaluation_policy=tmp_path / "evaluation-policy.json",
        result_contexts=context_paths,
        operation="validate",
        expected_scm_ref="c" * 40,
    )

    assert code == 0
    assert call["results"] == tuple(results[path] for path in context_paths)
    assert call["evaluation_policy"] is policy
    assert call["expected_scm_ref"] == "c" * 40
    output = json.loads(capsys.readouterr().out)
    assert output["frontier_receipt_id"] == "buyer-frontier-1"
    assert output["sha256"] == "f" * 64


def test_result_runner_rejects_wrong_selected_ref_before_outer_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hidden = tmp_path / "private" / "result-context.json"
    expected_ref = "d" * 40
    call: dict[str, object] = {}

    def fake_policy(path, root, *, expected_scm_ref):
        call["expected_scm_ref"] = expected_scm_ref
        raise CapacityValidationError(
            "evaluation-policy SCM ref does not match selected campaign ref"
        )

    monkeypatch.setattr(
        "issue_discovery.runner._validated_evaluation_policy",
        fake_policy,
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_capacity_result_context",
        lambda *args, **kwargs: pytest.fail(
            "wrong-ref policy reached result validation"
        ),
    )

    code = DiscoveryRunner(repo_root()).capacity_result(
        hidden,
        evaluation_policy=tmp_path / "private" / "evaluation-policy.json",
        predecessor_context=None,
        operation="validate",
        expected_scm_ref=expected_ref,
    )

    assert code == 1
    assert call["expected_scm_ref"] == expected_ref
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "capacity-result"
    assert output["status"] == "invalid"
    assert "does not match" in output["error"]
    assert str(hidden) not in output["error"]


def test_role_plan_runner_emits_canonical_path_free_success_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hidden_path = tmp_path / "private" / "plan.json"
    plan = SimpleNamespace(
        actor_slot="buyer-1",
        canonical_sha256="a" * 64,
        plan_id="buyer-plan-1",
        role="buyer",
        scm_ref="b" * 40,
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_role_plan",
        lambda *args, **kwargs: plan,
    )

    code = DiscoveryRunner(repo_root()).capacity_role_plan(
        hidden_path,
        operation="validate",
        expected_scm_ref="b" * 40,
    )

    assert code == 0
    output = capsys.readouterr().out.strip()
    assert output == json.dumps(
        {
            "actor_slot": "buyer-1",
            "artifact_kind": "role-plan",
            "operation": "validate",
            "plan_id": "buyer-plan-1",
            "role": "buyer",
            "scm_ref": "b" * 40,
            "sha256": "a" * 64,
            "status": "valid",
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    assert str(hidden_path) not in output


def test_role_plan_runner_rejects_duplicate_key_json_without_leaking_path(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    hidden_path = tmp_path / "private-plan.json"
    hidden_path.write_text('{"schema_version":2,"schema_version":2}\n')

    code = DiscoveryRunner(repo_root()).capacity_role_plan(
        hidden_path,
        operation="validate",
    )

    assert code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "role-plan"
    assert output["status"] == "invalid"
    assert "duplicate object key" in output["error"]
    assert str(hidden_path) not in output["error"]


def test_actor_set_runner_passes_validated_bundle_to_aggregate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    actor_set_path = tmp_path / "actor-set.json"
    actor_set_path.write_text("{}\n")
    evidence = (object(),)
    policy = object()
    bundle = _ValidatedEvidenceBundle(
        evidence=evidence,
        concurrency_policy=policy,
        oracle_authorities=(),
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_evidence_bundle",
        lambda **kwargs: bundle,
    )
    call: dict[str, object] = {}

    def fake_validate(value, selected_policy, selected_evidence):
        call.update(
            {
                "value": value,
                "policy": selected_policy,
                "evidence": selected_evidence,
            }
        )
        return SimpleNamespace(
            actor_set_id="actors-1",
            canonical_sha256="c" * 64,
            profile_stage_id="b2-s1-g1-qualification",
            scenario_id="b2-s1-g1",
        )

    monkeypatch.setattr(
        capacity_roles,
        "validate_substantive_actor_set",
        fake_validate,
    )

    code = DiscoveryRunner(repo_root()).capacity_actor_set(
        actor_set_path,
        concurrency_policy=tmp_path / "policy.json",
        role_plans=(tmp_path / "plan.json",),
        role_receipts=(tmp_path / "receipt.json",),
        frozen_actions=(tmp_path / "action.json",),
        payloads=(tmp_path / "payload.json",),
        oracle_authorities=(tmp_path / "oracle.json",),
        action_results=(tmp_path / "result.json",),
        operation="sha256",
    )

    assert code == 0
    assert call == {"value": {}, "policy": policy, "evidence": evidence}
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "actor_set_id": "actors-1",
        "artifact_kind": "actor-set",
        "operation": "sha256",
        "profile_stage_id": "b2-s1-g1-qualification",
        "scenario_id": "b2-s1-g1",
        "sha256": "c" * 64,
        "status": "valid",
    }


def test_action_capture_cli_forwards_runtime_only_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repo_root()
    call: dict[str, object] = {}

    def fake(self, **kwargs):
        call.update(kwargs)
        return 0

    monkeypatch.setattr(DiscoveryRunner, "capacity_action_capture", fake)
    assert (
        main(
            [
                "--repo-root",
                str(root),
                "capacity",
                "action-capture",
                "--expected-action-kind",
                "buyer-request",
                "action.json",
                "--role-plan",
                "plan.json",
                "--payload",
                "payload.json",
                "--oracle-authority",
                "oracle.json",
                "--runtime-binding",
                str(tmp_path / "binding.json"),
                "--concrete-payload-binding",
                str(tmp_path / "concrete.json"),
                "--actor-invocation-capability",
                str(tmp_path / "capability.json"),
                "--current-frozen-action",
                str(tmp_path / "current-action.json"),
                "--current-role-plan",
                str(tmp_path / "current-plan.json"),
                "--current-payload",
                str(tmp_path / "current-payload.json"),
                "--current-oracle-authority",
                str(tmp_path / "current-oracle.json"),
                "--actor-alive-at-invocation",
                "--claim-ledger",
                str(tmp_path / "claims"),
                "--result-output",
                str(tmp_path / "result.json"),
            ]
        )
        == 0
    )
    assert call["expected_action_kind"] == "buyer-request"
    assert call["current_runtime_binding"] == tmp_path / "binding.json"
    assert call["current_concrete_payload_binding"] == (tmp_path / "concrete.json")
    assert call["current_actor_invocation_capability"] == (tmp_path / "capability.json")
    assert call["current_action"] == tmp_path / "current-action.json"
    assert call["current_plan"] == tmp_path / "current-plan.json"
    assert call["current_payload"] == tmp_path / "current-payload.json"
    assert call["current_oracle_authority"] == tmp_path / "current-oracle.json"
    assert call["actor_alive_at_invocation"] is True
    assert call["claim_ledger"] == tmp_path / "claims"
    assert call["result_output"] == tmp_path / "result.json"
    assert call["frozen_action"] == root / "action.json"


def test_one_shot_wrapper_kind_cannot_be_overridden(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(
            [
                "capacity",
                "action-capture",
                "--expected-action-kind",
                "seller-service-start",
                "action.json",
                "--role-plan",
                "plan.json",
                "--payload",
                "payload.json",
                "--oracle-authority",
                "oracle.json",
                "--runtime-binding",
                "runtime.json",
                "--concrete-payload-binding",
                "concrete.json",
                "--actor-invocation-capability",
                "capability.json",
                "--actor-alive-at-invocation",
                "--claim-ledger",
                "claims",
                "--result-output",
                "result.json",
                "--expected-action-kind",
                "buyer-request",
            ]
        )
    assert exit_info.value.code == 2
    assert "may only be supplied once" in capsys.readouterr().err

    wrapper_expectations = {
        "emit-buyer-request.sh": "buyer-request",
        "publish-listing.sh": "seller-listing-publication",
        "start-seller-service.sh": "seller-service-start",
    }
    wrapper_root = repo_root() / "tools" / "issue-discovery" / "wrappers"
    for wrapper_name, action_kind in wrapper_expectations.items():
        content = (wrapper_root / wrapper_name).read_text(encoding="utf-8")
        assert content.index('"$@"') < content.index(
            f"--expected-action-kind {action_kind}"
        )


def test_action_capture_runner_is_mock_only_and_calls_one_shot_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_binding_path = tmp_path / "binding.json"
    runtime_binding = {
        "method": "opaque-random-v1",
        "domain": "scm.capacity.runtime-binding.v1",
        "value": "d" * 64,
    }
    runtime_binding_path.write_text(json.dumps(runtime_binding))
    concrete_binding_path = tmp_path / "concrete.json"
    concrete_binding_path.write_text(
        json.dumps(
            {
                **runtime_binding,
                "domain": "scm.capacity.concrete-payload.v1",
            }
        )
    )
    capability_path = tmp_path / "capability.json"
    capability_path.write_text(
        json.dumps(
            {
                **runtime_binding,
                "domain": "scm.capacity.actor-invocation.v1",
            }
        )
    )
    action = SimpleNamespace(
        action_id="buyer-action-1",
        action_kind="buyer-request",
        actor_slot="buyer-1",
    )
    plan = SimpleNamespace(
        profile_stage=SimpleNamespace(
            stage={"execution_boundary": "mock"},
        )
    )
    context = _ValidatedActionContext(
        plan=plan,
        oracle_authority=object(),
        concurrency_policy=None,
        action=action,
        payload_bytes=b"{}\n",
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_action_context",
        lambda **kwargs: context,
    )
    call: dict[str, object] = {}

    def fake_capture(selected_action, selected_plan, **kwargs):
        call.update(
            {
                "action": selected_action,
                "plan": selected_plan,
                **kwargs,
            }
        )
        return SimpleNamespace(
            result=SimpleNamespace(
                action_id="buyer-action-1",
                action_result_id="action-result-1",
                actor_slot="buyer-1",
                canonical_sha256="e" * 64,
                result={"failure_code": None},
                result_kind="emitted",
            )
        )

    monkeypatch.setattr(capacity_roles, "action_capture", fake_capture)

    runner = DiscoveryRunner(repo_root())
    code = runner.capacity_action_capture(
        frozen_action=tmp_path / "action.json",
        role_plan=tmp_path / "plan.json",
        payload=tmp_path / "payload.json",
        oracle_authority=tmp_path / "oracle.json",
        observer_plan=None,
        concurrency_policy=None,
        policy_role_plans=(),
        expected_scm_ref=None,
        expected_action_kind="buyer-request",
        current_runtime_binding=runtime_binding_path,
        current_concrete_payload_binding=concrete_binding_path,
        current_actor_invocation_capability=capability_path,
        actor_alive_at_invocation=True,
        claim_ledger=tmp_path / "claims",
        result_output=tmp_path / "result.json",
    )

    assert code == 0
    assert call["action"] is action
    assert call["plan"] is plan
    assert call["current_runtime_binding"] == runtime_binding
    assert call["actor_alive_at_invocation"] is True
    assert call["claim_ledger"] == tmp_path / "claims"
    assert call["result_output"] == tmp_path / "result.json"
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "action-result"
    assert output["operation"] == "capture"
    assert output["sha256"] == "e" * 64


def test_action_capture_runner_returns_nonzero_for_typed_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_binding_path = tmp_path / "binding.json"
    runtime_binding_path.write_text("{}")
    concrete_binding_path = tmp_path / "concrete.json"
    concrete_binding_path.write_text("{}")
    capability_path = tmp_path / "capability.json"
    capability_path.write_text("{}")
    context = _ValidatedActionContext(
        plan=SimpleNamespace(
            profile_stage=SimpleNamespace(
                stage={"execution_boundary": "mock"},
            )
        ),
        oracle_authority=object(),
        concurrency_policy=None,
        action=SimpleNamespace(
            action_id="buyer-action-1",
            action_kind="buyer-request",
        ),
        payload_bytes=b"{}\n",
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_action_context",
        lambda **kwargs: context,
    )
    monkeypatch.setattr(
        capacity_roles,
        "action_capture",
        lambda *args, **kwargs: SimpleNamespace(
            result=SimpleNamespace(
                action_id="buyer-action-1",
                action_result_id="action-result-rejected",
                actor_slot="buyer-1",
                canonical_sha256="f" * 64,
                result={"failure_code": "duplicate-release"},
                result_kind="rejected-before-emission",
            )
        ),
    )

    code = DiscoveryRunner(repo_root()).capacity_action_capture(
        frozen_action=tmp_path / "action.json",
        role_plan=tmp_path / "plan.json",
        payload=tmp_path / "payload.json",
        oracle_authority=tmp_path / "oracle.json",
        observer_plan=None,
        concurrency_policy=None,
        policy_role_plans=(),
        expected_scm_ref=None,
        expected_action_kind="buyer-request",
        current_runtime_binding=runtime_binding_path,
        current_concrete_payload_binding=concrete_binding_path,
        current_actor_invocation_capability=capability_path,
        actor_alive_at_invocation=True,
        claim_ledger=tmp_path / "claims",
        result_output=tmp_path / "result.json",
    )

    assert code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["failure_code"] == "duplicate-release"
    assert output["result_kind"] == "rejected-before-emission"
    assert output["sha256"] == "f" * 64


def test_action_capture_runner_rejects_real_stage_before_adapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    runtime_binding_path = tmp_path / "binding.json"
    runtime_binding_path.write_text("{}")
    concrete_binding_path = tmp_path / "concrete.json"
    concrete_binding_path.write_text("{}")
    capability_path = tmp_path / "capability.json"
    capability_path.write_text("{}")
    context = _ValidatedActionContext(
        plan=SimpleNamespace(
            profile_stage=SimpleNamespace(
                stage={"execution_boundary": "real-qualification"},
            )
        ),
        oracle_authority=object(),
        concurrency_policy=None,
        action=SimpleNamespace(
            action_id="buyer-action-1",
            action_kind="buyer-request",
        ),
        payload_bytes=b"{}\n",
    )
    monkeypatch.setattr(
        "issue_discovery.runner._validated_action_context",
        lambda **kwargs: context,
    )
    monkeypatch.setattr(
        capacity_roles,
        "action_capture",
        lambda *args, **kwargs: pytest.fail("real action reached public capture"),
    )

    code = DiscoveryRunner(repo_root()).capacity_action_capture(
        frozen_action=tmp_path / "action.json",
        role_plan=tmp_path / "plan.json",
        payload=tmp_path / "payload.json",
        oracle_authority=tmp_path / "oracle.json",
        observer_plan=None,
        concurrency_policy=None,
        policy_role_plans=(),
        expected_scm_ref=None,
        expected_action_kind="buyer-request",
        current_runtime_binding=runtime_binding_path,
        current_concrete_payload_binding=concrete_binding_path,
        current_actor_invocation_capability=capability_path,
        actor_alive_at_invocation=True,
        claim_ledger=tmp_path / "claims",
        result_output=tmp_path / "result.json",
    )

    assert code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["artifact_kind"] == "action-capture"
    assert "mock" in output["error"]
