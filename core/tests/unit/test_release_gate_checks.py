from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/run_release_gate_checks.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("run_release_gate_checks", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_gate_runner_executes_deployment_gate_then_full_matrix(
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
            ["python", "scripts/run_deployment_gate_checks.py"],
            module.ROOT,
        ),
        (
            ["python", "scripts/run_full_repo_validation.py"],
            module.ROOT,
        ),
    ]


def test_release_gate_runner_forwards_gate_arguments_to_deployment_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    commands: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        commands.append((command, cwd))

    monkeypatch.setattr(module, "_run_command", fake_run)

    exit_code = module.main(
        [
            "--environment",
            "production",
            "--seller-agent-env",
            "/tmp/seller.env",
            "--buyer-agent-env",
            "/tmp/buyer.env",
            "--provisioning-env",
            "/tmp/provisioning.env",
            "--registry-env",
            "/tmp/registry.env",
            "--inventory-path",
            "/tmp/hosts",
            "--skip-smoke-help",
        ]
    )

    assert exit_code == 0
    assert commands[0] == (
        [
            "python",
            "scripts/run_deployment_gate_checks.py",
            "--environment",
            "production",
            "--seller-agent-env",
            "/tmp/seller.env",
            "--buyer-agent-env",
            "/tmp/buyer.env",
            "--provisioning-env",
            "/tmp/provisioning.env",
            "--registry-env",
            "/tmp/registry.env",
            "--inventory-path",
            "/tmp/hosts",
            "--skip-smoke-help",
        ],
        module.ROOT,
    )
    assert commands[1] == (
        ["python", "scripts/run_full_repo_validation.py"],
        module.ROOT,
    )
