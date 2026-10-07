#!/usr/bin/env python3
"""Print what a Claude Code session must re-read after its context is compacted.

Run by the project's `SessionStart` hook for the `compact` source; Claude Code adds
this script's standard output to the session's context. Compaction keeps a summary
of the task but drops the documents `AGENTS.md` requires reading, and guidance
compliance falls sharply once they are gone. The documents themselves are far
larger than the 10,000 characters a hook may inject, and a digest of their rules
would be a second copy that drifts, so this names what to re-read rather than
restating it, together with the branch and the changes being worked to orient the
session.

Contract: openspec/specs/change-workflow/spec.md.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = Path("openspec/changes/README.md")
REQUIRED = (
    "docs/development/ARCHITECTURE.md",
    "docs/development/TESTING.md",
    "docs/development/DEPLOYMENT_AND_CONFIG.md",
    "openspec/README.md",
)
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


def context(root: Path = ROOT) -> str:
    index = root / INDEX
    progress = changes_in_progress(index.read_text("utf-8")) if index.is_file() else []
    lines = [
        "Your context was just compacted. The summary keeps your task state but not the",
        "repository guidance, and work done without it drifts from the guidance.",
        "Before continuing, re-read these in full with your file tools (AGENTS.md is",
        "still in context):",
        *(f"- {path}" for path in REQUIRED),
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


def main() -> int:
    sys.stdout.write(context())
    return 0


if __name__ == "__main__":
    sys.exit(main())
