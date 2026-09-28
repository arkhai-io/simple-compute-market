"""Fail if anything selects a Python version other than the root declaration.

The repository declares one Python version, in the root `.python-version`.
uv does not read that file from a nested project, so every consumer reads it
explicitly, and this check rejects:

- a `.python-version` file anywhere but the root;
- a `--python` flag with a literal version in a Makefile, shell script, or
  tool phase configuration;
- a Makefile that runs uv without exporting `UV_PYTHON` read from the root
  declaration by a path that resolves;
- a CI job that runs uv without setting `UV_PYTHON` from the declaration, or
  a `python-version` setup pin of another minor version;
- a Dockerfile `FROM` naming a Python version literally, or a
  `PYTHON_VERSION` build argument defaulting to another version.

Conventions: docs/development/BUILD_AND_PACKAGING.md.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECLARATION = ".python-version"
SKIPPED_DIRS = {".venv", "node_modules", "openspec", ".git"}

_LITERAL_FLAG = re.compile(r"--python[= ]+[\"']?\d+\.\d+")
_RUNS_UV = re.compile(r"\buv\s+(run|sync|pip|lock|venv|build)\b")
_EXPORT = re.compile(
    r"^export UV_PYTHON := \$\(or \$\(shell cat (\S+) 2>/dev/null\),\$\(error \S+ not found\)\)\s*$",
    re.M,
)
_CI_EXPORT = 'echo "UV_PYTHON=$(cat .python-version)" >> "$GITHUB_ENV"'
_LITERAL_IMAGE = re.compile(r"(?i)^FROM\s.*\bpython:?3\.\d+")
_ARG = re.compile(r"^ARG PYTHON_VERSION=(\S+)\s*$", re.M)
_SETUP_PIN = re.compile(r"python-version:\s*[\"']?(\d+\.\d+)")


def _files(root: Path, pattern: str) -> list[Path]:
    return sorted(
        path for path in root.rglob(pattern)
        if path.is_file() and not SKIPPED_DIRS & set(path.relative_to(root).parts)
    )


def _uncommented(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def declared(root: Path) -> str | None:
    path = root / DECLARATION
    if not path.is_file():
        return None
    value = path.read_text("utf-8").strip()
    return value if re.fullmatch(r"\d+\.\d+", value) else None


def ci_problems(workflow: Path, root: Path, version: str) -> list[str]:
    where = workflow.relative_to(root)
    problems = []
    text = workflow.read_text("utf-8")
    for pin in _SETUP_PIN.findall(text):
        if pin != version:
            problems.append(f"{where}: sets up Python {pin}; the repository declares {version}")
    jobs = re.split(r"^  (?=[A-Za-z0-9_-]+:\s*$)", text.split("\njobs:", 1)[-1], flags=re.M)
    for job in jobs[1:]:
        name = job.split(":", 1)[0]
        if _RUNS_UV.search(_uncommented(job)) and _CI_EXPORT not in job:
            problems.append(f"{where}: job `{name}` runs uv without UV_PYTHON from {DECLARATION}")
    return problems


def problems(root: Path = ROOT) -> list[str]:
    version = declared(root)
    if version is None:
        return [f"{DECLARATION} is missing or is not a MAJOR.MINOR version"]
    found = []
    for extra in _files(root, DECLARATION):
        if extra.parent != root:
            found.append(f"{extra.relative_to(root)}: only the root declares the Python version")
    literal_sources = _files(root, "Makefile") + _files(root, "*.sh") + [
        p for p in _files(root, "*.yaml") if p.relative_to(root).parts[0] == "tools"
    ]
    for path in literal_sources:
        for line in _uncommented(path.read_text("utf-8")).splitlines():
            if _LITERAL_FLAG.search(line):
                found.append(f"{path.relative_to(root)}: names a Python version: {line.strip()}")
    for makefile in _files(root, "Makefile"):
        text = makefile.read_text("utf-8")
        if not _RUNS_UV.search(_uncommented(text)):
            continue
        match = _EXPORT.search(text)
        if not match or (makefile.parent / match.group(1)).resolve() != (root / DECLARATION).resolve():
            found.append(f"{makefile.relative_to(root)}: runs uv without exporting UV_PYTHON from {DECLARATION}")
    for workflow in _files(root, "*.yml"):
        if workflow.relative_to(root).parts[:2] == (".github", "workflows"):
            found += ci_problems(workflow, root, version)
    for dockerfile in _files(root, "Dockerfile*"):
        if dockerfile.name.endswith(".dockerignore"):
            continue
        text = _uncommented(dockerfile.read_text("utf-8"))
        where = dockerfile.relative_to(root)
        for line in text.splitlines():
            if _LITERAL_IMAGE.match(line.strip()):
                found.append(f"{where}: names a Python version in FROM; use ARG PYTHON_VERSION")
        for default in _ARG.findall(text):
            if default != version:
                found.append(f"{where}: PYTHON_VERSION defaults to {default}; the repository declares {version}")
    return found


def main() -> int:
    found = problems()
    for problem in found:
        print(problem)
    if found:
        print(f"\n{len(found)} Python version problem(s). See docs/development/BUILD_AND_PACKAGING.md.")
        return 1
    print("OK: every Python version selection reads the root declaration.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
