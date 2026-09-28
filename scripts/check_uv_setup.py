"""Fail if an environment or image install names internal packages by hand.

Every `reinit` target, and every Dockerfile install from the repository
wheelhouse, must go through `scripts/uv_project.py`, which derives the
internal packages from the project's lock when it runs. This check rejects:

- in Makefiles: a literal `--upgrade-package`, `--reinstall-package`, or
  `--refresh-package`; a recipe that runs `uv sync` itself; a `reinit` recipe
  other than a single call to the script by a path that resolves; and a
  project with tests whose lock installs wheelhouse packages but that has no
  `reinit` target;
- in Dockerfiles that copy the wheelhouse: those same flags; a `sed` rewrite
  of a lock's registry; a repository distribution's `name==version`; a
  `uv sync` or wheelhouse `uv pip install` not made through the script; a call
  to the script at a path the stage did not copy it to; and a final (runtime)
  stage that copies the wheelhouse.

Makefiles are read with Make's rules: backslash-newline joins lines, and a
comment on a rule line runs to the end of the joined line, so text continued
after a help comment is not recipe text.

Conventions: docs/development/BUILD_AND_PACKAGING.md.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SPEC = importlib.util.spec_from_file_location(
    "uv_project", Path(__file__).resolve().parent / "uv_project.py"
)
assert _SPEC and _SPEC.loader
uv_project = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(uv_project)

SKIPPED_DIRS = {".venv", "node_modules", "openspec", ".git"}
PACKAGE_FLAG = re.compile(r"--(?:upgrade|reinstall|refresh)-package\b")
RULE = re.compile(r"^([^\t#=:][^=:]*?)\s*:(?![=:])(.*)$")
UV_SYNC = re.compile(r"\buv\s+sync\b")
SCRIPT_CALL = re.compile(r"(\S*uv_project\.py)\b")
REINIT_RECIPE = re.compile(r"^python3\s+(\S+/uv_project\.py)\s+reinit\s*$")


def _files(root: Path, pattern: str) -> list[Path]:
    return sorted(
        path for path in root.rglob(pattern)
        if path.is_file() and not SKIPPED_DIRS & set(path.relative_to(root).parts)
    )


def logical_lines(text: str) -> list[str]:
    """Join backslash-newline continuations, as Make and Docker both do."""
    joined, pending = [], ""
    for line in text.split("\n"):
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        joined.append(pending + line)
        pending = ""
    if pending:
        joined.append(pending)
    return joined


def makefile_rules(text: str) -> dict[str, tuple[list[str], list[str]]]:
    """Map each target to its prerequisites and recipe lines."""
    rules: dict[str, tuple[list[str], list[str]]] = {}
    current: list[str] = []
    for line in logical_lines(text):
        if line.startswith("\t"):
            for target in current:
                rules[target][1].append(line.strip())
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = RULE.match(line)
        if not match or line.startswith((" ", "export ", "define ", "ifeq", "ifneq", "include")):
            current = []
            continue
        prerequisites = match.group(2).split("#", 1)[0].split(";", 1)[0].split()
        current = [t for t in match.group(1).split() if t != ".PHONY"]
        for target in current:
            rules.setdefault(target, ([], []))[0].extend(prerequisites)
    return rules


def _chain(rules: dict, target: str, seen: set[str] | None = None) -> list[str]:
    """Recipe lines of ``target`` and every in-file prerequisite it reaches."""
    seen = seen if seen is not None else set()
    if target in seen or target not in rules:
        return []
    seen.add(target)
    prerequisites, recipe = rules[target]
    lines = list(recipe)
    for prerequisite in prerequisites:
        lines += _chain(rules, prerequisite, seen)
    return lines


def makefile_problems(makefile: Path, root: Path) -> list[str]:
    where = makefile.relative_to(root)
    rules = makefile_rules(makefile.read_text("utf-8"))
    problems = []
    for target, (_, recipe) in rules.items():
        for line in recipe:
            if PACKAGE_FLAG.search(line):
                problems.append(f"{where}: `{target}` names a package in a flag: {line}")
            if UV_SYNC.search(line):
                problems.append(f"{where}: `{target}` runs uv sync itself; depend on `reinit`")
    if "reinit" in rules:
        recipe = rules["reinit"][1]
        match = REINIT_RECIPE.match(recipe[0]) if len(recipe) == 1 else None
        if not match:
            problems.append(f"{where}: `reinit` must be a single `python3 <path>/uv_project.py reinit`")
        elif (makefile.parent / match.group(1)).resolve() != (root / "scripts" / "uv_project.py"):
            problems.append(f"{where}: `reinit` calls {match.group(1)}, which is not scripts/uv_project.py")
    return problems


def missing_reinit(root: Path) -> list[str]:
    problems = []
    for project in uv_project.locked_projects(root):
        if not (project / "tests").is_dir():
            continue
        try:
            internal = uv_project.wheelhouse_packages(project, root / uv_project.WHEELHOUSE_NAME)
        except uv_project.DerivationError as exc:
            problems.append(str(exc))
            continue
        makefile = project / "Makefile"
        rules = makefile_rules(makefile.read_text("utf-8")) if makefile.is_file() else {}
        if internal and "reinit" not in rules:
            problems.append(
                f"{project.relative_to(root)}: installs {', '.join(internal)} from the "
                f"wheelhouse but has no `reinit` target"
            )
    return problems


def dockerfile_stages(text: str) -> list[list[str]]:
    """Instructions grouped by stage, comments dropped and continuations joined."""
    stages: list[list[str]] = [[]]
    for line in logical_lines(text):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if re.match(r"(?i)^FROM\s", stripped) and stages[-1]:
            if any(re.match(r"(?i)^FROM\s", i) for i in stages[-1]):
                stages.append([])
        stages[-1].append(re.sub(r"\s+", " ", stripped))
    return stages


def _copies_wheelhouse(instruction: str) -> bool:
    return bool(re.match(r"(?i)^COPY\s", instruction)) and bool(re.search(r"(^|\s)\.dist/?(\s|$)", instruction))


def dockerfile_problems(dockerfile: Path, root: Path, distributions: set[str]) -> list[str]:
    where = dockerfile.relative_to(root)
    stages = dockerfile_stages(dockerfile.read_text("utf-8"))
    if not any(_copies_wheelhouse(i) for stage in stages for i in stage):
        return []
    problems = []
    pin = re.compile(r"\b([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==[0-9]")
    for number, stage in enumerate(stages):
        copied = set()
        for instruction in stage:
            if re.match(r"(?i)^COPY\s", instruction) and "uv_project.py" in instruction:
                destination = instruction.split()[-1]
                copied.add(destination.rstrip("/") + "/uv_project.py" if destination.endswith("/") else destination)
        for instruction in stage:
            if PACKAGE_FLAG.search(instruction):
                problems.append(f"{where}: names a package in a flag: {instruction[:120]}")
            if "sed " in instruction and "registry" in instruction:
                problems.append(f"{where}: rewrites a lock's registry: {instruction[:120]}")
            for name in pin.findall(instruction):
                if uv_project.normalise(name) in distributions:
                    problems.append(f"{where}: spells the version of {name}; install-wheel reads it")
            if re.match(r"(?i)^RUN\s", instruction):
                if UV_SYNC.search(instruction) or re.search(r"\buv\s+pip\s+install\b[^&;|]*--find-links", instruction):
                    problems.append(f"{where}: installs from the wheelhouse without uv_project.py")
                for called in SCRIPT_CALL.findall(instruction):
                    if called not in copied:
                        problems.append(f"{where}: calls {called}, which this stage did not copy there")
        if number == len(stages) - 1 and len(stages) > 1 and any(_copies_wheelhouse(i) for i in stage):
            problems.append(f"{where}: the runtime stage copies the wheelhouse")
    return problems


def problems(root: Path = ROOT) -> list[str]:
    found = []
    for makefile in _files(root, "Makefile"):
        found += makefile_problems(makefile, root)
    found += missing_reinit(root)
    distributions = set(uv_project.repository_versions(root))
    for dockerfile in _files(root, "Dockerfile*"):
        if not dockerfile.name.endswith(".dockerignore"):
            found += dockerfile_problems(dockerfile, root, distributions)
    return found


def main() -> int:
    found = problems()
    for problem in found:
        print(problem)
    if found:
        print(f"\n{len(found)} uv setup problem(s). See docs/development/BUILD_AND_PACKAGING.md.")
        return 1
    print("OK: every environment and image install derives its internal packages from its lock.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
