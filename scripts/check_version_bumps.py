#!/usr/bin/env python3
"""Fail if a change moves a package's version more than one SemVer step.

A package a change alters is bumped once for the change, not once per commit
(`docs/development/RELEASING.md`, "Versioning policy"). Each `pyproject.toml`
whose version differs from its version at the merge-base with the branch the
change lands on must be exactly one step from it: the next patch, minor, or
major, with the lower parts reset. A larger bump replacing a smaller one is
therefore one step from the merge-base, and passes. A package the change leaves
at its version is not checked, since the rule asks for no bump, and neither is
a package that did not exist at the merge-base.

Run by `make check-repository`, the change workflow's `pre-commit`. Usage: `check_version_bumps.py [--base <branch>]`.

Contract: openspec/specs/market-change-workflow/spec.md, MCW-c4ek.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from change_diff import DEFAULT_BRANCH, BaseNotFound, file_at, merge_base  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
_SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def version(text: str) -> str | None:
    """The `[project]` version a `pyproject.toml` declares, or None."""
    declared = tomllib.loads(text).get("project", {}).get("version")
    return declared if isinstance(declared, str) else None


def package_name(text: str, path: str) -> str:
    """The distribution a `pyproject.toml` declares, with where it lives."""
    name = tomllib.loads(text).get("project", {}).get("name")
    return f"{name} ({path})" if isinstance(name, str) else path


def next_steps(old: str) -> tuple[str, str, str] | None:
    """The next patch, minor, and major of an X.Y.Z version, or None."""
    match = _SEMVER.match(old)
    if not match:
        return None
    major, minor, patch = map(int, match.groups())
    return (f"{major}.{minor}.{patch + 1}", f"{major}.{minor + 1}.0", f"{major + 1}.0.0")


def bump_problem(package: str, old: str, new: str) -> str | None:
    """Why `old` → `new` is not one SemVer step, or None when it is."""
    if old == new:
        return None
    steps = next_steps(old)
    if steps is None or not _SEMVER.match(new):
        return f"{package}: {old} → {new} is not a MAJOR.MINOR.PATCH version step"
    if new not in steps:
        return (f"{package}: {old} → {new} is more than one version step; "
                f"bump once, to one of {', '.join(steps)}")
    return None


def _pyprojects(root: Path) -> list[str]:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--",
         "pyproject.toml", "*/pyproject.toml"],
        cwd=root, capture_output=True, text=True, check=True).stdout
    return sorted({name for name in listed.splitlines() if (root / name).is_file()})


def problems(root: Path, base: str) -> list[str]:
    found = []
    for path in _pyprojects(root):
        before = file_at(root, base, path)
        if before is None:
            continue
        after = (root / path).read_text("utf-8")
        old, new = version(before), version(after)
        if old is not None and new is not None and (
                problem := bump_problem(package_name(after, path), old, new)):
            found.append(problem)
    return found


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=DEFAULT_BRANCH,
                        help="the branch the change lands on (default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        found = problems(root, merge_base(root, args.base))
    except BaseNotFound as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if found:
        print("\n".join(found))
        print()
        print("FAIL: a package is bumped once per change, by one SemVer step from the version")
        print("it has where the change began (docs/development/RELEASING.md, \"Versioning policy\").")
        return 1
    print(f"OK: every package version the change moves since {args.base} moves one step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
