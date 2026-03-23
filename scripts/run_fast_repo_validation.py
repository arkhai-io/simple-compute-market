#!/usr/bin/env python3
"""Run the fast cross-repo validation matrix from one canonical entrypoint."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
TEST_MATRIX: list[tuple[list[str], Path]] = [
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
        ROOT / "core",
    ),
    (
        ["uv", "--no-config", "run", "pytest", "-q"],
        ROOT / "service",
    ),
    (
        ["uv", "--no-config", "run", "pytest", "-q"],
        ROOT / "cli",
    ),
    (
        ["uv", "--no-config", "run", "pytest", "-q"],
        ROOT / "async-provisioning-service",
    ),
    (
        ["uv", "--no-config", "run", "pytest", "-q"],
        ROOT / "erc-8004-registry-py",
    ),
    (
        ["uv", "--no-config", "run", "pytest", "../domain/compute/tests", "-q"],
        ROOT / "core",
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
        ROOT / "erc-8004-contracts",
    ),
]


def _run_command(command: list[str], *, cwd: Path) -> None:
    print(f"[run] ({cwd}) {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    _parse_args(argv)

    for command, cwd in TEST_MATRIX:
        _run_command(command, cwd=cwd)

    print("[ok] fast repo validation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
