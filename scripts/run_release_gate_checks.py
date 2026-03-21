#!/usr/bin/env python3
"""Run the expanded release gates for production readiness."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]


def _run_command(command: list[str], *, cwd: Path) -> None:
    print(f"[run] ({cwd}) {' '.join(command)}")
    subprocess.run(command, cwd=cwd, check=True)


def _parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    _, gate_args = parser.parse_known_args(argv)
    return argparse.Namespace(gate_args=gate_args)


def main(argv: Iterable[str] | None = None) -> int:
    args = _parse_args(argv)

    _run_command(
        ["python", "scripts/run_deployment_gate_checks.py", *args.gate_args],
        cwd=ROOT,
    )
    _run_command(["python", "scripts/run_full_repo_validation.py"], cwd=ROOT)

    print("[ok] release gate checks completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
