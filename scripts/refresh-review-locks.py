#!/usr/bin/env python3
"""Refresh selected project lockfiles against current repository wheels."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

PACKAGE_BLOCK = re.compile(r"(?ms)^\[\[package\]\]\n.*?(?=^\[\[package\]\]\n|\Z)")
NAME = re.compile(r'^name = "([^"]+)"$', re.MULTILINE)
SOURCE = re.compile(
    r'^source = \{ (registry|editable|directory) = "([^"]+)" \}$',
    re.MULTILINE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--python", default=os.environ.get("REVIEW_PYTHON", "3.13"))
    parser.add_argument("--projects", nargs="+", required=True)
    return parser.parse_args()


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "_", name).lower()


def wheel_names(dist_dir: Path) -> set[str]:
    names: set[str] = set()
    for wheel in dist_dir.glob("*.whl"):
        # Wheel distribution names cannot contain hyphens; the first component
        # is therefore sufficient for repository wheel discovery.
        names.add(normalized(wheel.name.split("-", 1)[0]))
    return names


def internal_packages(lockfile: Path, available: set[str]) -> list[str]:
    text = lockfile.read_text(encoding="utf-8")
    packages: set[str] = set()
    for match in PACKAGE_BLOCK.finditer(text):
        block = match.group(0)
        name_match = NAME.search(block)
        source_match = SOURCE.search(block)
        if not name_match or not source_match:
            continue
        source_kind, source_path = source_match.groups()
        if source_kind in {"editable", "directory"} and source_path == ".":
            continue
        name = name_match.group(1)
        if normalized(name) in available:
            packages.add(name)
    return sorted(packages)


def main() -> int:
    args = parse_args()
    root = args.root.resolve()
    dist_dir = root / ".dist"
    if not dist_dir.is_dir():
        raise ValueError(f"missing wheel directory: {dist_dir}")
    available = wheel_names(dist_dir)
    if not available:
        raise ValueError(f"no wheels found in {dist_dir}")

    for relative in args.projects:
        project = root / relative
        lockfile = project / "uv.lock"
        pyproject = project / "pyproject.toml"
        if not lockfile.is_file() or not pyproject.is_file():
            raise ValueError(f"review project lacks pyproject.toml or uv.lock: {relative}")
        packages = internal_packages(lockfile, available)
        command = [
            "uv",
            "lock",
            "--python",
            args.python,
            "--find-links",
            str(dist_dir),
        ]
        for package in packages:
            command.extend(("--upgrade-package", package))
        print(f"Refreshing {relative}/uv.lock ({len(packages)} internal packages)")
        subprocess.run(command, cwd=project, check=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
