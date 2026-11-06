#!/usr/bin/env python3
"""Fail if an import a change adds inside a function gives no reason.

Imports go at module level unless one has a reason to stay local — a circular
import the move was tried against, or a deliberate lazy load — recorded beside it
(`openspec/README.md`, "Plan closeout requirements", part 2). This check reads
the imports a change's diff adds or touches inside a function and fails on each
with no comment: one ending a line of the statement, or one on its own on the
line above. A comment that is only a tool's directive (`noqa`, `type:`,
`pragma`) gives no reason. Whether the reason is sound stays with review.

Run by `make check-repository`, the change workflow's `pre-commit`, against the merge-base with the branch the change
lands on. Usage: `check_local_imports.py [--base <branch>]`.

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
_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)
# A comment that only instructs tools says nothing about why the import is
# local, so it is not a reason; a directive followed by a reason is one.
_DIRECTIVE = re.compile(
    r"(?:noqa(?::\s*[A-Z]+\d+(?:\s*,\s*[A-Z]+\d+)*)?|type:\s*ignore(?:\[[^\]]*\])?"
    r"|pyright:\s*ignore(?:\[[^\]]*\])?|pylint:\s*disable=[\w,-]+"
    r"|pragma:\s*no\s*(?:cover|branch)|(?:fmt|isort):\s*(?:skip|off|on))",
    re.IGNORECASE)


def _directive_only(comment: str) -> bool:
    """Whether a comment is empty or nothing but tool directives, one or several."""
    parts = [part.strip() for part in comment.split("#")[1:] if part.strip()]
    return all(_DIRECTIVE.fullmatch(part) for part in parts)


def local_imports(tree: ast.AST) -> list[ast.Import | ast.ImportFrom]:
    """Every import inside a function, nested functions' included."""
    found: list[ast.Import | ast.ImportFrom] = []

    def visit(node: ast.AST, inside: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if inside and isinstance(child, (ast.Import, ast.ImportFrom)):
                found.append(child)
            visit(child, inside or isinstance(child, _FUNCTIONS))

    visit(tree, False)
    return found


def unexplained(text: str, added: set[int]) -> list[int]:
    """The first line of each added local import in `text` that carries no reason."""
    tree = ast.parse(text)
    commented = {token.start[0] for token in
                 tokenize.generate_tokens(io.StringIO(text).readline)
                 if token.type == tokenize.COMMENT and not _directive_only(token.string)}
    source = text.splitlines()
    lines = []
    for node in local_imports(tree):
        span = range(node.lineno, (node.end_lineno or node.lineno) + 1)
        if not added.intersection(span):
            continue
        above = source[node.lineno - 2].strip() if node.lineno > 1 else ""
        reason_above = above.startswith("#") and not _directive_only(above)
        if not commented.intersection(span) and not reason_above:
            lines.append(node.lineno)
    return sorted(lines)


def problems(root: Path, base: str) -> list[str]:
    found = []
    for path, numbers in sorted(added_lines(root, base, (".py",)).items()):
        try:
            missing = unexplained((root / path).read_text("utf-8", errors="replace"), numbers)
        except (SyntaxError, tokenize.TokenError) as exc:
            found.append(f"{path}: cannot be read as Python to find its imports: {exc}")
            continue
        found.extend(f"{path}:{number}: an import inside a function gives no reason to stay "
                     "local" for number in missing)
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
        print("FAIL: move each import to module level, or say beside it why it stays local:")
        print("a circular import the move was tried against, or a deliberate lazy load.")
        return 1
    print(f"OK: every import the change adds inside a function since {args.base} gives "
          "its reason.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
