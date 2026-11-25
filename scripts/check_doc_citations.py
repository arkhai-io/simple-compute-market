"""Reject a documentation citation whose target is absent or tombstoned.

A document's citations resolve (docs/guidance/engineering/documentation.md,
"Citations resolve"). Here that holds for every `openspec/`, `docs/`, `tools/`,
`scripts/`, `e2e-tests/` and `.agents/` path a document cites, on the branch
(openspec/specs/market-change-workflow/README.md, "The closing checks"), and an
unresolvable citation is a blocking defect rather than a stale link.
`.agents/` holds the skills this repository keeps, its workflow configuration, and
the evidence kinds' guides; the harness skill directories mirror its skills through
links, so it alone is checked.

The existence test this replaces could not fail on a rename-to-tombstone,
which is the most likely broken citation in a renaming change: a tombstoned
file still exists on disk, so `Path.exists()` is true of a file that is
pending deletion and whose content is gone. The predicate for that lives in
`scripts/tombstones.py` and is imported rather than reimplemented, because a
check that disagreed with the prune utility about what a tombstone is would
pass on files the prune then deletes.

Run over permanent documentation and over every unarchived change. Archived
changes are excluded: they are a record of what was true when they were
archived, and their citations are allowed to have moved on. Scoped to one
change by name, the check finds it active or archived, since closeout archives
a change before its review; once it is archived, a citation of the change's own
unarchived path resolves against its archive directory, so the archive move
itself is never reported. Before it is archived, a citation of a capability's
`spec.md` that the change's own delta creates resolves, since closeout checks
citations before the archive writes that file from the delta: the paths it creates
are the ones the workflow's specification index check reports (`check spec-index
<change> --json`), so the two checks agree on what a delta creates. A change's
`reviews/` are excluded too: review records are untracked working notes, never
part of the branch, so a citation in one is not a citation the branch makes. A
checkout's local workflow configuration (`LOCAL_ONLY`) is never on any branch, Git
ignoring it, so a citation of it names a file each checkout holds for itself, and
its absence is no unresolved citation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tombstones import is_tombstone  # noqa: E402
from workflow_command import WorkflowRefused, created_specifications, found_change  # noqa: E402

#: Directories whose paths must resolve when cited.
CITED_ROOTS = ("openspec", "docs", "tools", "scripts", "e2e-tests", ".agents")

#: Suffixes worth checking. A citation without one is usually a directory or
#: prose, and directories are checked separately below.
CITED_SUFFIXES = ("py", "md", "toml", "yml", "yaml", "json", "sh", "mk")

#: The files each checkout keeps for itself, which Git ignores and no branch holds.
LOCAL_ONLY = frozenset({".agents/workflow.local.toml"})

#: A path-looking run inside a document. The lookarounds keep it from biting
#: off the tail of a longer identifier, and the non-greedy body stops at the
#: first suffix match so `a/b.py` is not swallowed into `a/b.py.bak`.
CITATION = re.compile(
    r"(?<![\w./-])((?:%s)/[\w./-]+?\.(?:%s))(?![\w/-])"
    % ("|".join(map(re.escape, CITED_ROOTS)), "|".join(CITED_SUFFIXES))
)


def _found(root: Path, change: str) -> dict:
    """The change as the workflow's command finds it, active or archived; a change it
    does not find ends the check with its reason."""
    try:
        return found_change(root, change)
    except WorkflowRefused as exc:
        raise SystemExit(str(exc)) from exc


def _change_documents(directory: Path) -> list[Path]:
    return sorted(
        path for path in directory.glob("**/*.md")
        if "reviews" not in path.relative_to(directory).parts
    )


def documents(root: Path, change: str | None = None) -> list[Path]:
    """Documents to check.

    With ``change``, only that change's own documents, active or archived. A
    change's closeout owes the citations it wrote, and gating it on the whole
    repository's documentation debt would make one team's stale runbook block
    everyone else's archival -- which turns a useful check into one people
    route around.

    Without ``change``, every permanent document plus every unarchived
    change, which is the repository-wide view.
    """

    changes = root / "openspec" / "changes"
    if change is not None:
        return _change_documents(root / _found(root, change)["directory"])

    found: list[Path] = []
    for pattern in ("openspec/specs/**/*.md", "docs/**/*.md"):
        found.extend(sorted(root.glob(pattern)))
    found.extend(sorted(changes.glob("*.md")))
    for change in sorted(p for p in changes.iterdir() if p.is_dir()):
        if change.name == "archive":
            continue
        found.extend(_change_documents(change))
    return found


def _created_specs(root: Path, change: str) -> frozenset[str]:
    """Each capability's `spec.md`, as cited, that an active change's deltas write
    when the change is archived, as the workflow's specification index check reports
    them; a refusal ends the check with its reason."""
    try:
        return created_specifications(root, change)
    except WorkflowRefused as exc:
        raise SystemExit(str(exc)) from exc


def unresolvable(
    root: Path, change: str | None = None
) -> list[tuple[str, str, str]]:
    """Every citation that is absent or points at a tombstone."""

    own: tuple[str, Path] | None = None
    created: frozenset[str] = frozenset()
    if change is not None:
        found = _found(root, change)
        if found["archived"]:
            own = (f"openspec/changes/{change}/", root / found["directory"])
        else:
            created = _created_specs(root, change)
    problems: list[tuple[str, str, str]] = []
    for document in documents(root, change):
        text = document.read_text(encoding="utf-8", errors="ignore")
        for cited in sorted(set(CITATION.findall(text))):
            target = root / cited
            if own and cited.startswith(own[0]):
                target = own[1] / cited[len(own[0]):]
            if not target.exists():
                if cited not in created and cited not in LOCAL_ONLY:
                    problems.append(("absent", cited, document.as_posix()))
            elif target.is_file() and is_tombstone(target):
                problems.append(("tombstone", cited, document.as_posix()))
    return problems


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    change = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] else None
    scanned = documents(root, change)
    problems = unresolvable(root, change)
    scope = (
        "change %s" % change
        if change
        else "permanent documentation + unarchived changes"
    )
    print(
        "Checking documentation citations in %d documents (%s)..."
        % (len(scanned), scope)
    )
    if not problems:
        print("OK: every cited path resolves and none is a tombstone.")
        return 0
    for kind, cited, document in problems:
        if kind == "absent":
            print("MISSING:   %s\n  cited by %s" % (cited, document))
        else:
            print(
                "TOMBSTONE: %s\n  cited by %s\n"
                "  the target is pending deletion; cite its replacement"
                % (cited, document)
            )
    print(
        "\n%d unresolvable citation(s): each is a blocking defect, not a stale "
        "link." % len(problems)
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
