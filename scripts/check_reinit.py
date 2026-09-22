"""Reject a `reinit` target that does not reinstall every internal wheel it uses.

Internal packages are built into `.dist` and installed from wheels (see
`docs/development/ARCHITECTURE.md#build-packaging-and-initialization`). A
rebuilt wheel keeps its version, so `uv sync` keeps whatever copy an
environment already holds unless told to replace it; `AGENTS.md` therefore
requires each `reinit` target to upgrade and reinstall the internal packages
it uses. When one is missing, a test run silently exercises a stale copy of
that package, and the failure surfaces later as an import error or, worse, as
a test passing against code that no longer exists.

A project's `uv.lock` is the record of what its environment installs. Every
internal package that lock resolves from a local wheel directory must appear
as `--reinstall-package` in the project's `reinit` recipe, or in a recipe that
`reinit` depends on in the same Makefile. A project whose lock resolves any
internal package from a local wheel directory must have a `reinit` target at
all. Packages the lock takes from a public index, from source (editable or
path), or as the project itself are out of scope: `reinit` cannot refresh
them from `.dist`. A project with no `tests` directory is out of scope too:
it has no test environment for a stale wheel to corrupt.

Exit status 1 lists every gap; 0 means none.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Directories never scanned: environments, build output, and change history.
SKIPPED_PARTS = {".venv", "node_modules", ".git", "build", "openspec", ".dist"}

#: A Make rule line: a target name, then a single colon (not `:=`).
RULE = re.compile(r"^([A-Za-z0-9_.-]+):(?!=)(.*)$")


def _scanned(path: Path, root: Path) -> bool:
    return not SKIPPED_PARTS.intersection(path.relative_to(root).parts)


def internal_packages(root: Path) -> set[str]:
    """Every distribution name a `pyproject.toml` in the repository declares."""
    names: set[str] = set()
    for pyproject in root.rglob("pyproject.toml"):
        if not _scanned(pyproject, root):
            continue
        try:
            project = tomllib.loads(pyproject.read_text("utf-8")).get("project", {})
        except tomllib.TOMLDecodeError:
            continue
        if isinstance(project.get("name"), str):
            names.add(_normalise(project["name"]))
    return names


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def wheel_installed(lock: Path, internal: set[str]) -> set[str]:
    """Internal packages the lock resolves from a local wheel directory."""
    data = tomllib.loads(lock.read_text("utf-8"))
    found: set[str] = set()
    for package in data.get("package", []):
        name = _normalise(package.get("name", ""))
        registry = (package.get("source") or {}).get("registry")
        if name in internal and isinstance(registry, str) and "://" not in registry:
            found.add(name)
    return found


def recipes(makefile_text: str) -> dict[str, tuple[list[str], str]]:
    """Target -> (prerequisites, recipe text), for rules in one Makefile.

    A recipe runs from its rule line to the next rule line. Comment and blank
    lines inside it do not end it, because Make does not end a recipe there
    either.
    """
    out: dict[str, tuple[list[str], list[str]]] = {}
    current: str | None = None
    for line in makefile_text.splitlines():
        match = RULE.match(line)
        if match and not line.startswith("\t"):
            current = match.group(1)
            prerequisites = match.group(2).split("##", 1)[0].split()
            out[current] = (prerequisites, [])
        elif current is not None:
            out[current][1].append(line)
    return {target: (deps, "\n".join(body)) for target, (deps, body) in out.items()}


def reinstalled(rules: dict[str, tuple[list[str], str]], target: str) -> set[str]:
    """Packages `target` and its in-file prerequisites reinstall."""
    seen: set[str] = set()
    found: set[str] = set()
    pending = [target]
    while pending:
        name = pending.pop()
        if name in seen or name not in rules:
            continue
        seen.add(name)
        prerequisites, body = rules[name]
        found.update(
            _normalise(p) for p in re.findall(r"--reinstall-package\s+([A-Za-z0-9_.-]+)", body)
        )
        pending.extend(prerequisites)
    return found


def problems(root: Path) -> list[str]:
    internal = internal_packages(root)
    found: list[str] = []
    for lock in sorted(root.rglob("uv.lock")):
        if not _scanned(lock, root):
            continue
        needed = wheel_installed(lock, internal)
        if not needed:
            continue
        project = lock.parent
        if not (project / "tests").is_dir():
            continue
        where = project.relative_to(root).as_posix() or "."
        makefile = project / "Makefile"
        rules = recipes(makefile.read_text("utf-8")) if makefile.exists() else {}
        if "reinit" not in rules:
            found.append(
                f"{where}: no reinit target, but its lock installs internal wheels: "
                + ", ".join(sorted(needed))
            )
            continue
        missing = needed - reinstalled(rules, "reinit")
        if missing:
            found.append(
                f"{where}: reinit does not reinstall " + ", ".join(sorted(missing))
            )
    return found


def main() -> int:
    found = problems(ROOT)
    if not found:
        print("OK: every reinit target reinstalls each internal wheel its lock installs.")
        return 0
    print("Internal wheels a reinit target would leave stale:")
    for problem in found:
        print(f"  {problem}")
    print(
        "Add `--upgrade-package <name> --reinstall-package <name>` to each "
        "project's reinit recipe."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
