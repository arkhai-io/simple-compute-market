"""Print what a Claude Code session must re-read after its context is compacted.

Run by the project's `SessionStart` hook for the `compact` source; Claude Code adds
the hook's standard output to the session's context. Compaction keeps a summary
of the task but drops the documents every step's skill reads as it starts, and
guidance compliance falls sharply once they are gone. Those documents are the
workflow configuration's `load.common`: the hook cannot tell the session's step, so
it names the documents common to every step, and the skill being followed names
its own. The documents themselves are far larger than the 10,000 characters a hook
may inject, and a digest of their rules would be a second copy that drifts, so this
names what to re-read rather than restating it, together with the branch and the
changes being worked to orient the session.

Contract: openspec/specs/change-workflow/spec.md, CW-l7hn.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from . import config
from .common import StepError, repository_root
from .index import INDEX

LIMIT = 9_000


def changes_in_progress(index: str) -> list[tuple[str, str]]:
    """Changes whose index status is `in <phase>`, in index order."""
    found = []
    for line in index.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        # Some campaign tables lead with an `Order` column, so the change link is
        # the first linked cell rather than the first cell, and its status follows.
        link = next((i for i, cell in enumerate(cells) if cell.startswith("[`")), None)
        if link is None or link + 1 >= len(cells):
            continue
        name = cells[link][2:cells[link].index("`", 2)]
        status = cells[link + 1] if cells[link + 1].startswith("in ") else None
        if status:
            found.append((name, status))
    return found


def _branch(root: Path) -> str:
    result = subprocess.run(["git", "branch", "--show-current"], cwd=root,
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() or "(detached HEAD)"


def _documents(root: Path) -> list[str]:
    """What to re-read: the configuration's `load.common`, or, when the configuration
    cannot be read, what to do about that, so the session is still told."""
    try:
        documents = config.load(root).documents(config.COMMON_DOCUMENTS)
    except StepError as exc:
        return [f"The workflow configuration cannot be read, so the documents to re-read "
                f"are unknown: {exc}",
                "Re-read the repository's guidance your skill names before continuing."]
    if not documents:
        return ["The workflow configuration lists no documents every step reads "
                "(load.common); re-read those your skill names before continuing."]
    return ["Before continuing, re-read these in full with your file tools:",
            *(f"- {path}" for path in documents)]


def context(root: Path) -> str:
    index = root / INDEX
    progress = changes_in_progress(index.read_text("utf-8")) if index.is_file() else []
    lines = [
        "Your context was just compacted. The summary keeps your task state but not the",
        "repository guidance, and work done without it drifts from the guidance.",
        *_documents(root),
        "If you are working an OpenSpec change, also re-read its design, the section of",
        "its task list you are on with that section's notes, and the skill you are",
        "following (.agents/skills/<skill>/SKILL.md).",
        "",
        f"Checked-out branch: {_branch(root)}",
    ]
    if progress:
        lines.append("Changes in progress in openspec/changes/README.md:")
        lines += [f"- {name}: {status}" for name, status in progress]
    text = "\n".join(lines) + "\n"
    return text if len(text) <= LIMIT else text[:LIMIT] + "\n…\n"


def main(root: Path | None = None) -> int:
    try:
        root = repository_root() if root is None else root
    except StepError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(context(root))
    return 0


if __name__ == "__main__":
    sys.exit(main())
