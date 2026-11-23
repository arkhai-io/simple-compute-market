"""Fail if an agent skill is not loaded from its one source.

The rule holds two things. The workflow's own skills are the installed
distribution's, loaded from each supported harness's user skill directory: an
installed engine checks them before every subcommand, this check's among them
(`install.require_installed`), and the engine run from its source tree checks
nothing installed. The skills a repository
commits itself each live once, under `.agents/skills/<name>/`, and each supported
harness loads them through a relative symlink of the same name in its own project
skill directory; the workflow's own sources, which the source tree keeps there for
the distribution, need no such link, and a project entry of a workflow skill's name
would stand beside the installed skill as a second copy. Two copies of a skill drift
apart, so this check rejects:

- a shared skill with no `SKILL.md`;
- a harness entry of a workflow skill's name, which the installed skill alone
  provides;
- a shared skill missing from a harness skill directory;
- a harness entry that is not a symlink — a real copy kept beside, or instead
  of, a shared source;
- a harness link that does not resolve, or resolves anywhere but the shared
  skill of the same name.

Contract: openspec/specs/change-workflow/spec.md, CW-d8de.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import documents
from .common import StepError, repository_root

SOURCE = Path(".agents/skills")
HARNESSES = (Path(".claude/skills"), Path(".codex/skills"))


def problems(root: Path, workflow: frozenset[str] = frozenset()) -> list[str]:
    """Where the skills the repository commits are not each loaded from their one
    source; `workflow` names the workflow's own, which each harness loads from its user
    skill directory alone, so no project entry of their names may stand."""
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
            if entry.name in workflow:
                found.append(f"{where}: the workflow's skill {entry.name} is installed into "
                             "the harness's user skill directory; no project entry of its "
                             "name may stand beside it")
                continue
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
            if name not in present and name not in workflow:
                found.append(f"{harness / name}: missing link to {SOURCE / name}")
    return found


def main(root: Path | None = None,
         distribution: documents.Distribution = documents.RUNNING) -> int:
    try:
        root = repository_root() if root is None else root
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    found = problems(root, frozenset(distribution.skills()))
    for problem in found:
        print(problem, file=sys.stderr)
    if found:
        print(f"\n{len(found)} agent skill problem(s). Each skill a repository commits has "
              f"one source under {SOURCE}; the workflow's are installed by "
              "`change-workflow install`.", file=sys.stderr)
        return 1
    print("OK: every agent skill the repository commits is loaded from its one shared "
          "source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
