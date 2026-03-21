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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    commands: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        commands.append((command, cwd))

    monkeypatch.setattr(module, "_run_command", fake_run)

    canary_log = tmp_path / "prod-canary.log"
    canary_log.write_text(
        "[success] canary completed\n"
        '{\n'
        '  "status": "succeeded",\n'
        '  "seller_order_id": "seller-order",\n'
        '  "buyer_order_id": "buyer-order",\n'
        '  "provisioning_job_id": "job-1"\n'
        '}\n',
        encoding="utf-8",
    )

    exit_code = module.main(["--deployed-canary-log", str(canary_log)])

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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    commands: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        commands.append((command, cwd))

    monkeypatch.setattr(module, "_run_command", fake_run)

    canary_log = tmp_path / "prod-canary.log"
    canary_log.write_text(
        "[success] canary completed\n"
        '{\n'
        '  "status": "succeeded",\n'
        '  "seller_order_id": "seller-order",\n'
        '  "buyer_order_id": "buyer-order",\n'
        '  "provisioning_job_id": "job-1"\n'
        '}\n',
        encoding="utf-8",
    )

    exit_code = module.main(
        [
            "--deployed-canary-log",
            str(canary_log),
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


def test_release_gate_runner_accepts_legacy_successful_canary_log(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_script_module()
    commands: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        commands.append((command, cwd))

    monkeypatch.setattr(module, "_run_command", fake_run)

    canary_log = tmp_path / "prod-canary.log"
    canary_log.write_text(
        "[success] canary completed\n"
        '{\n'
        '  "job": {"job_id": "job-1"},\n'
        '  "orders": {\n'
        '    "seller-order": {"status": "closed"},\n'
        '    "buyer-order": {"status": "closed"}\n'
        "  }\n"
        '}\n',
        encoding="utf-8",
    )

    exit_code = module.main(["--deployed-canary-log", str(canary_log)])

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


def test_release_gate_runner_requires_deployed_canary_log() -> None:
    module = _load_script_module()

    with pytest.raises(SystemExit, match="Provide --deployed-canary-log"):
        module.main([])


def test_release_gate_runner_rejects_unsuccessful_canary_log(tmp_path: Path) -> None:
    module = _load_script_module()
    canary_log = tmp_path / "prod-canary.log"
    canary_log.write_text(
        "[success] canary completed\n"
        '{\n'
        '  "status": "failed",\n'
        '  "seller_order_id": "seller-order"\n'
        '}\n',
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="does not prove a successful deployed canary"):
        module.main(["--deployed-canary-log", str(canary_log)])
