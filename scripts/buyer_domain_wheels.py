"""Derive what the release's `market` binary bundles from the declaration.

The binary freezes the buyer CLI, the declared distribution whose project
defines the binary's name as a console script, with every declared distribution
whose project registers a `market.buyer_domains` entry point. Both are found
here, from `manifests/release-components.json` and each declared project's
`pyproject.toml`, so no Dockerfile or Makefile lists the buyer domains: a
domain declared and published but missing from the binary would make the
release's `market` a different program from PyPI's.

`make build-market-binary` passes each command's output to the binary's build
image as a build argument:

- `domains` (the default) prints each buyer domain's wheel file name, one per
  line;
- `cli` prints the buyer CLI's wheel file name;
- `entry-point` prints the console script the binary freezes, `module:function`;
- `constraints` prints `<distribution>==<version>` for every declared
  distribution, one per line, so the image installs the declared versions;
- `pyinstaller-options` prints the options that bundle each domain: discovery
  reads installed entry-point metadata and imports each domain by name, so
  PyInstaller sees neither unless told.

`domains` and `cli` refuse a wheel the wheelhouse does not hold.
"""

from __future__ import annotations

import argparse
import sys
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from release_components import (
    DECLARATION_PATH,
    REPO_ROOT,
    DeclarationError,
    Distribution,
    ReleaseComponents,
    load,
    project_version,
    wheel_file_name,
)

DOMAIN_GROUP = "market.buyer_domains"
BINARY_NAME = "market"


@dataclass(frozen=True)
class Bundled:
    """A declared distribution the binary bundles, with its wheel file name and the
    modules its entry points name."""

    distribution: Distribution
    wheel: str
    modules: tuple[str, ...]


@dataclass(frozen=True)
class BinaryInputs:
    cli: Bundled
    entry_point: str
    domains: tuple[Bundled, ...]


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


def _bundled(root: Path, distribution: Distribution, entry_points: Sequence[str]) -> Bundled:
    return Bundled(
        distribution=distribution,
        wheel=wheel_file_name(distribution, project_version(root, distribution)),
        modules=tuple(dict.fromkeys(_module(value) for value in entry_points)),
    )


def inputs(components: ReleaseComponents, root: Path = REPO_ROOT,
           binary: str = BINARY_NAME) -> BinaryInputs:
    """The buyer CLI, its entry point and the buyer domains, in declaration order.

    Refuses unless exactly one declared distribution defines `binary` as a
    console script and at least one registers a buyer domain.
    """
    clis: list[tuple[Distribution, str]] = []
    domains: list[Bundled] = []
    for distribution in components.distributions:
        project = _project(root, distribution)
        script = (project.get("scripts") or {}).get(binary)
        if isinstance(script, str):
            clis.append((distribution, script))
        registered = ((project.get("entry-points") or {}).get(DOMAIN_GROUP) or {})
        if registered:
            domains.append(_bundled(root, distribution, list(registered.values())))
    if len(clis) != 1:
        found = ", ".join(entry.dist for entry, _ in clis) or "none"
        raise DeclarationError(
            f"exactly one declared distribution must define the `{binary}` console "
            f"script; found {found}"
        )
    if not domains:
        raise DeclarationError(f"no declared distribution registers a {DOMAIN_GROUP} entry point")
    distribution, script = clis[0]
    return BinaryInputs(
        cli=_bundled(root, distribution, [script]),
        entry_point=script.strip(),
        domains=tuple(domains),
    )


def _present(wheels: Sequence[str], dist_dir: Path) -> list[str]:
    missing = [wheel for wheel in wheels if not (dist_dir / wheel).is_file()]
    if missing:
        raise DeclarationError(
            f"{dist_dir} holds no {', '.join(missing)}; build the wheelhouse with `make dist`"
        )
    return list(wheels)


def output(command: str, components: ReleaseComponents, root: Path, dist_dir: Path) -> list[str]:
    """The lines `command` prints."""
    if command == "constraints":
        lines = []
        for entry in components.distributions:
            _project(root, entry)
            lines.append(f"{entry.dist}=={project_version(root, entry)}")
        return lines
    found = inputs(components, root)
    if command == "domains":
        return _present([domain.wheel for domain in found.domains], dist_dir)
    if command == "cli":
        return _present([found.cli.wheel], dist_dir)
    if command == "entry-point":
        return [found.entry_point]
    options = []
    for bundled in (found.cli, *found.domains):
        options += ["--copy-metadata", bundled.distribution.dist]
    for domain in found.domains:
        for module in domain.modules:
            options += ["--hidden-import", module]
    return [" ".join(options)]


COMMANDS = ("domains", "cli", "entry-point", "constraints", "pyinstaller-options")


def main(argv: Sequence[str] | None = None, *, root: Path = REPO_ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", nargs="?", default="domains", choices=COMMANDS)
    parser.add_argument("--dist-dir", type=Path, default=None,
                        help="the wheelhouse; .dist under the repository by default")
    args = parser.parse_args(argv)
    dist_dir = args.dist_dir or root / ".dist"
    try:
        lines = output(args.command, load(root / DECLARATION_PATH), root, dist_dir)
    except DeclarationError as error:
        print(f"buyer_domain_wheels: {error}", file=sys.stderr)
        return 1
    for line in lines:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
