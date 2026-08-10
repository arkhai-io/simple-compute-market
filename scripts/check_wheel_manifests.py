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
        on_disk = {item.name for item in resolved.iterdir() if item.suffix == ".py"}
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


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    findings: list[str] = []
    for pyproject in sorted(root.glob("domains/**/pyproject.toml")):
        if ".venv" in pyproject.parts or "node_modules" in pyproject.parts:
            continue
        text = pyproject.read_text(encoding="utf-8")
        if "force-include" not in text:
            continue
        findings.extend(audit(pyproject.parent))

    if findings:
        print("Wheel manifests have drifted from their source trees:\n")
        for finding in findings:
            print(f"  {finding}")
        print("\nAdd one force-include entry per file, or remove the stale entry.")
        return 1

    print("OK: every wheel file manifest matches its source tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
