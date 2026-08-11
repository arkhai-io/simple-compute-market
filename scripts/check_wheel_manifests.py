#!/usr/bin/env python3
"""Reject a wheel file manifest that has drifted from its source tree.

A project whose wheel is assembled by an explicit
``[tool.hatch.build.targets.wheel.force-include]`` table must list every Python
module in each directory that table references. A module present in the source
tree and absent from the table builds and installs cleanly, then raises
``ModuleNotFoundError`` the first time an installed consumer imports it — so the
defect surfaces as a missing domain plugin rather than as a packaging error.

Directory-level mapping would remove the need for this check, but
``force-include`` bypasses ``exclude``, so a directory mapping ships whatever
happens to be present at build time. Until the affected namespaces are owned by
the distributions that use them, the manifests stay explicit and this check
keeps them honest.

This check exists only while those manifests do. It is removed with them.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

# Shared with scripts/prune_tombstones.py: a file beginning with the marker but
# carrying live code must not be treated as deleted by one check and retained by
# the other.
from tombstones import is_tombstone


import tomllib

FORCE_INCLUDE = ("tool", "hatch", "build", "targets", "wheel", "force-include")


def _table(config: dict, path: tuple[str, ...]) -> dict | None:
    node: object = config
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return None
        node = node[key]
    return node if isinstance(node, dict) else None


def _only_include(config: dict) -> set[str]:
    wheel = _table(config, ("tool", "hatch", "build", "targets", "wheel"))
    if not wheel:
        return set()
    return {Path(entry).name for entry in wheel.get("only-include", [])}


def audit(project: Path) -> list[str]:
    """Return one finding per module missing from ``project``'s manifest."""
    with (project / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)

    manifest = _table(config, FORCE_INCLUDE)
    if not manifest:
        return []

    listed: dict[str, set[str]] = defaultdict(set)
    for source in manifest:
        as_path = Path(source)
        listed[str(as_path.parent)].add(as_path.name)

    exempt = _only_include(config)
    findings: list[str] = []
    for directory, names in sorted(listed.items()):
        resolved = (project / directory).resolve()
        if not resolved.is_dir():
            continue
        on_disk = {
            item.name
            for item in resolved.iterdir()
            if item.suffix == ".py" and not is_tombstone(item)
        }
        tombstoned = {
            item.name
            for item in resolved.iterdir()
            if item.suffix == ".py" and is_tombstone(item)
        }
        for stale in sorted(names & tombstoned):
            findings.append(
                f"{project}/pyproject.toml: {directory}/{stale} is tombstoned "
                "for deletion but still listed in the wheel manifest; remove "
                "the entry"
            )
        for missing in sorted(on_disk - names - exempt):
            findings.append(
                f"{project}/pyproject.toml: {directory}/{missing} exists in the "
                "source tree but is not in the wheel manifest; an installed "
                "consumer importing it will fail"
            )
        for absent in sorted(names - on_disk):
            if absent.endswith(".py"):
                findings.append(
                    f"{project}/pyproject.toml: {directory}/{absent} is listed "
                    "in the wheel manifest but no longer exists"
                )
    return findings


def audit_unowned_packages(root: Path) -> list[str]:
    """Reject a Python package under ``domains/`` that no distribution owns.

    An unowned namespace is what produced the defect this check exists for: two
    consumers reached the same directory by different means, one by a wheel file
    manifest and one by copying the tree onto the interpreter path, and neither
    was answerable for its contents.

    A directory is owned when it sits inside a project directory — one holding a
    ``pyproject.toml`` — or under that project's ``src``. A directory holding only
    tombstones is a pending deletion and is not a package.
    """
    projects = set()
    shipped_sources = set()
    for pyproject in root.glob("domains/**/pyproject.toml"):
        if any(x in pyproject.parts for x in (".venv", "node_modules")):
            continue
        projects.add(pyproject.parent)
        with pyproject.open("rb") as handle:
            manifest = _table(tomllib.load(handle), FORCE_INCLUDE) or {}
        for source in manifest:
            shipped_sources.add((pyproject.parent / source).resolve())

    findings: list[str] = []
    for init in sorted((root / "domains").rglob("__init__.py")):
        if any(x in init.parts for x in (".venv", "node_modules", "build")):
            continue
        directory = init.parent
        live = [
            item
            for item in directory.iterdir()
            if item.suffix == ".py" and not is_tombstone(item)
        ]
        if not live:
            continue
        if any(directory == p or p in directory.parents for p in projects):
            continue
        # A directory whose only live module is its ``__init__.py`` is a
        # namespace anchor rather than a package of its own. It is owned when
        # some project's manifest ships that file, which is how a flat
        # ``domains.<x>.<y>`` import path is assembled inside one wheel.
        if [item.name for item in live] == ["__init__.py"]:
            if init.resolve() in shipped_sources:
                continue
            findings.append(
                f"{directory.relative_to(root)}: namespace anchor shipped by no "
                "distribution; the wheel that assembles this import path must "
                "list its __init__.py"
            )
            continue
        findings.append(
            f"{directory.relative_to(root)}: Python package owned by no "
            "distribution; every shipped module must belong to exactly one "
            "project directory"
        )
    return findings


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    findings: list[str] = []
    findings.extend(audit_unowned_packages(root))
    for pyproject in sorted(root.glob("domains/**/pyproject.toml")):
        if ".venv" in pyproject.parts or "node_modules" in pyproject.parts:
            continue
        text = pyproject.read_text(encoding="utf-8")
        if "force-include" not in text:
            continue
        findings.extend(audit(pyproject.parent))

    if findings:
        print("Packaging ownership problems found:\n")
        for finding in findings:
            print(f"  {finding}")
        print("\nAdd one force-include entry per file, or remove the stale entry.")
        return 1

    print("OK: every wheel file manifest matches its source tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
