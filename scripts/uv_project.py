"""Run uv for a project against the repository wheelhouse.

A rebuilt internal wheel keeps its version, so uv keeps both an environment's
installed copy of it and the dependencies a lock recorded for it unless told
otherwise. `--reinstall-package` replaces the installed code;
`--upgrade-package` makes uv re-read the wheel's metadata and rewrite the
dependencies the lock records. This script derives the internal packages from
the project's `uv.lock` when it runs, so no caller lists them:

- `reinit` syncs the project environment, upgrading and reinstalling every
  internal package. It may rewrite the lock; that rewrite is what to commit.
- `image -- <uv sync options>` syncs an image environment from the committed
  lock with `--locked`, reinstalling every internal package so a persistent
  uv cache cannot supply a previous build of a same-version wheel.
- `install-wheel` installs the project's own distribution, at the version its
  `pyproject.toml` declares, from the wheelhouse alone.
- `lock [PROJECT ...]` relocks projects against the current wheelhouse and
  installs nothing. It upgrades every internal package and every other
  repository distribution the lock names, so one that has drifted to a
  package index returns to the wheelhouse.

An internal package is one the lock resolves from the repository wheelhouse.
A lock that resolves anything from another local path is an error. Any
derivation failure exits non-zero before a uv command runs.

Conventions and the checks that enforce them:
docs/development/BUILD_AND_PACKAGING.md.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WHEELHOUSE_NAME = ".dist"
PYTHON_DECLARATION = ".python-version"
_SKIPPED_DIRS = {".venv", "node_modules", "openspec", ".git"}

Runner = Callable[[Sequence[str], Path], int]


class DerivationError(Exception):
    """A fact the command needs could not be derived from the project."""


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text("utf-8"))
    except FileNotFoundError:
        raise DerivationError(f"{path} does not exist") from None
    except tomllib.TOMLDecodeError as exc:
        raise DerivationError(f"{path} is not valid TOML: {exc}") from None


def wheelhouse_packages(project: Path, wheelhouse: Path) -> list[str]:
    """Normalised names the project's lock resolves from ``wheelhouse``."""
    lock = project / "uv.lock"
    names: set[str] = set()
    for package in _read_toml(lock).get("package", []):
        registry = (package.get("source") or {}).get("registry")
        if not isinstance(registry, str) or "://" in registry:
            continue
        if (project / registry).resolve() != wheelhouse.resolve():
            raise DerivationError(
                f"{lock} resolves {package['name']} from {registry}, which is "
                f"not the repository wheelhouse"
            )
        names.add(normalise(package["name"]))
    return sorted(names)


def declared_distribution(project: Path) -> tuple[str, str]:
    """The project's distribution name and version from its pyproject."""
    pyproject = project / "pyproject.toml"
    declared = _read_toml(pyproject).get("project", {})
    name, version = declared.get("name"), declared.get("version")
    if not name or not version:
        raise DerivationError(f"{pyproject} declares no project name and version")
    return name, version


def declared_python(root: Path) -> str:
    path = root / PYTHON_DECLARATION
    try:
        version = path.read_text("utf-8").strip()
    except FileNotFoundError:
        raise DerivationError(f"{path} does not exist") from None
    if not version:
        raise DerivationError(f"{path} is empty")
    return version


def repository_versions(root: Path) -> dict[str, str]:
    """The declared version of every distribution a repository project declares."""
    versions = {}
    for pyproject in sorted(root.rglob("pyproject.toml")):
        if _SKIPPED_DIRS & set(pyproject.relative_to(root).parts):
            continue
        try:
            name, version = declared_distribution(pyproject.parent)
        except DerivationError:
            continue
        versions[normalise(name)] = version
    return versions


def relative_wheelhouse(project: Path, wheelhouse: Path) -> str:
    """The wheelhouse relative to the project, so every lock records one path."""
    return os.path.relpath(wheelhouse.resolve(), project.resolve())


def _each(flag: str, values: Sequence[str]) -> list[str]:
    return [arg for value in values for arg in (flag, value)]


def reinit_command(project: Path, root: Path) -> list[str]:
    wheelhouse = root / WHEELHOUSE_NAME
    internal = wheelhouse_packages(project, wheelhouse)
    command = [
        "uv", "sync",
        "--python", declared_python(root),
        "--find-links", relative_wheelhouse(project, wheelhouse),
    ]
    for name in internal:
        command += ["--upgrade-package", name, "--reinstall-package", name]
    return command


def image_command(project: Path, root: Path, options: Sequence[str]) -> list[str]:
    wheelhouse = root / WHEELHOUSE_NAME
    internal = wheelhouse_packages(project, wheelhouse)
    return [
        "uv", "sync", "--locked",
        "--find-links", relative_wheelhouse(project, wheelhouse),
        *options,
        *_each("--reinstall-package", internal),
    ]


def install_wheel_command(project: Path, root: Path, environment: Path) -> list[str]:
    name, version = declared_distribution(project)
    return [
        "uv", "pip", "install",
        "--python", str(environment / "bin" / "python"),
        "--no-deps", "--no-index", "--reinstall",
        "--find-links", str((root / WHEELHOUSE_NAME).resolve()),
        f"{name}=={version}",
    ]


def lock_command(project: Path, root: Path, repository: set[str]) -> list[str]:
    wheelhouse = root / WHEELHOUSE_NAME
    internal = set(wheelhouse_packages(project, wheelhouse))
    named = {normalise(p["name"]) for p in _read_toml(project / "uv.lock").get("package", [])}
    own = normalise(declared_distribution(project)[0])
    upgrade = sorted(internal | (named & repository) - {own})
    return [
        "uv", "lock",
        "--find-links", relative_wheelhouse(project, wheelhouse),
        *_each("--upgrade-package", upgrade),
    ]


def locked_projects(root: Path) -> list[Path]:
    """Every project directory holding both a pyproject and a lock."""
    projects = []
    for lock in root.rglob("uv.lock"):
        if _SKIPPED_DIRS & set(lock.relative_to(root).parts):
            continue
        if (lock.parent / "pyproject.toml").is_file():
            projects.append(lock.parent)
    return sorted(projects)


def _run(command: Sequence[str], cwd: Path) -> int:
    print("+ " + " ".join(command), file=sys.stderr, flush=True)
    return subprocess.run(list(command), cwd=cwd).returncode


def _environment(project: Path) -> Path:
    configured = os.environ.get("UV_PROJECT_ENVIRONMENT")
    return Path(configured) if configured else project / ".venv"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("reinit", "sync the project environment, refreshing internal packages"),
        ("install-wheel", "install the project's own wheel from the wheelhouse"),
    ):
        sub = commands.add_parser(name, help=help_text)
        sub.add_argument("--project", type=Path, default=Path.cwd())
    image = commands.add_parser("image", help="sync an image environment from the lock")
    image.add_argument("--project", type=Path, default=Path.cwd())
    image.add_argument("options", nargs=argparse.REMAINDER,
                       help="uv sync options after `--`")
    lock = commands.add_parser("lock", help="relock projects without installing")
    lock.add_argument("projects", nargs="*", type=Path,
                      help="project directories; every locked project when omitted")
    return parser


def main(argv: Sequence[str] | None = None, *, root: Path = ROOT,
         run: Runner = _run) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "lock":
            projects = [p.resolve() for p in args.projects] or locked_projects(root)
            repository = set(repository_versions(root))
            planned = [(project, lock_command(project, root, repository)) for project in projects]
        else:
            project = args.project.resolve()
            if args.command == "reinit":
                command = reinit_command(project, root)
            elif args.command == "image":
                options = args.options[1:] if args.options[:1] == ["--"] else args.options
                command = image_command(project, root, options)
            else:
                command = install_wheel_command(project, root, _environment(project))
            planned = [(project, command)]
    except DerivationError as exc:
        print(f"uv_project: {exc}", file=sys.stderr)
        return 2

    failed = [project for project, command in planned if run(command, project) != 0]
    for project in failed:
        print(f"uv_project: {args.command} failed in {project}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
