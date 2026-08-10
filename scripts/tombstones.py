"""Shared tombstone predicate.

A tombstone marks a file as pending deletion: its entire contents are replaced by
a comment stating why. Two checks depend on recognising one — the wheel-manifest
audit must not expect a tombstoned file in a manifest, and the prune utility
deletes them — and they must agree, or a file beginning with a stale tombstone
above live code is treated as deleted by one and retained by the other.
"""

from __future__ import annotations

from pathlib import Path

MARKER = "# TOMBSTONE:"

#: Extensions where a leading ``#`` is a comment. ``.md`` is included even though
#: ``#`` is a heading there: documentation gets deleted too, and a one-line file
#: reading "# TOMBSTONE: ..." is unambiguous either way.
COMMENT_HASH_SUFFIXES = frozenset({
    ".py", ".pyi", ".toml", ".yml", ".yaml", ".sh", ".bash", ".cfg", ".ini",
    ".tf", ".tfvars", ".env", ".mk", ".md", ".gitignore", ".dockerignore",
})

#: Files without a suffix where a leading ``#`` is still a comment.
COMMENT_HASH_NAMES = frozenset({"Makefile", "Dockerfile"})


def is_tombstone(path: Path) -> bool:
    """True when the file's entire meaningful content is a tombstone comment.

    Deliberately strict. A file that merely begins with the marker and then
    carries live code is not deleted — treating it as such would drop working
    modules from a manifest audit. And the documents defining this convention
    show a tombstone inside a fenced example surrounded by prose, which the
    whole-file requirement excludes.
    """
    if path.suffix not in COMMENT_HASH_SUFFIXES and path.name not in COMMENT_HASH_NAMES:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines or not lines[0].lstrip().startswith(MARKER):
        return False
    # A tombstone may wrap onto continuation comment lines, but nothing else.
    return all(line.lstrip().startswith("#") for line in lines)


def reason(path: Path) -> str:
    """The tombstone's stated reason, joined across continuation lines."""
    lines = [
        line.lstrip().lstrip("#").strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    joined = " ".join(lines).removeprefix(MARKER.lstrip("# ")).strip()
    return joined.removeprefix("delete this file").lstrip(" \u2014-")
