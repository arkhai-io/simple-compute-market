from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from issue_discovery import capacity_roles
from issue_discovery.cli import main
from issue_discovery.runner import (
    DiscoveryRunner,
    _ValidatedActionContext,
    _ValidatedEvidenceBundle,
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


@pytest.mark.parametrize(
    ("command", "arguments", "method_name", "operation"),
    [
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
    ):
        if name in arguments:
            assert str(root / name) in rendered


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
    assert call["current_concrete_payload_binding"] == (
        tmp_path / "concrete.json"
    )
    assert call["current_actor_invocation_capability"] == (
        tmp_path / "capability.json"
    )
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
