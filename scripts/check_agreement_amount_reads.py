#!/usr/bin/env python3
"""Require classification of every production amount read.

Python's dynamic carriers make type/name-based exemptions unsafe: a wrapper or
alias can hide an Agreement. Instead all attribute, mapping and reflective
amount reads are inventoried, including reads of unrelated amount-bearing
models. Each exemption identifies an exact expression and enclosing function,
its occurrence count, and a reviewable reason in agreement_amount_reads.json.
New expressions and changed counts fail closed; stale exemptions fail too.

Model declarations and writes are not reads. Tests and temporary change probes
may inspect raw carriers; production Python in core, kit, domains, provisioning,
tools, e2e-tests and scripts is checked, including untracked new source files.
"""
from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOTS = ("core", "kit", "domains", "provisioning", "tools", "e2e-tests", "scripts")
EXCLUDED = {".venv", "__pycache__", "tests", ".git", "node_modules", "test-vectors"}


def amount_reads(source: str) -> list[tuple[str, str, int]]:
    """Find syntactic reads without trusting the receiver's name or type."""
    tree = ast.parse(source)
    # A key alias must not turn a literal mapping/reflection read invisible.
    keys: set[str] = set()
    readers = {"getattr": 1, "hasattr": 1, "attrgetter": 0, "itemgetter": 0}
    methods = {"get", "pop", "setdefault", "__getitem__", "__getattribute__", "attrgetter", "itemgetter"}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module in {"builtins", "operator"}:
                for alias in node.names:
                    if alias.name in readers:
                        readers[alias.asname or alias.name] = readers[alias.name]
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                reader = (readers.get(value.id) if isinstance(value, ast.Name) else
                          0 if isinstance(value, ast.Attribute) and value.attr in methods else None)
                if reader is not None:
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in readers:
                            readers[target.id] = reader
                            changed = True
                if (isinstance(value, ast.Constant) and value.value == "amount"
                        or isinstance(value, ast.Name) and value.id in keys):
                    for target in targets:
                        if isinstance(target, ast.Name) and target.id not in keys:
                            keys.add(target.id)
                            changed = True

    def amount_key(node: ast.AST) -> bool:
        return (isinstance(node, ast.Constant) and node.value == "amount"
                or isinstance(node, ast.Name) and node.id in keys)

    found = []

    def visit(node: ast.AST, scope: tuple[str, ...]) -> None:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = (*scope, node.name)
        read = isinstance(node, ast.Attribute) and node.attr == "amount" and isinstance(node.ctx, ast.Load)
        read |= isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) and amount_key(node.slice)
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr in methods
                    and node.args and amount_key(node.args[0])):
                read = True
            if (isinstance(node.func, ast.Name) and node.func.id in readers
                    and len(node.args) > readers[node.func.id]
                    and amount_key(node.args[readers[node.func.id]])):
                read = True
        if read:
            found.append((".".join(scope) or "<module>", ast.unparse(node), node.lineno))
        for child in ast.iter_child_nodes(node):
            visit(child, scope)

    visit(tree, ())
    return found


def inventory(root: Path) -> tuple[Counter, dict[tuple[str, str, str], int]]:
    counts: Counter = Counter()
    lines = {}
    for directory in ROOTS:
        for path in sorted((root / directory).rglob("*.py")):
            relative = path.relative_to(root)
            if EXCLUDED.intersection(relative.parts) or path.name.startswith("test_"):
                continue
            for scope, expression, line in amount_reads(path.read_text("utf-8")):
                key = (relative.as_posix(), scope, expression)
                counts[key] += 1
                lines[key] = line
    return counts, lines


def problems(root: Path = ROOT) -> list[str]:
    counts, lines = inventory(root)
    records = json.loads((root / "scripts/agreement_amount_reads.json").read_text("utf-8"))
    allowed = {}
    errors = []
    for record in records:
        key = (record["path"], record["scope"], record["expression"])
        if key in allowed or not record.get("reason", "").strip():
            errors.append(f"{key}: duplicate classification or missing reason")
        allowed[key] = record["count"]
    for key, count in counts.items():
        if allowed.get(key) != count:
            path, scope, expression = key
            errors.append(f"{path}:{lines[key]} {scope}: unclassified amount read "
                          f"({count} occurrences): {expression}")
    for key in allowed.keys() - counts.keys():
        errors.append(f"{key}: stale amount-read classification")
    return errors


def main() -> int:
    try:
        errors = problems()
    except (SyntaxError, ValueError, KeyError, OSError) as exc:
        print(f"amount-read guard cannot classify source: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("OK: production amount reads are classified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
