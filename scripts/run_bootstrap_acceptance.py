#!/usr/bin/env python3
"""Run the heavyweight bootstrap acceptance checks."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_GATE_MATRIX: list[tuple[list[str], Path]] = [
    (
        ["python", "scripts/check_local_bootstrap_contract.py"],
        ROOT,
    ),
    (
        ["python", "scripts/check_installed_bundle_contract.py"],
        ROOT,
    ),
]
E2E_MATRIX: list[tuple[list[str], Path]] = [
    (
        [
            str(ROOT / "core/.venv/bin/python"),
            "-m",
            "pytest",
            "tests/e2e/test_manual_local_bootstrap.py",
            "-q",
        ],
        ROOT,
    ),
    (
        [
            str(ROOT / "core/.venv/bin/python"),
            "-m",
            "pytest",
            "tests/e2e/test_installed_bundle_smoke.py",
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

    for command, cwd in CONTRACT_GATE_MATRIX + E2E_MATRIX:
        _run_command(command, cwd=cwd)

    print("[ok] bootstrap acceptance completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
