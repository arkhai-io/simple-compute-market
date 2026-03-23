#!/usr/bin/env python3
"""Run the full cross-repo validation matrix, including heavyweight slices."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
FAST_TEST_MATRIX: list[tuple[list[str], Path]] = [
    (
        [
            "python",
            "scripts/run_fast_repo_validation.py",
        ],
        ROOT,
    ),
]
FULL_ONLY_TEST_MATRIX: list[tuple[list[str], Path]] = [
    (
        ["python", "-B", "-m", "pytest", "tests", "-q"],
        ROOT / "compute-provisioning-iac",
    ),
    (
        [
            str(ROOT / "core/.venv/bin/python"),
            "-m",
            "pytest",
            "tests/e2e/test_local_dual_agent_stack.py",
            "-q",
        ],
        ROOT,
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

    for command, cwd in FAST_TEST_MATRIX + FULL_ONLY_TEST_MATRIX:
        _run_command(command, cwd=cwd)

    print("[ok] full repo validation completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
