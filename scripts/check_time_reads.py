#!/usr/bin/env python3
"""Fail on a direct read of the wall clock in production source and the lane doubles.

A process reads the time of the world from the one time source its composition
root installs (`injected_time.now()`), and a duration of its own activity from
the monotonic clock (`docs/guidance/engineering/implementation.md`, "One time
source per process"). A direct wall read bypasses the source, so under injected
time that process alone would read the wall clock while every other party reads
the instant a test set. This check refuses each such read, naming the file and
line:

- `time.time` and `time.time_ns`, called or passed as a value;
- `time.gmtime()` and `time.localtime()` with no argument, or with `None`, which
  read the current instant (with an instant they only convert it);
- `datetime.now`, `datetime.utcnow`, `datetime.today` and `date.today`, called or
  passed as a value;

by any import form: `import time`, `from time import time`, `import datetime`,
`from datetime import datetime`, and an alias of any of them. `time.monotonic` and
`time.perf_counter` are permitted. Names are resolved from the module's imports,
wherever they sit; a local rebinding of an imported name is not followed.

The scope is every project's `src/` under `core/`, `kit/`, `domains/` and
`provisioning/`, and the lane doubles' under `tools/`. The time component's own
source, which is what reads the wall clock for the process, is outside it, as are
tests. The other standalone components under `tools/` are outside it too: each
depends on no internal package, so it cannot read the time component, and takes
its clock as a constructor argument defaulting to the wall clock — the relay's
grant-admission plugin among them, which always runs on wall time. SQL time
defaults are not Python reads and are outside the check.

Usage: `check_time_reads.py [--root <repository>]`. It prints each finding, then
the count of findings per project, and exits 1 when there is any.
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOTS = ("core", "kit", "domains", "provisioning")
LANE_DOUBLES = (
    "tools/payments-lane-double",
    "tools/mediation-lane-double",
    "tools/lane-double-controls",
)
_SKIPPED_DIRS = {".venv", "venv", "node_modules", "__pycache__", ".git", "target", "dist",
                 ".dist", ".mypy_cache", ".pytest_cache"}

# A function of the time module that reads the wall clock: always, or only
# when called with no argument.
_TIME_READS = {"time": True, "time_ns": True, "gmtime": False, "localtime": False}
# A class of the datetime module and its methods that read the wall clock.
_DATETIME_READS = {"datetime": {"now", "utcnow", "today"}, "date": {"today"}}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    # The column tells two reads of one form on one line apart, so each counts.
    column: int
    form: str

    def render(self) -> str:
        return (f"{self.path}:{self.line}: {self.form} reads the wall clock directly; read "
                "the process time source (injected_time.now()), or time.monotonic() "
                "for a duration of the process's own activity")


@dataclass
class _Bindings:
    """What the names a module imports are bound to."""

    time_modules: set[str]
    datetime_modules: set[str]
    time_functions: dict[str, str]  # local name -> time module function
    datetime_classes: dict[str, str]  # local name -> datetime module class


def _bindings(tree: ast.AST) -> _Bindings:
    bound = _Bindings(set(), set(), {}, {})
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "time":
                    bound.time_modules.add(alias.asname or "time")
                elif alias.name == "datetime":
                    bound.datetime_modules.add(alias.asname or "datetime")
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            for alias in node.names:
                if node.module == "time" and alias.name in _TIME_READS:
                    bound.time_functions[alias.asname or alias.name] = alias.name
                elif node.module == "datetime" and alias.name in _DATETIME_READS:
                    bound.datetime_classes[alias.asname or alias.name] = alias.name
    return bound


def _time_function(node: ast.expr, bound: _Bindings) -> str | None:
    """The time module function `node` names, if it names one that may read."""
    if isinstance(node, ast.Name):
        return bound.time_functions.get(node.id)
    if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id in bound.time_modules and node.attr in _TIME_READS):
        return node.attr
    return None


def _datetime_read(node: ast.expr, bound: _Bindings) -> str | None:
    """`<class>.<method>` when `node` names a datetime method that reads the clock."""
    if not isinstance(node, ast.Attribute):
        return None
    owner = node.value
    cls = None
    if isinstance(owner, ast.Name):
        cls = bound.datetime_classes.get(owner.id)
    elif (isinstance(owner, ast.Attribute) and isinstance(owner.value, ast.Name)
          and owner.value.id in bound.datetime_modules and owner.attr in _DATETIME_READS):
        cls = owner.attr
    if cls and node.attr in _DATETIME_READS[cls]:
        return f"{cls}.{node.attr}"
    return None


def reads(text: str, path: str = "<source>") -> list[Finding]:
    """Every direct wall-clock read in one module's source."""
    tree = ast.parse(text, filename=path)
    bound = _bindings(tree)
    found: set[Finding] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function = _time_function(node.func, bound)
            if function and not _TIME_READS[function] and _reads_now(node):
                found.add(Finding(path, node.lineno, node.col_offset, f"time.{function}()"))
        if isinstance(node, (ast.Name, ast.Attribute)) and isinstance(
                getattr(node, "ctx", None), ast.Load):
            function = _time_function(node, bound)
            if function and _TIME_READS[function]:
                found.add(Finding(path, node.lineno, node.col_offset, f"time.{function}"))
            form = _datetime_read(node, bound)
            if form:
                found.add(Finding(path, node.lineno, node.col_offset, form))
    return sorted(found)


def _reads_now(call: ast.Call) -> bool:
    """Whether a `gmtime`/`localtime` call converts the current instant: no
    argument, or `None` as its one."""
    arguments = [*call.args, *(keyword.value for keyword in call.keywords)]
    return not arguments or (
        len(arguments) == 1 and isinstance(arguments[0], ast.Constant)
        and arguments[0].value is None)


def _walk_python(directory: Path):
    for current, subdirectories, files in os.walk(directory):
        subdirectories[:] = sorted(d for d in subdirectories if d not in _SKIPPED_DIRS)
        for name in sorted(files):
            if name.endswith(".py"):
                yield Path(current) / name


def projects(root: Path) -> list[Path]:
    """Every project in scope: each directory under the project roots holding a
    `pyproject.toml`, and the lane doubles."""
    found: list[Path] = []
    for top in PROJECT_ROOTS:
        for current, subdirectories, files in os.walk(root / top):
            subdirectories[:] = sorted(d for d in subdirectories
                                       if d not in _SKIPPED_DIRS and d != "src")
            if "pyproject.toml" in files:
                found.append(Path(current))
    found += [root / double for double in LANE_DOUBLES if (root / double / "pyproject.toml").is_file()]
    return sorted(set(found))


def check(root: Path = ROOT) -> tuple[list[Finding], Counter[str]]:
    """Every finding in scope, and the count of findings per project."""
    findings: list[Finding] = []
    per_project: Counter[str] = Counter()
    for project in projects(root):
        source = project / "src"
        if not source.is_dir():
            continue
        name = project.relative_to(root).as_posix()
        for module in _walk_python(source):
            relative = module.relative_to(root).as_posix()
            found = reads(module.read_text(encoding="utf-8"), relative)
            findings += found
            per_project[name] += len(found)
    return findings, per_project


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    options = parser.parse_args(argv)
    findings, per_project = check(options.root.resolve())
    for finding in findings:
        print(finding.render())
    if findings:
        print()
        for name, count in sorted(per_project.items()):
            if count:
                print(f"{count:5d}  {name}")
        print(f"FAILED: {len(findings)} direct wall-clock read(s) in "
              f"{sum(1 for count in per_project.values() if count)} project(s)")
        return 1
    print("OK: no direct wall-clock read in production source or the lane doubles.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
