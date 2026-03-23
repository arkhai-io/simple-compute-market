from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/run_platform_standup.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_platform_standup", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_deploy_commands_orders_render_preflight_rollout_and_refresh(tmp_path: Path) -> None:
    module = _load_script_module()

    commands = module.build_deploy_commands(
        project="sms-canary-project",
        zone="us-east4-c",
        shared_secrets_dir=tmp_path / "shared",
        local_secrets_dir=tmp_path / "local",
        render_output_dir=tmp_path / "rendered",
        canary_env_path=tmp_path / "prod-canary.env",
        chain_name="ethereum_sepolia",
    )

    assert commands == [
        [
            "python",
            "scripts/materialize_host_envs.py",
            "--shared-secrets-dir",
            str(tmp_path / "shared"),
            "--local-secrets-dir",
            str(tmp_path / "local"),
            "--output-dir",
            str(tmp_path / "rendered"),
        ],
        [
            "python",
            "scripts/check_chain_profile.py",
            "--shared-secrets-dir",
            str(tmp_path / "shared"),
            "--local-secrets-dir",
            str(tmp_path / "local"),
            "--json",
        ],
        [
            "python",
            "scripts/rollout_live_env.py",
            "--project",
            "sms-canary-project",
            "--zone",
            "us-east4-c",
            "--render-output-dir",
            str(tmp_path / "rendered"),
            "--chain-name",
            "ethereum_sepolia",
        ],
        [
            "python",
            "scripts/refresh_canary_agent_ids.py",
            "--project",
            "sms-canary-project",
            "--zone",
            "us-east4-c",
            "--canary-env-path",
            str(tmp_path / "prod-canary.env"),
        ],
    ]


def test_build_verify_command_uses_rendered_bundle_and_expected_chain(tmp_path: Path) -> None:
    module = _load_script_module()

    command = module.build_verify_command(
        environment="isolated-eth-sepolia",
        render_output_dir=tmp_path / "rendered",
        inventory_path=tmp_path / "inventory/hosts",
        expected_chain_name="ethereum_sepolia",
        expected_chain_id=11155111,
    )

    assert command == [
        "python",
        "scripts/run_deployment_gate_checks.py",
        "--environment",
        "isolated-eth-sepolia",
        "--seller-agent-env",
        str(tmp_path / "rendered/seller-agent.env"),
        "--buyer-agent-env",
        str(tmp_path / "rendered/buyer-agent.env"),
        "--provisioning-env",
        str(tmp_path / "rendered/provisioning.env"),
        "--registry-env",
        str(tmp_path / "rendered/registry.env"),
        "--inventory-path",
        str(tmp_path / "inventory/hosts"),
        "--expected-chain-name",
        "ethereum_sepolia",
        "--expected-chain-id",
        "11155111",
        "--skip-smoke-help",
    ]


def test_build_platform_artifact_uses_shared_role_contract() -> None:
    module = _load_script_module()

    artifact = module.build_platform_artifact(
        action="deploy",
        status="succeeded",
        request_url="gcloud://sms-canary-project/us-east4-c",
        auth_url="gcloud://sms-canary-project/us-east4-c",
        render_output_dir="/tmp/sms-rendered",
        details={"seller_agent_id": "seller-id", "buyer_agent_id": "buyer-id"},
    )

    assert artifact["role"] == "platform"
    assert artifact["action"] == "deploy"
    assert artifact["status"] == "succeeded"
    assert artifact["details"]["render_output_dir"] == "/tmp/sms-rendered"
    assert artifact["details"]["seller_agent_id"] == "seller-id"
    assert artifact["details"]["buyer_agent_id"] == "buyer-id"
