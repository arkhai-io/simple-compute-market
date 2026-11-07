#!/usr/bin/env python3
"""Fail if a comment or docstring line a change adds describes history.

Comments describe the current system, not how it came to be (`AGENTS.md`,
"Python comments and docstrings"). `check-comment-hygiene` catches change names
and task numbers over the whole tree; this check catches the wording of history,
the phrases in `WORDS`, in the comment and docstring lines a change's diff adds
to `.py`, `.toml`, `.yml` and `.yaml` files. "Now" and "legacy" are not on the
list: current-state comments and fixtures use them. A line the check misreads is
reworded; there is no exception marker, since a rule with private exceptions is
not the rule as written. The phrases are matched in comments and docstrings
only, so code and single-line string values holding them pass. A TOML or YAML
line is read alone, so a `#` line inside a YAML block scalar or a TOML
multi-line string is read as a comment: in this repository such blocks hold
embedded shell or configuration — a workflow's `run:`, a chart's config file —
whose comments the rule covers. A string line that trips the check is reworded.

Run by `make check-repository`, the change workflow's `pre-commit`, against the merge-base with the branch the change
lands on. Usage: `check_history_wording.py [--base <branch>]`.

Contract: openspec/specs/market-change-workflow/spec.md, MCW-c4ek.
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from change_diff import DEFAULT_BRANCH, BaseNotFound, added_lines, merge_base  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORDS = ("previously", "formerly", "used to", "no longer", "moved from", "was renamed",
         "originally")
SUFFIXES = (".py", ".toml", ".yml", ".yaml")
_HISTORY = re.compile(
    r"\b(" + "|".join(word.replace(" ", r"\s+") for word in WORDS) + r")\b", re.IGNORECASE)
# A quote opens a string only where a value can start, so an apostrophe inside
# a bare word ("don't") does not hide the comment after it.
_VALUE_START = set(" \t:=[,{(-")


class Unreadable(Exception):
    """A Python file whose comments and docstrings cannot be told from its code."""


def python_comments(text: str) -> dict[int, str]:
    """Each line's comment or docstring text in Python source."""
    found: dict[int, str] = {}
    try:
        tree = ast.parse(text)
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (SyntaxError, tokenize.TokenError) as exc:
        raise Unreadable(str(exc)) from exc
    for token in tokens:
        if token.type == tokenize.COMMENT:
            found[token.start[0]] = token.string
    source = text.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)):
                for number in range(first.lineno, (first.end_lineno or first.lineno) + 1):
                    found[number] = source[number - 1]
    return found


def hash_comment(line: str) -> str | None:
    """The `#` comment of one TOML or YAML line, or None."""
    quote: str | None = None
    previous = " "
    escaped = False
    for index, char in enumerate(line):
        if quote:
            # Only a double-quoted string has escapes, in TOML and YAML alike.
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = None
        elif char in "\"'" and previous in _VALUE_START:
            quote = char
        elif char == "#" and previous in " \t":
            return line[index:]
        previous = char
    return None


def problems(root: Path, base: str) -> list[str]:
    found = []
    for path, numbers in sorted(added_lines(root, base, SUFFIXES).items()):
        text = (root / path).read_text("utf-8", errors="replace")
        if path.endswith(".py"):
            try:
                comments = python_comments(text)
            except Unreadable as exc:
                found.append(f"{path}: cannot be read as Python to find its comments: {exc}")
                continue
        else:
            lines = text.splitlines()
            comments = {number: comment for number in numbers if number <= len(lines)
                        if (comment := hash_comment(lines[number - 1])) is not None}
        for number in sorted(numbers):
            if number in comments and (match := _HISTORY.search(comments[number])):
                found.append(f'{path}:{number}: "{match.group(1)}" describes history; '
                             "say what holds now")
    return found


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default=DEFAULT_BRANCH,
                        help="the branch the change lands on (default: %(default)s)")
    args = parser.parse_args(argv)
    try:
        found = problems(root, merge_base(root, args.base))
    except BaseNotFound as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if found:
        print("\n".join(found))
        print()
        print("FAIL: a comment or docstring the change adds describes history. Comments")
        print("describe the current system (AGENTS.md, \"Python comments and docstrings\").")
        return 1
    print(f"OK: no comment or docstring the change adds since {args.base} describes history.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
