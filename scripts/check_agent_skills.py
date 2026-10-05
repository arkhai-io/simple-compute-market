"""Fail if an agent skill is not loaded from its one shared source.

Every committed skill lives once, under `.agents/skills/<name>/`, and each
supported harness loads it through a relative symlink of the same name in its
own skill directory. Two copies of a skill drift apart, so this check rejects:

- a shared skill with no `SKILL.md`;
- a shared skill missing from a harness skill directory;
- a harness entry that is not a symlink — a real copy kept beside, or instead
  of, a shared source;
- a harness link that does not resolve, or resolves anywhere but the shared
  skill of the same name.

Contract: openspec/specs/change-workflow/spec.md.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(".agents/skills")
HARNESSES = (Path(".claude/skills"), Path(".codex/skills"))


def problems(root: Path = ROOT) -> list[str]:
    source = root / SOURCE
    shared = sorted(p.name for p in source.iterdir() if p.is_dir()) if source.is_dir() else []
    found = []
    for name in shared:
        if not (source / name / "SKILL.md").is_file():
            found.append(f"{SOURCE / name}: shared skill has no SKILL.md")
    for harness in HARNESSES:
        directory = root / harness
        entries = sorted(directory.iterdir(), key=lambda p: p.name) if directory.is_dir() else []
        for entry in entries:
            where = harness / entry.name
            if not entry.is_symlink():
                found.append(f"{where}: a copy, not a link to {SOURCE / entry.name}")
                continue
            target = entry.resolve()
            if not target.exists():
                found.append(f"{where}: link does not resolve")
            elif target != (source / entry.name).resolve():
                found.append(f"{where}: links to {target}, not {SOURCE / entry.name}")
        present = {entry.name for entry in entries}
        for name in shared:
            if name not in present:
                found.append(f"{harness / name}: missing link to {SOURCE / name}")
    return found


def main() -> int:
    found = problems()
    for problem in found:
        print(problem)
    if found:
        print(f"\n{len(found)} agent skill problem(s). Each skill has one source under {SOURCE}.")
        return 1
    print("OK: every agent skill is loaded from its one shared source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
