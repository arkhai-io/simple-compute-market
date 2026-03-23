from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
FAST_SCRIPT_PATH = ROOT / "scripts/run_fast_repo_validation.py"
SCRIPT_PATH = ROOT / "scripts/run_full_repo_validation.py"


def _load_script_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fast_repo_validation_runner_defines_reviewable_command_matrix() -> None:
    module = _load_script_module(FAST_SCRIPT_PATH, "run_fast_repo_validation")

    assert module.TEST_MATRIX == [
        (
            [
                "uv",
                "--no-config",
                "run",
                "pytest",
                "tests",
                "agent/test_market_env.py",
                "-q",
            ],
            module.ROOT / "core",
        ),
        (
            ["uv", "--no-config", "run", "pytest", "-q"],
            module.ROOT / "service",
        ),
        (
            ["uv", "--no-config", "run", "pytest", "-q"],
            module.ROOT / "cli",
        ),
        (
            ["uv", "--no-config", "run", "pytest", "-q"],
            module.ROOT / "async-provisioning-service",
        ),
        (
            ["uv", "--no-config", "run", "pytest", "-q"],
            module.ROOT / "erc-8004-registry-py",
        ),
        (
            ["uv", "--no-config", "run", "pytest", "../domain/compute/tests", "-q"],
            module.ROOT / "core",
        ),
        (
            [
                "bash",
                "-lc",
                "if [ -s \"$HOME/.nvm/nvm.sh\" ]; then "
                "source ~/.nvm/nvm.sh && "
                "nvm use 22.12.0 >/dev/null; "
                "else "
                "test \"$(node -v)\" = \"v22.12.0\"; "
                "fi && "
                "export SEPOLIA_RPC_URL=http://127.0.0.1:8545 "
                "MAINNET_RPC_URL=http://127.0.0.1:8545 && "
                "npm ci --legacy-peer-deps && "
                "npx hardhat compile && "
                "npm test",
            ],
            module.ROOT / "erc-8004-contracts",
        ),
    ]


def test_fast_repo_validation_runner_executes_matrix_in_order(monkeypatch) -> None:
    module = _load_script_module(FAST_SCRIPT_PATH, "run_fast_repo_validation")
    commands: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        commands.append((command, cwd))

    monkeypatch.setattr(module, "_run_command", fake_run)

    exit_code = module.main([])

    assert exit_code == 0
    assert commands == module.TEST_MATRIX


def test_full_repo_validation_runner_extends_fast_matrix_with_heavy_slices() -> None:
    module = _load_script_module(SCRIPT_PATH, "run_full_repo_validation")

    assert module.FAST_TEST_MATRIX == [
        (
            [
                "python",
                "scripts/run_fast_repo_validation.py",
            ],
            module.ROOT,
        ),
    ]
    assert module.FULL_ONLY_TEST_MATRIX == [
        (
            ["python", "-B", "-m", "pytest", "tests", "-q"],
            module.ROOT / "compute-provisioning-iac",
        ),
        (
            [
                str(module.ROOT / "core/.venv/bin/python"),
                "-m",
                "pytest",
                "tests/e2e/test_local_dual_agent_stack.py",
                "-q",
            ],
            module.ROOT,
        ),
    ]


def test_full_repo_validation_runner_executes_fast_then_full_only_commands(monkeypatch) -> None:
    module = _load_script_module(SCRIPT_PATH, "run_full_repo_validation")
    commands: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], *, cwd: Path) -> None:
        commands.append((command, cwd))

    monkeypatch.setattr(module, "_run_command", fake_run)

    exit_code = module.main([])

    assert exit_code == 0
    assert commands == module.FAST_TEST_MATRIX + module.FULL_ONLY_TEST_MATRIX
