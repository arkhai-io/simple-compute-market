"""Fail if a project departs from the repository's one project layout.

Every repository distribution builds its wheel from exactly one import
package at `src/<package>` with hatchling, and every project environment
installs it editable. This check rejects:

- a distribution whose wheel target is anything but
  `packages = ["src/<package>"]` naming a package that exists, or that
  remaps, includes, or excludes files through other build settings;
- a `[tool.uv]` `find-links` declaration or `cache-keys` list;
- a `[tool.uv.sources]` entry that names a path;
- `UV_NO_EDITABLE`, `--no-editable`, or `no_editable` in a Makefile, shell
  script, or CI workflow.

A virtual project (`[tool.uv] package = false`) builds no wheel, so the wheel
rule does not reach it. Dockerfiles are not scanned for editability: an image
installs its project's own wheel, which is not an editable install.

Conventions: docs/development/BUILD_AND_PACKAGING.md.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIPPED_DIRS = {".venv", "node_modules", "openspec", ".git"}
_PACKAGE = re.compile(r"src/([A-Za-z_][A-Za-z0-9_]*)")
_EDITABLE_OFF = re.compile(r"UV_NO_EDITABLE|--no-editable|\bno_editable\b")


def _files(root: Path, pattern: str) -> list[Path]:
    return sorted(
        path for path in root.rglob(pattern)
        if path.is_file() and not SKIPPED_DIRS & set(path.relative_to(root).parts)
    )


def pyproject_problems(pyproject: Path, root: Path) -> list[str]:
    where = pyproject.parent.relative_to(root)
    declared = tomllib.loads(pyproject.read_text("utf-8"))
    if "project" not in declared:
        return []
    tool = declared.get("tool", {})
    uv = tool.get("uv", {})
    problems = []
    for key in ("find-links", "cache-keys"):
        if key in uv:
            problems.append(f"{where}: declares [tool.uv] {key}")
    for name, source in (uv.get("sources") or {}).items():
        for entry in source if isinstance(source, list) else [source]:
            if isinstance(entry, dict) and "path" in entry:
                problems.append(f"{where}: resolves {name} from the path {entry['path']}; use the wheelhouse")
    if uv.get("package") is False:
        return problems
    backend = declared.get("build-system", {}).get("build-backend", "")
    if not backend.startswith("hatchling"):
        problems.append(f"{where}: builds with {backend or 'no backend'}; use hatchling")
        return problems
    build = tool.get("hatch", {}).get("build", {})
    target = build.get("targets", {}).get("wheel", {})
    extra = sorted(k for k in build if k != "targets") + sorted(k for k in target if k != "packages")
    packages = target.get("packages", [])
    match = _PACKAGE.fullmatch(packages[0]) if len(packages) == 1 else None
    if extra or not match:
        problems.append(
            f"{where}: the wheel target must be exactly packages = [\"src/<package>\"]"
            + (f" (also sets {', '.join(extra)})" if extra else "")
        )
    elif not (pyproject.parent / packages[0] / "__init__.py").is_file():
        problems.append(f"{where}: {packages[0]} is not a package")
    return problems


def editable_problems(root: Path) -> list[str]:
    sources = _files(root, "Makefile") + _files(root, "*.mk") + _files(root, "*.sh") + [
        p for p in _files(root, "*.yml") if p.relative_to(root).parts[:2] == (".github", "workflows")
    ]
    problems = []
    for path in sources:
        for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
            if not line.lstrip().startswith("#") and _EDITABLE_OFF.search(line):
                problems.append(f"{path.relative_to(root)}:{number}: disables editable installs")
    return problems


def problems(root: Path = ROOT) -> list[str]:
    found = []
    for pyproject in _files(root, "pyproject.toml"):
        found += pyproject_problems(pyproject, root)
    return found + editable_problems(root)


def main() -> int:
    found = problems()
    for problem in found:
        print(problem)
    if found:
        print(f"\n{len(found)} project layout problem(s). See docs/development/BUILD_AND_PACKAGING.md.")
        return 1
    print("OK: every distribution is one package under src/ and installs editable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
