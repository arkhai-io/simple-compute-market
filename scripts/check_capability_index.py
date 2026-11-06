#!/usr/bin/env python3
"""Fail if the capability index and the capabilities it lists disagree.

`openspec/specs/README.md` is the canonical capability documentation index
(`AGENTS.md`, "Documentation ownership"): a capability it does not list is one a
reader starting there never finds. Every `openspec/specs/<capability>/` holding a
`spec.md` must have a row in the index's `## Capabilities` table linking that
`spec.md`, and every row of that table must link a capability's `spec.md` and
nothing that does not exist.

Run by `make check-repository`, the change workflow's `pre-commit`. Usage: `check_capability_index.py`.

Contract: openspec/specs/market-change-workflow/spec.md, MCW-c4ek.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECS = Path("openspec/specs")
INDEX = SPECS / "README.md"
_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
_HEADING = re.compile(r"^#+\s")


def table_rows(index: str) -> list[str]:
    """The body rows of the table under the index's `## Capabilities` heading:
    every table line there but the first two, its header and delimiter."""
    rows, inside = [], False
    for line in index.splitlines():
        if _HEADING.match(line):
            inside = line.strip() == "## Capabilities"
        elif inside and line.lstrip().startswith("|"):
            rows.append(line)
    return rows[2:]


def problems(root: Path) -> list[str]:
    specs = root / SPECS
    capabilities = sorted(path.parent.name for path in specs.glob("*/spec.md"))
    linked: set[str] = set()
    found = []
    for row in table_rows((root / INDEX).read_text("utf-8")):
        row_capabilities = set()
        for target in _LINK.findall(row):
            if "://" in target:
                continue
            resolved = (specs / target).resolve()
            if not resolved.is_file():
                found.append(f"{INDEX.as_posix()}: the row `{row.strip()}` links "
                             f"{target}, which does not exist")
            elif resolved.name == "spec.md" and resolved.parent.parent == specs.resolve():
                row_capabilities.add(resolved.parent.name)
        if not row_capabilities:
            found.append(f"{INDEX.as_posix()}: the row `{row.strip()}` links no "
                         "capability's spec.md")
        linked |= row_capabilities
    found.extend(f"{INDEX.as_posix()}: no row links {(SPECS / name / 'spec.md').as_posix()}"
                 for name in capabilities if name not in linked)
    return found


def main(root: Path = ROOT) -> int:
    if found := problems(root):
        print("\n".join(found))
        print()
        print("FAIL: the capability index must list every capability with a specification,")
        print("and link nothing that does not exist.")
        return 1
    print("OK: the capability index lists every capability, and each of its links resolves.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
