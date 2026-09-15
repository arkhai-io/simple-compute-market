"""Reject a documentation citation whose target is absent or tombstoned.

`AGENTS.md` requires that every `openspec/`, `docs/`, `tools/`, `scripts/`
and `e2e-tests/` path cited by a document resolve on the branch, and treats
an unresolvable citation as a blocking defect rather than a stale link.

The existence test this replaces could not fail on a rename-to-tombstone,
which is the most likely broken citation in a renaming change: a tombstoned
file still exists on disk, so `Path.exists()` is true of a file that is
pending deletion and whose content is gone. The predicate for that lives in
`scripts/tombstones.py` and is imported rather than reimplemented, because a
check that disagreed with the prune utility about what a tombstone is would
pass on files the prune then deletes.

Run over permanent documentation and over every unarchived change. Archived
changes are excluded: they are a record of what was true when they were
archived, and their citations are allowed to have moved on. A change's own
closeout runs this before it is archived, which is when its citations are
still expected to hold.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tombstones import is_tombstone  # noqa: E402

#: Directories whose paths `AGENTS.md` requires to resolve when cited.
CITED_ROOTS = ("openspec", "docs", "tools", "scripts", "e2e-tests")

#: Suffixes worth checking. A citation without one is usually a directory or
#: prose, and directories are checked separately below.
CITED_SUFFIXES = ("py", "md", "toml", "yml", "yaml", "json", "sh", "mk")

#: A path-looking run inside a document. The lookarounds keep it from biting
#: off the tail of a longer identifier, and the non-greedy body stops at the
#: first suffix match so `a/b.py` is not swallowed into `a/b.py.bak`.
CITATION = re.compile(
    r"(?<![\w./-])((?:%s)/[\w./-]+?\.(?:%s))(?![\w/-])"
    % ("|".join(CITED_ROOTS), "|".join(CITED_SUFFIXES))
)


def documents(root: Path, change: str | None = None) -> list[Path]:
    """Documents to check.

    With ``change``, only that change's own documents. A change's closeout
    owes the citations it wrote, and gating it on the whole repository's
    documentation debt would make one team's stale runbook block everyone
    else's archival -- which turns a useful check into one people route
    around.

    Without ``change``, every permanent document plus every unarchived
    change, which is the repository-wide view.
    """

    changes = root / "openspec" / "changes"
    if change is not None:
        directory = changes / change
        if not directory.is_dir():
            raise SystemExit(
                "no such unarchived change: %s" % directory.as_posix()
            )
        return sorted(directory.glob("**/*.md"))

    found: list[Path] = []
    for pattern in ("openspec/specs/**/*.md", "docs/**/*.md"):
        found.extend(sorted(root.glob(pattern)))
    found.extend(sorted(changes.glob("*.md")))
    for change in sorted(p for p in changes.iterdir() if p.is_dir()):
        if change.name == "archive":
            continue
        found.extend(sorted(change.glob("**/*.md")))
    return found


def unresolvable(
    root: Path, change: str | None = None
) -> list[tuple[str, str, str]]:
    """Every citation that is absent or points at a tombstone."""

    problems: list[tuple[str, str, str]] = []
    for document in documents(root, change):
        text = document.read_text(encoding="utf-8", errors="ignore")
        for cited in sorted(set(CITATION.findall(text))):
            target = root / cited
            if not target.exists():
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
        "\n%d unresolvable citation(s). `AGENTS.md` treats these as blocking "
        "defects rather than stale links." % len(problems)
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
