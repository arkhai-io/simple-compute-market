from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/run_repeatable_canary.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_repeatable_canary", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(f"{key}={value}\n" for key, value in values.items()),
        encoding="utf-8",
    )


def _render_bundle(output_dir: Path) -> None:
    _write_env(
        output_dir / "seller-agent.env",
        {
            "AGENT_ID": "seller-prod",
            "BASE_URL_OVERRIDE": "http://10.0.0.21:8000",
        },
    )
    _write_env(
        output_dir / "buyer-agent.env",
        {
            "AGENT_ID": "buyer-prod",
            "BASE_URL_OVERRIDE": "http://10.0.0.22:8000",
        },
    )
    _write_env(
        output_dir / "provisioning.env",
        {
            "DEFAULT_VM_HOST": "btc1",
        },
    )
    _write_env(
        output_dir / "registry.env",
        {
            "REGISTRY_URL": "http://10.0.0.11:8080",
        },
    )
    _write_env(
        output_dir / "prod-canary.env",
        {
            "REGISTRY_URL": "http://10.0.0.11:8080",
            "PROVISIONING_SERVICE_URL": "http://10.0.0.12:8081",
            "SELLER_AGENT_URL": "http://10.0.0.21:8000",
            "BUYER_AGENT_URL": "http://10.0.0.22:8000",
            "SELLER_AGENT_ID": "eip155:84532:0x1111111111111111111111111111111111111111:101",
            "BUYER_AGENT_ID": "eip155:84532:0x1111111111111111111111111111111111111111:202",
            "SELLER_PRIVATE_KEY": "0xseller-private-key",
            "BUYER_PRIVATE_KEY": "0xbuyer-private-key",
            "SSH_PRIVATE_KEY_PATH": "/tmp/tenant_ed25519",
        },
    )


def test_repeatable_canary_runner_executes_render_fund_gates_validate_then_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    local_secrets_dir = tmp_path / "local-secrets"
    output_dir = tmp_path / "rendered"
    artifacts_dir = tmp_path / "artifacts"
    commands: list[tuple[list[str], Path]] = []
    logged_commands: list[tuple[list[str], Path, Path, dict[str, str] | None]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> None:
        commands.append((command, cwd))
        if command[:2] == ["python", "scripts/materialize_host_envs.py"]:
            _render_bundle(output_dir)

    def fake_logged_run(
        command: list[str],
        *,
        cwd: Path,
        log_path: Path,
        env: dict[str, str] | None = None,
    ) -> int:
        logged_commands.append((command, cwd, log_path, env))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("[success] canary completed\n", encoding="utf-8")
        return 0

    monkeypatch.setattr(module, "_run_command", fake_run)
    monkeypatch.setattr(module, "_run_logged_command", fake_logged_run)

    exit_code = module.main(
        [
            "--environment",
            "isolated-base-sepolia",
            "--local-secrets-dir",
            str(local_secrets_dir),
            "--output-dir",
            str(output_dir),
            "--artifacts-dir",
            str(artifacts_dir),
            "--inventory-path",
            "compute-provisioning-iac/ansible/inventory/hosts",
            "--apply-funding",
        ]
    )

    assert exit_code == 0
    assert commands == [
        (
            [
                "python",
                "scripts/materialize_host_envs.py",
                "--local-secrets-dir",
                str(local_secrets_dir),
                "--output-dir",
                str(output_dir),
            ],
            module.ROOT,
        ),
        (
            [
                "python",
                "scripts/pre_canary_fund.py",
                "--local-secrets-dir",
                str(local_secrets_dir),
                "--apply",
            ],
            module.ROOT,
        ),
        (
            [
                "python",
                "scripts/run_deployment_gate_checks.py",
                "--environment",
                "isolated-base-sepolia",
                "--seller-agent-env",
                str(output_dir / "seller-agent.env"),
                "--buyer-agent-env",
                str(output_dir / "buyer-agent.env"),
                "--provisioning-env",
                str(output_dir / "provisioning.env"),
                "--registry-env",
                str(output_dir / "registry.env"),
                "--inventory-path",
                "compute-provisioning-iac/ansible/inventory/hosts",
                "--skip-smoke-help",
            ],
            module.ROOT,
        ),
        (
            [
                "python",
                "scripts/validate_deployment_bundle.py",
                "--environment",
                "isolated-base-sepolia",
                "--seller-agent-env",
                str(output_dir / "seller-agent.env"),
                "--buyer-agent-env",
                str(output_dir / "buyer-agent.env"),
                "--provisioning-env",
                str(output_dir / "provisioning.env"),
                "--registry-env",
                str(output_dir / "registry.env"),
                "--inventory-path",
                "compute-provisioning-iac/ansible/inventory/hosts",
                "--seller-agent-url",
                "http://10.0.0.21:8000",
                "--buyer-agent-url",
                "http://10.0.0.22:8000",
                "--seller-agent-id",
                "eip155:84532:0x1111111111111111111111111111111111111111:101",
                "--buyer-agent-id",
                "eip155:84532:0x1111111111111111111111111111111111111111:202",
                "--seller-private-key",
                "0xseller-private-key",
                "--buyer-private-key",
                "0xbuyer-private-key",
                "--ssh-private-key-path",
                "/tmp/tenant_ed25519",
            ],
            module.ROOT,
        ),
    ]
    assert len(logged_commands) == 1
    assert logged_commands[0][0] == [
        "uv",
        "--no-config",
        "run",
        "python",
        "scripts/prod_canary_smoke.py",
    ]
    assert logged_commands[0][1] == module.ROOT
    assert logged_commands[0][2] == artifacts_dir / "prod-canary.log"
    assert logged_commands[0][3] is not None
    assert logged_commands[0][3]["SELLER_AGENT_URL"] == "http://10.0.0.21:8000"


def test_repeatable_canary_runner_attempts_rollback_on_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    local_secrets_dir = tmp_path / "local-secrets"
    output_dir = tmp_path / "rendered"
    artifacts_dir = tmp_path / "artifacts"
    commands: list[tuple[list[str], Path]] = []
    logged_commands: list[tuple[list[str], Path, Path]] = []

    def fake_run(
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
    ) -> None:
        commands.append((command, cwd))
        if command[:2] == ["python", "scripts/materialize_host_envs.py"]:
            _render_bundle(output_dir)

    def fake_logged_run(
        command: list[str],
        *,
        cwd: Path,
        log_path: Path,
        env: dict[str, str] | None = None,
    ) -> int:
        logged_commands.append((command, cwd, log_path))
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("[failed] canary completed\n", encoding="utf-8")
        if command[-1] == "scripts/prod_canary_smoke.py":
            return 1
        return 0

    monkeypatch.setattr(module, "_run_command", fake_run)
    monkeypatch.setattr(module, "_run_logged_command", fake_logged_run)

    exit_code = module.main(
        [
            "--environment",
            "isolated-base-sepolia",
            "--local-secrets-dir",
            str(local_secrets_dir),
            "--output-dir",
            str(output_dir),
            "--artifacts-dir",
            str(artifacts_dir),
            "--skip-deployment-gates",
            "--skip-bundle-validation",
        ]
    )

    assert exit_code == 1
    assert commands[:2] == [
        (
            [
                "python",
                "scripts/materialize_host_envs.py",
                "--local-secrets-dir",
                str(local_secrets_dir),
                "--output-dir",
                str(output_dir),
            ],
            module.ROOT,
        ),
        (
            [
                "python",
                "scripts/pre_canary_fund.py",
                "--local-secrets-dir",
                str(local_secrets_dir),
            ],
            module.ROOT,
        ),
    ]
    assert logged_commands == [
        (
            ["uv", "--no-config", "run", "python", "scripts/prod_canary_smoke.py"],
            module.ROOT,
            artifacts_dir / "prod-canary.log",
        ),
        (
            [
                "uv",
                "--no-config",
                "run",
                "python",
                "scripts/prod_canary_rollback.py",
                "--log-path",
                str(artifacts_dir / "prod-canary.log"),
            ],
            module.ROOT,
            artifacts_dir / "prod-canary-rollback.log",
        ),
    ]
