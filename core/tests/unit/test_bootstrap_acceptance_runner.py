from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/run_bootstrap_acceptance.py"


def _load_script_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_bootstrap_acceptance_runner_defines_reviewable_gate_and_e2e_matrices() -> None:
    module = _load_script_module(SCRIPT_PATH, "run_bootstrap_acceptance")

    assert module.CONTRACT_GATE_MATRIX == [
        (
            ["python", "scripts/check_local_bootstrap_contract.py"],
            module.ROOT,
        ),
        (
            ["python", "scripts/check_installed_bundle_contract.py"],
            module.ROOT,
        ),
    ]
    assert module.E2E_MATRIX == [
        (
            [
                str(module.ROOT / "core/.venv/bin/python"),
                "-m",
                "pytest",
                "tests/e2e/test_manual_local_bootstrap.py",
                "-q",
            ],
            module.ROOT,
        ),
        (
            [
                str(module.ROOT / "core/.venv/bin/python"),
                "-m",
                "pytest",
                "tests/e2e/test_installed_bundle_smoke.py",
                "-q",
            ],
            module.ROOT,
        ),
    ]


def test_bootstrap_acceptance_runner_executes_gates_then_e2e(monkeypatch) -> None:
    module = _load_script_module(SCRIPT_PATH, "run_bootstrap_acceptance_exec")
    commands: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        commands.append((command, cwd))

    monkeypatch.setattr(module, "_run_command", fake_run)

    exit_code = module.main([])

    assert exit_code == 0
    assert commands == module.CONTRACT_GATE_MATRIX + module.E2E_MATRIX
