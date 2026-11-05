"""What a change's diff adds, against its merge-base with the branch it lands on.

A change's closing checks that judge only what the change wrote read the lines
its diff adds, not every line of a touched file, so a rule written after the
text around it does not fail a change on text it never wrote. The diff runs from the merge-base
to the working tree, untracked files included, since a step runs its closing
checks before it commits: a file the step has not yet added is still the
change's, every line of it added.

The branch is named, `dev` by default, and may be a local branch, on `origin`,
or on `workspace`, the owner's workspace as a change's own clone names it. Any
of these copies may lag the one the change last merged, and a merge-base with a
lagging copy would count the merged commits as the change's, so the newest
merge-base among them is the one read.

Contract: openspec/specs/market-change-workflow/spec.md, MCW-c4ek.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

DEFAULT_BRANCH = "dev"
REMOTES = ("origin", "workspace")
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


class BaseNotFound(Exception):
    """The branch the change lands on has no commit here to diff against."""


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=root,
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def merge_base(root: Path, branch: str = DEFAULT_BRANCH) -> str:
    """The newest commit where HEAD meets `branch`, locally or on a remote."""
    newest: str | None = None
    for ref in (branch, *(f"{remote}/{branch}" for remote in REMOTES)):
        done = _git(root, "merge-base", "HEAD", ref)
        found = done.stdout.strip()
        if done.returncode != 0 or not found:
            continue
        if newest is None or _git(root, "merge-base", "--is-ancestor", newest,
                                  found).returncode == 0:
            newest = found
    if newest is None:
        raise BaseNotFound(
            f"no merge-base with {branch!r}: it is neither a local branch nor on "
            f"{' or '.join(REMOTES)}; fetch it, or name the branch the change lands on")
    return newest


def added_lines(root: Path, base: str, suffixes: tuple[str, ...]) -> dict[str, set[int]]:
    """Each file ending in one of `suffixes` the diff from `base` adds lines to, and
    the numbers of those lines in the working tree's copy."""
    patterns = [f"*{suffix}" for suffix in suffixes]
    # The prefixes are fixed, since a user's diff configuration may change them.
    diff = _git(root, "diff", "-U0", "-M", "--no-color", "--no-ext-diff",
                "--src-prefix=a/", "--dst-prefix=b/", base, "--", *patterns)
    if diff.returncode != 0:
        raise BaseNotFound(f"git diff {base} failed: {diff.stderr.strip()}")
    added: dict[str, set[int]] = {}
    path: str | None = None
    # A file's `+++` header comes before its first hunk; once a hunk starts, a
    # line beginning `+++ ` is an added line whose text starts `++ `.
    in_header = False
    for line in diff.stdout.splitlines():
        if line.startswith("diff --git "):
            path, in_header = None, True
        elif in_header and line.startswith("+++ "):
            # Git ends the header with a tab when the path holds a space.
            target = line[4:].rstrip("\t")
            path = target[2:] if target.startswith("b/") else None
        elif path is not None and (hunk := _HUNK.match(line)):
            in_header = False
            start, count = int(hunk.group(1)), int(hunk.group(2) or "1")
            if count:
                added.setdefault(path, set()).update(range(start, start + count))
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "--", *patterns)
    for name in untracked.stdout.splitlines():
        lines = (root / name).read_text("utf-8", errors="replace").splitlines()
        if lines:
            added[name] = set(range(1, len(lines) + 1))
    return added


def file_at(root: Path, commit: str, path: str) -> str | None:
    """A file's text at `commit`, or None when it did not exist there."""
    shown = _git(root, "show", f"{commit}:{path}")
    return shown.stdout if shown.returncode == 0 else None
