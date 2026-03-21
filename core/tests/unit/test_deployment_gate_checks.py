from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/run_deployment_gate_checks.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_deployment_gate_checks", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gate_runner_runs_repo_checks_and_smoke_help_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    commands: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        commands.append((command, cwd))

    monkeypatch.setattr(module, "_run_command", fake_run)

    exit_code = module.main([])

    assert exit_code == 0
    assert commands == [
        (
            [
                "uv",
                "--no-config",
                "run",
                "pytest",
                "tests/unit/test_repo_consistency.py",
                "tests/unit/test_validate_deployment_bundle.py",
                "tests/unit/test_deployment_gate_checks.py",
                "tests/unit/test_alkahest_config.py",
                "-q",
            ],
            module.ROOT / "core",
        ),
        (
            ["uv", "--no-config", "run", "pytest", "tests/unit/test_alkahest.py", "-q"],
            module.ROOT / "service",
        ),
        (
            [
                "uv",
                "--no-config",
                "run",
                "pytest",
                "tests/test_canary_actors.py",
                "tests/test_canary_rollback.py",
                "tests/test_prod_canary_smoke.py",
                "tests/test_config_init.py",
                "tests/test_order_auth.py",
                "-q",
            ],
            module.ROOT / "cli",
        ),
        (
            ["uv", "--no-config", "run", "python", "../scripts/prod_canary_smoke.py", "--help"],
            module.ROOT / "cli",
        ),
    ]


def test_gate_runner_runs_validator_when_env_bundle_is_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    commands: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        commands.append((command, cwd))

    monkeypatch.setattr(module, "_run_command", fake_run)

    agent_env = tmp_path / "agent.env"
    provisioning_env = tmp_path / "provisioning.env"
    registry_env = tmp_path / "registry.env"
    inventory = tmp_path / "hosts"
    for path in (agent_env, provisioning_env, registry_env, inventory):
        path.write_text("KEY=value\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--environment",
            "staging",
            "--agent-env",
            str(agent_env),
            "--provisioning-env",
            str(provisioning_env),
            "--registry-env",
            str(registry_env),
            "--inventory-path",
            str(inventory),
            "--seller-agent-id",
            "eip155:84532:0x1111111111111111111111111111111111111111:101",
            "--skip-smoke-help",
        ]
    )

    assert exit_code == 0
    assert commands[2] == (
        [
            "uv",
            "--no-config",
            "run",
            "pytest",
            "tests/test_canary_actors.py",
            "tests/test_canary_rollback.py",
            "tests/test_prod_canary_smoke.py",
            "tests/test_config_init.py",
            "tests/test_order_auth.py",
            "-q",
        ],
        module.ROOT / "cli",
    )
    assert commands[3] == (
        [
            "python",
            "scripts/validate_deployment_bundle.py",
            "--environment",
            "staging",
            "--agent-env",
            str(agent_env),
            "--provisioning-env",
            str(provisioning_env),
            "--registry-env",
            str(registry_env),
            "--inventory-path",
            str(inventory),
            "--seller-agent-id",
            "eip155:84532:0x1111111111111111111111111111111111111111:101",
        ],
        module.ROOT,
    )


def test_gate_runner_rejects_partial_env_bundle_args() -> None:
    module = _load_script_module()

    with pytest.raises(SystemExit, match="Provide --agent-env, --provisioning-env, and --registry-env together."):
        module.main(["--agent-env", "/tmp/agent.env"])


def test_gate_runner_runs_dual_agent_validator_when_actor_envs_are_supplied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _load_script_module()
    commands: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        commands.append((command, cwd))

    monkeypatch.setattr(module, "_run_command", fake_run)

    seller_env = tmp_path / "seller.env"
    buyer_env = tmp_path / "buyer.env"
    provisioning_env = tmp_path / "provisioning.env"
    registry_env = tmp_path / "registry.env"
    inventory = tmp_path / "hosts"
    for path in (seller_env, buyer_env, provisioning_env, registry_env, inventory):
        path.write_text("KEY=value\n", encoding="utf-8")

    exit_code = module.main(
        [
            "--environment",
            "production",
            "--seller-agent-env",
            str(seller_env),
            "--buyer-agent-env",
            str(buyer_env),
            "--provisioning-env",
            str(provisioning_env),
            "--registry-env",
            str(registry_env),
            "--inventory-path",
            str(inventory),
            "--skip-smoke-help",
        ]
    )

    assert exit_code == 0
    assert commands[3] == (
        [
            "python",
            "scripts/validate_deployment_bundle.py",
            "--environment",
            "production",
            "--seller-agent-env",
            str(seller_env),
            "--buyer-agent-env",
            str(buyer_env),
            "--provisioning-env",
            str(provisioning_env),
            "--registry-env",
            str(registry_env),
            "--inventory-path",
            str(inventory),
        ],
        module.ROOT,
    )


def test_gate_runner_rejects_partial_dual_agent_env_bundle_args() -> None:
    module = _load_script_module()

    with pytest.raises(
        SystemExit,
        match=(
            "Provide either --agent-env with --provisioning-env and --registry-env, "
            "or provide both --seller-agent-env and --buyer-agent-env with the same shared env files."
        ),
    ):
        module.main(["--seller-agent-env", "/tmp/seller.env", "--provisioning-env", "/tmp/provisioning.env"])
