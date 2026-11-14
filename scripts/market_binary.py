"""Derive the release's `market` binary from the declaration.

The binary freezes the buyer CLI, the declared distribution whose project
defines the binary's name as a console script, with every declared distribution
whose project registers a `market.buyer_domains` entry point. Both are found
here, from `manifests/release-components.json` and each declared project's
`pyproject.toml`. The binary's locked project, `core/buyer/market-binary`,
lists them as its dependencies, and `make check-market-binary` holds that list
equal to what this script derives: a domain declared and published but missing
from the binary would make the release's `market` a different program from
PyPI's, and so would an undeclared one, which PyPI does not serve.

The binary is the declaration's `binaries[]` entry whose `target` the caller
names (`--target`); `make build-market-binary` passes its own name. Its `name`
is the console script, and its `path` the file the build exports, which must
end in that name. `make build-market-binary` passes each command's output to
the binary's build image:

- `name` prints the binary's name;
- `output-dir` prints the directory of the binary's `path`;
- `entry-point` prints the console script the binary freezes, `module:function`;
- `pyinstaller-options` prints the options that bundle each domain: discovery
  reads installed entry-point metadata and imports each domain by name, so
  PyInstaller sees neither unless told.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from release_components import (
    DECLARATION_PATH,
    REPO_ROOT,
    Binary,
    DeclarationError,
    Distribution,
    ReleaseComponents,
    load,
)

DOMAIN_GROUP = "market.buyer_domains"
# The release binary's build target, and the locked project its build image
# installs; the Dockerfile beside that project copies it by this path.
TARGET = "build-market-binary"
PROJECT = "core/buyer/market-binary"


@dataclass(frozen=True)
class Bundled:
    """A declared distribution the binary bundles, with the modules its entry
    points name."""

    distribution: Distribution
    modules: tuple[str, ...]


@dataclass(frozen=True)
class BinaryInputs:
    cli: Bundled
    entry_point: str
    domains: tuple[Bundled, ...]


def binary(components: ReleaseComponents, target: str) -> Binary:
    """The declared binary `target` builds.

    Refuses no such entry, two of them, and a `path` whose file name is not the
    binary's `name`.
    """
    found = [entry for entry in components.binaries if entry.target == target]
    if len(found) != 1:
        raise DeclarationError(
            f"exactly one declared binary must name the build target {target}; "
            f"found {len(found)}"
        )
    entry = found[0]
    if PurePosixPath(entry.path).name != entry.name:
        raise DeclarationError(
            f"binary {entry.name}'s path {entry.path} does not end in its name"
        )
    return entry


def _project(root: Path, distribution: Distribution) -> dict:
    pyproject = root / distribution.path / "pyproject.toml"
    try:
        return tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {})
    except FileNotFoundError:
        raise DeclarationError(f"{pyproject} does not exist") from None
    except tomllib.TOMLDecodeError as error:
        raise DeclarationError(f"{pyproject} is not valid TOML: {error}") from None


def _module(entry_point: str) -> str:
    return entry_point.split(":", 1)[0].strip()


def _bundled(distribution: Distribution, entry_points: Sequence[str]) -> Bundled:
    return Bundled(
        distribution=distribution,
        modules=tuple(dict.fromkeys(_module(value) for value in entry_points)),
    )


def inputs(components: ReleaseComponents, root: Path, name: str) -> BinaryInputs:
    """The buyer CLI, its entry point and the buyer domains, in declaration order.

    Refuses unless exactly one declared distribution defines `name` as a
    console script and at least one registers a buyer domain.
    """
    clis: list[tuple[Distribution, str]] = []
    domains: list[Bundled] = []
    for distribution in components.distributions:
        project = _project(root, distribution)
        script = (project.get("scripts") or {}).get(name)
        if isinstance(script, str):
            clis.append((distribution, script))
        registered = ((project.get("entry-points") or {}).get(DOMAIN_GROUP) or {})
        if registered:
            domains.append(_bundled(distribution, list(registered.values())))
    if len(clis) != 1:
        found = ", ".join(entry.dist for entry, _ in clis) or "none"
        raise DeclarationError(
            f"exactly one declared distribution must define the `{name}` console "
            f"script; found {found}"
        )
    if not domains:
        raise DeclarationError(f"no declared distribution registers a {DOMAIN_GROUP} entry point")
    distribution, script = clis[0]
    return BinaryInputs(
        cli=_bundled(distribution, [script]),
        entry_point=script.strip(),
        domains=tuple(domains),
    )


def output(command: str, components: ReleaseComponents, root: Path, target: str) -> list[str]:
    """The lines `command` prints."""
    entry = binary(components, target)
    if command == "name":
        return [entry.name]
    if command == "output-dir":
        return [str(PurePosixPath(entry.path).parent)]
    found = inputs(components, root, entry.name)
    if command == "entry-point":
        return [found.entry_point]
    options = []
    for bundled in (found.cli, *found.domains):
        options += ["--copy-metadata", bundled.distribution.dist]
    for domain in found.domains:
        for module in domain.modules:
            options += ["--hidden-import", module]
    return [" ".join(options)]


COMMANDS = ("name", "output-dir", "entry-point", "pyinstaller-options")


def main(argv: Sequence[str] | None = None, *, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", required=True,
                        help="the build target of the declared binary")
    parser.add_argument("command", choices=COMMANDS)
    args = parser.parse_args(argv)
    try:
        lines = output(args.command, load(root / DECLARATION_PATH), root, args.target)
    except DeclarationError as error:
        print(f"market_binary: {error}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
