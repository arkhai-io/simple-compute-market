"""Reject a lock that pins an internal wheel at a version this tree does not build.

Internal packages are built into `.dist` from source and installed from those
wheels (see `docs/development/ARCHITECTURE.md#build-packaging-and-initialization`).
A clean checkout's `.dist` holds exactly the versions the tree's `pyproject.toml`
files declare. A lock that still pins an earlier version resolves on a machine
whose `.dist` happens to retain the old wheel, and fails everywhere else, first
in CI. `uv lock` keeps a pin that still satisfies its constraint, so bumping a
package's version does not by itself move its consumers' locks; each must be
relocked with `--upgrade-package <n>`.

Scope: packages a lock resolves from a local wheel directory. Packages from a
public index, from source, or the project itself are out of scope.

Exit status 1 lists every stale pin; 0 means none.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: Directories never scanned: environments, build output, and change history.
SKIPPED_PARTS = {".venv", "node_modules", ".git", "build", "openspec", ".dist"}


def _scanned(path: Path) -> bool:
    return not SKIPPED_PARTS.intersection(path.relative_to(ROOT).parts)


def _normalise(name: str) -> str:
    return name.replace("_", "-").replace(".", "-").lower()


def built_versions(root: Path) -> dict[str, str]:
    """Each internal distribution's name and the version its source declares."""
    versions: dict[str, str] = {}
    for pyproject in root.rglob("pyproject.toml"):
        if not _scanned(pyproject):
            continue
        try:
            project = tomllib.loads(pyproject.read_text("utf-8")).get("project", {})
        except tomllib.TOMLDecodeError:
            continue
        name, version = project.get("name"), project.get("version")
        if isinstance(name, str) and isinstance(version, str):
            versions[_normalise(name)] = version
    return versions


def stale_pins(root: Path) -> list[str]:
    versions = built_versions(root)
    problems: list[str] = []
    for lock in sorted(root.rglob("uv.lock")):
        if not _scanned(lock):
            continue
        for package in tomllib.loads(lock.read_text("utf-8")).get("package", []):
            registry = (package.get("source") or {}).get("registry", "")
            if not registry or registry.startswith(("http://", "https://")):
                continue
            name = _normalise(str(package.get("name", "")))
            expected = versions.get(name)
            if expected is not None and package.get("version") != expected:
                problems.append(
                    f"  {lock.parent.relative_to(root)}: {name} locked at "
                    f"{package.get('version')}, tree builds {expected}"
                )
    return problems


def main() -> int:
    problems = stale_pins(ROOT)
    if problems:
        print("Locks pinning an internal wheel this tree no longer builds:")
        print("\n".join(problems))
        print(
            "Relock each project with `uv lock --find-links <relative .dist> "
            "--upgrade-package <n>`."
        )
        return 1
    print("OK: every lock pins the internal wheel versions this tree builds.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
