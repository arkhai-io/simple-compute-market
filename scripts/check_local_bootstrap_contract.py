#!/usr/bin/env python3
"""Run the canonical local-bootstrap contract checks."""

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
            "tests/unit/test_bootstrap_contract.py",
            "tests/unit/test_bootstrap_local_dev.py",
            "tests/unit/test_test_env_helper.py",
            "tests/unit/test_local_bootstrap_docs_contract.py",
            "tests/unit/test_compose_deprecation_contract.py",
            "-q",
        ],
        ROOT / "core",
    ),
    (
        ["uv", "--no-config", "run", "pytest", "tests/test_dev_cli.py", "-q"],
        ROOT / "cli",
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

    print("[ok] local bootstrap contract checks completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
